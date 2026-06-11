// XeneonTouchDriver.cpp
//
// v10: driver loads and owns interface 0 (confirmed v9). This version:
//   1. Sends the mode-switch feature reports at Start:
//        0x21  Input Mode = 2 (multitouch), Device ID = 0
//        0x0A  Max Contacts = 10
//      (Payloads proven working from userspace via hidapi — see
//      userspace/xeneon_touch/mode_switch.py.)
//   2. Hex-dumps every input report in handleReport, then forwards to the
//      base class so the HID stack keeps flowing. The descriptor already
//      advertises the 0x0D multitouch collection, so once mode 2 is active
//      AppleUserHIDEventDriver may interpret digitizer events natively —
//      the dump tells us whether the 0x0D reports actually arrive and what
//      their real layout is before we write any custom dispatch.

#include "XeneonTouchDriver.h"
#include <USBDriverKit/USBDriverKit.h>   // descriptor parsing + free helpers
#include <DriverKit/IOTypes.h>
#include <DriverKit/IOLib.h>
#include <DriverKit/IOBufferMemoryDescriptor.h>
#include <DriverKit/IOMemoryMap.h>
#include <os/log.h>

#define LOG(fmt, ...) os_log(OS_LOG_DEFAULT, "XeneonTouchDriver: " fmt, ##__VA_ARGS__)

static constexpr uint8_t kReportIDInputMode   = 0x21;
static constexpr uint8_t kReportIDMaxContacts = 0x0A;

// Cap on per-report log lines so a 120 Hz touch stream doesn't drown the
// unified log. First N reports are dumped in full; after that, one line
// per kLogEvery.
static constexpr uint32_t kVerboseReports = 32;
static constexpr uint32_t kLogEvery       = 256;
static uint32_t gReportCount = 0;

// ── USB-level feature report helpers ──────────────────────────────────────────
// v10 lesson: IOUserUSBHostHIDDevice::setReport returned kIOReturnBadArgument
// (0xE00002C2) for every attempt — the HID-layer path is picky about
// completions/sizes. We own the IOUSBHostInterface, so send the HID class
// SET_REPORT control transfer ourselves (USB HID 1.11 §7.2.2).
//   bmRequestType 0x21 = host→device | class | interface
//   bRequest      0x09 = SET_REPORT
//   wValue        (3 << 8) | reportID   (3 = feature)
//   wIndex        interface number (0)
//   data          full report INCLUDING the ID byte (matches Linux usbhid /
//                 Windows HidD_SetFeature framing, the paths this firmware
//                 is known to accept)
static constexpr uint8_t  kHIDRequestSetReport = 0x09;
static constexpr uint8_t  kHIDRequestGetReport = 0x01;
static constexpr uint16_t kHIDReportTypeFeatureWValue = 0x0300;
static constexpr uint16_t kInterfaceNumber = 0;

static kern_return_t sendFeatureUSB(IOUSBHostInterface *iface, uint8_t reportID,
                                    const uint8_t *data, uint16_t dataLen)
{
    IOBufferMemoryDescriptor *buf = nullptr;
    kern_return_t ret = IOBufferMemoryDescriptor::Create(
        kIOMemoryDirectionOut, dataLen, 0, &buf);
    if (ret != kIOReturnSuccess || !buf) {
        LOG("feature 0x%02X: buffer create failed 0x%08X", reportID, ret);
        return ret;
    }
    IOAddressSegment range = {};
    buf->GetAddressRange(&range);
    if (range.address) memcpy(reinterpret_cast<void *>(range.address), data, dataLen);
    buf->SetLength(dataLen);

    uint16_t transferred = 0;
    ret = iface->DeviceRequest(0x21, kHIDRequestSetReport,
                               kHIDReportTypeFeatureWValue | reportID,
                               kInterfaceNumber, dataLen,
                               buf, &transferred, 1000);
    buf->release();
    LOG("SET_REPORT feature 0x%02X (%u data bytes, first=0x%02X) -> 0x%08X (xfer=%u)",
        reportID, dataLen, data[0], ret, transferred);
    return ret;
}

// (GET_REPORT read-back removed in v12 — this firmware echoes the control
// setup packet back as data, so read-back proves nothing.)

// Generic IN control transfer with logging (v17)
static kern_return_t ctrlIn(IOUSBHostInterface *iface, uint8_t bmReq,
                            uint8_t bReq, uint16_t wValue, uint16_t wIndex,
                            uint16_t wLength, const char *tag)
{
    IOBufferMemoryDescriptor *buf = nullptr;
    if (IOBufferMemoryDescriptor::Create(kIOMemoryDirectionIn, wLength, 0, &buf)
            != kIOReturnSuccess || !buf) {
        LOG("%{public}s: buffer create failed", tag);
        return kIOReturnNoMemory;
    }
    buf->SetLength(wLength);
    uint16_t xfer = 0;
    kern_return_t ret = iface->DeviceRequest(bmReq, bReq, wValue, wIndex,
                                             wLength, buf, &xfer, 1000);
    IOAddressSegment r = {};
    buf->GetAddressRange(&r);
    const uint8_t *p = reinterpret_cast<const uint8_t *>(r.address);
    LOG("%{public}s -> 0x%08X xfer=%u first4: %02x %02x %02x %02x",
        tag, ret, xfer,
        xfer > 0 && p ? p[0] : 0, xfer > 1 && p ? p[1] : 0,
        xfer > 2 && p ? p[2] : 0, xfer > 3 && p ? p[3] : 0);
    buf->release();
    return ret;
}

kern_return_t XeneonTouchDriver::Start_Impl(IOService *provider)
{
    LOG(">>> Start_Impl (v17 - In-Line Handshake)");

    // 1. Let the parent class execute its native matching and open the provider
    kern_return_t ret = Start(provider, SUPERDISPATCH);
    if (ret != kIOReturnSuccess) {
        LOG("Super Start failed 0x%08X", ret);
        return ret;
    }

    IOUSBHostInterface *iface = OSDynamicCast(IOUSBHostInterface, provider);
    if (!iface) {
        LOG("provider is not IOUSBHostInterface?!");
        RegisterService();
        return kIOReturnSuccess;
    }
    LOG("Super Start OK. Hardware provider claimed safely.");

    // ── 2. EXECUTE YOUR ENTIRE WINDOWS REPLAY SEQUENCE HERE ──────────────────
    // The parent class has opened the interface, meaning the control endpoints
    // are wide open and safe for us to write to without hitting exclusive locks.
    
    for (int i = 0; i < 3; i++) {
        ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 4,   "GET_STR2 len4");
        ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 24,  "GET_STR2 len24");
    }

    static const uint16_t rdLen[3] = { 768, 102, 144 };
    for (uint16_t ifnum = 0; ifnum <= 2; ifnum++) {
        uint16_t xfer = 0;
        iface->DeviceRequest(0x21, 0x0A, 0x0000, ifnum, 0, nullptr, &xfer, 1000);
        char tag[16] = { 'R', 'D', (char)('0' + ifnum), 0 };
        ctrlIn(iface, 0x81, 0x06, 0x2200, ifnum, rdLen[ifnum], tag);
    }

    ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 514, "GET_STR2 len514");
    ctrlIn(iface, 0xA1, kHIDRequestGetReport, kHIDReportTypeFeatureWValue | kReportIDMaxContacts, kInterfaceNumber, 2, "GET_REPORT 0x0A");

    const uint8_t modeFramed[] = { 0x21, 0x02, 0x00 };
    sendFeatureUSB(iface, kReportIDInputMode, modeFramed, sizeof(modeFramed));

    LOG("Windows initialization replay complete. Hardware mode switched.");

    // ── 3. FORCE THE DRIVERKIT HID ENGINE TO RE-PARSE THE STREAM ──────────────
    // Because the hardware was changed from single-touch to multi-touch *after*
    // the parent class initialized, we must manually tickle the input report loop
    // to pick up the updated multi-touch descriptors.
    ret = initInputReport();
    LOG("Manual initInputReport re-trigger -> 0x%08X", ret);

    RegisterService();
    return kIOReturnSuccess;
}

// ── Start ─────────────────────────────────────────────────────────────────────
//kern_return_t XeneonTouchDriver::Start_Impl(IOService *provider)
//{
//    LOG(">>> Start_Impl (v17)");
//
//    kern_return_t ret = Start(provider, SUPERDISPATCH);
//    if (ret != kIOReturnSuccess) {
//        LOG("Super Start failed 0x%08X", ret);
//        return ret;
//    }
//
//    IOUSBHostInterface *iface = OSDynamicCast(IOUSBHostInterface, provider);
//    if (!iface) {
//        LOG("provider is not IOUSBHostInterface?!");
//        RegisterService();
//        return kIOReturnSuccess;
//    }
//    LOG("Super Start OK");
//
//    // ── v13 diagnostics: what does interface 0 actually look like? ────────
//    const IOUSBConfigurationDescriptor *cfg = iface->CopyConfigurationDescriptor();
//    const IOUSBInterfaceDescriptor *ifd =
//        cfg ? iface->GetInterfaceDescriptor(cfg) : nullptr;
//    if (ifd) {
//        LOG("ifaceDesc: num=%u class=%u subclass=%u protocol=%u endpoints=%u altSetting=%u",
//            ifd->bInterfaceNumber, ifd->bInterfaceClass, ifd->bInterfaceSubClass,
//            ifd->bInterfaceProtocol, ifd->bNumEndpoints, ifd->bAlternateSetting);
//
//        const IOUSBEndpointDescriptor *ep = nullptr;
//        while ((ep = IOUSBGetNextEndpointDescriptor(
//                    cfg, ifd,
//                    reinterpret_cast<const IOUSBDescriptorHeader *>(ep)))) {
//            LOG("endpoint addr=0x%02x attr=0x%02x maxPacket=%u interval=%u",
//                ep->bEndpointAddress, ep->bmAttributes,
//                (uint16_t)(ep->wMaxPacketSize), ep->bInterval);
//        }
//
//        // Boot-subclass interfaces default to boot protocol (mouse-style
//        // reports) until the host selects report protocol. If that's our
//        // situation, fix it.
//        if (ifd->bInterfaceSubClass == 1) {
//            kern_return_t pr = setProtocol(1 /* report protocol */);
//            LOG("boot subclass detected — SET_PROTOCOL(report) -> 0x%08X", pr);
//        }
//    } else {
//        LOG("could not read interface descriptor");
//    }
//    if (cfg) IOUSBHostFreeDescriptor(cfg);
//
//    // ── v17: COMPLETE byte-exact replay of Windows capture pkts 78-113 ────
//    // Hypothesis: the firmware's unlock gate requires the full Windows
//    // interrogation IN ORDER — notably reading the report descriptors of
//    // ALL THREE interfaces before the mode write. On Windows the order is:
//    //   3×(GET_STRING idx2 len4, len24) → SET_IDLE(0) → READ RD0(768) →
//    //   SET_IDLE(1) → READ RD1(102) → SET_IDLE(2) → READ RD2(144) →
//    //   GET_STRING idx2 len514 → GET_REPORT 0x0A(2) → SET_REPORT 0x21
//    // Our previous builds fired the unlock before Apple's drivers had read
//    // RD1/RD2 — possibly why the (accepted) mode write never engaged.
//
//    // 3× double string fetch, Windows-style (wValue 0x0302, lang 0x0409)
//    for (int i = 0; i < 3; i++) {
//        ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 4,   "GET_STR2 len4");
//        ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 24,  "GET_STR2 len24");
//    }
//
//    // idle + report-descriptor read, per interface, in capture order
//    static const uint16_t rdLen[3] = { 768, 102, 144 };
//    for (uint16_t ifnum = 0; ifnum <= 2; ifnum++) {
//        uint16_t xfer = 0;
//        kern_return_t hr = iface->DeviceRequest(0x21, 0x0A, 0x0000, ifnum, 0,
//                                                (IOMemoryDescriptor *)nullptr,
//                                                &xfer, 1000);
//        LOG("SET_IDLE iface %u -> 0x%08X", ifnum, hr);
//        char tag[16] = { 'R', 'D', (char)('0' + ifnum), 0 };
//        ctrlIn(iface, 0x81, 0x06, 0x2200, ifnum, rdLen[ifnum], tag);
//    }
//
//    // trailing oversized string fetch (capture pkt 108, wLength 514)
//    ctrlIn(iface, 0x80, 0x06, 0x0302, 0x0409, 514, "GET_STR2 len514");
//
//    // GET_REPORT Feature 0x0A (capture pkt 110)
//    ctrlIn(iface, 0xA1, kHIDRequestGetReport,
//           kHIDReportTypeFeatureWValue | kReportIDMaxContacts,
//           kInterfaceNumber, 2, "GET_REPORT 0x0A");
//
//    // SET_REPORT Feature 0x21 = 21 02 00 (capture pkt 112)
//    const uint8_t modeFramed[] = { 0x21, 0x02, 0x00 };
//    sendFeatureUSB(iface, kReportIDInputMode, modeFramed, sizeof(modeFramed));
//
//    LOG("Mode switch done — watching for input reports");
//    RegisterService();
//    return kIOReturnSuccess;
//}

// ── Stop ──────────────────────────────────────────────────────────────────────
kern_return_t XeneonTouchDriver::Stop_Impl(IOService *provider)
{
    LOG("Stop (saw %u input reports this session)", gReportCount);
    gReportCount = 0;
    return Stop(provider, SUPERDISPATCH);
}

// ── initInputReport — log whether the interrupt-IN read was set up ───────────
kern_return_t XeneonTouchDriver::initInputReport()
{
    kern_return_t ret = IOUserUSBHostHIDDevice::initInputReport();
    LOG("initInputReport -> 0x%08X", ret);
    return ret;
}

// ── handleReport — diagnostic hex dump, then forward ─────────────────────────
kern_return_t XeneonTouchDriver::handleReport(uint64_t            timestamp,
                                              IOMemoryDescriptor  *report,
                                              uint32_t            reportLength,
                                              IOHIDReportType     reportType,
                                              IOOptionBits        options)
{
    uint32_t n = ++gReportCount;
    bool verbose = (n <= kVerboseReports) || (n % kLogEvery == 0);

    if (verbose && report) {
        IOMemoryMap *map = nullptr;
        if (report->CreateMapping(0, 0, 0, 0, 0, &map) == kIOReturnSuccess && map) {
            const uint8_t *p = reinterpret_cast<const uint8_t *>(map->GetAddress());
            uint32_t len = reportLength < 24 ? reportLength : 24;
            if (p) {
                // Manual hex format — os_log doesn't take dynamic buffers.
                char hex[3 * 24 + 1] = {0};
                for (uint32_t i = 0; i < len; i++) {
                    static const char d[] = "0123456789abcdef";
                    hex[i * 3]     = d[p[i] >> 4];
                    hex[i * 3 + 1] = d[p[i] & 0xF];
                    hex[i * 3 + 2] = ' ';
                }
                LOG("report #%u type=%u len=%u id=0x%02X data: %{public}s",
                    n, (unsigned)reportType, reportLength, p[0], hex);
            }
            map->release();
        } else {
            LOG("report #%u type=%u len=%u (map failed)",
                n, (unsigned)reportType, reportLength);
        }
    }

    // Forward to base class — this is what feeds IOHIDInterface and the
    // system event driver. Do not swallow reports.
    return IOUserUSBHostHIDDevice::handleReport(timestamp, report, reportLength,
                                                reportType, options);
}
