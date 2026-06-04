#!/usr/bin/env python3
"""
Mode-switch probe for the WCH touch controller.

The HID descriptor on Interface 0 exposes two feature reports that
control multitouch mode (standard HID digitizer protocol):

  Report 0x21 — Input Mode (Usage 0x0052) + Device ID (Usage 0x0053)
                Setting Input Mode = 2 activates multitouch reporting.
  Report 0x0A — Max Contacts (Usage 0x0055)

This script tries every available path to send those reports, then
listens for digitizer events via IOHIDEventSystemClient to see if
multitouch data starts flowing.

Approach order:
  1. hidapi send_feature_report on Interface 0 (control transfer,
     may succeed even when interrupt endpoint is exclusively owned)
  2. IOHIDManager open (no seize) + IOHIDDeviceSetReport on Interface 0
  3. Vendor output Report 0x51 on Interface 1 (unknown protocol — we
     try wrapping the standard HID Set_Report payload)
  4. Listen for IOHIDEventSystemClient digitizer events for 20 s
"""

import sys, os, time, ctypes, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

from xeneon_touch.config import VID, PID

# ── IOKit / CF setup (reused for both IOHIDManager and EventSystem) ─────────
_IOKit = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')
_CF    = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64)

# CF
_CF.CFStringCreateWithCString.restype  = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
_CF.CFNumberCreate.restype             = _vp
_CF.CFNumberCreate.argtypes            = [_vp, _lng, _vp]
_CF.CFDictionaryCreateMutable.restype  = _vp
_CF.CFDictionaryCreateMutable.argtypes = [_vp, _lng, _vp, _vp]
_CF.CFDictionarySetValue.restype       = None
_CF.CFDictionarySetValue.argtypes      = [_vp, _vp, _vp]
_CF.CFRunLoopGetCurrent.restype        = _vp
_CF.CFRunLoopGetCurrent.argtypes       = []
_CF.CFRunLoopRun.restype               = None
_CF.CFRunLoopRun.argtypes              = []
_CF.CFRunLoopStop.restype              = None
_CF.CFRunLoopStop.argtypes             = [_vp]
_CF.CFArrayGetCount.restype            = _lng
_CF.CFArrayGetCount.argtypes           = [_vp]
_CF.CFArrayGetValueAtIndex.restype     = _vp
_CF.CFArrayGetValueAtIndex.argtypes    = [_vp, _lng]

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type   = 3

def _cfstr(s):
    return _CF.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)

def _cfnum(n):
    v = ctypes.c_int32(n)
    return _CF.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(v))

_mode = _cfstr("kCFRunLoopDefaultMode")

# IOHIDManager
_IOKit.IOHIDManagerCreate.restype                       = _vp
_IOKit.IOHIDManagerCreate.argtypes                      = [_vp, _u32]
_IOKit.IOHIDManagerOpen.restype                         = _i32
_IOKit.IOHIDManagerOpen.argtypes                        = [_vp, _u32]
_IOKit.IOHIDManagerSetDeviceMatching.restype            = None
_IOKit.IOHIDManagerSetDeviceMatching.argtypes           = [_vp, _vp]
_IOKit.IOHIDManagerScheduleWithRunLoop.restype          = None
_IOKit.IOHIDManagerScheduleWithRunLoop.argtypes         = [_vp, _vp, _vp]
_IOKit.IOHIDManagerCopyDevices.restype                  = _vp
_IOKit.IOHIDManagerCopyDevices.argtypes                 = [_vp]

# IOHIDDevice
_IOKit.IOHIDDeviceSetReport.restype  = _i32
_IOKit.IOHIDDeviceSetReport.argtypes = [_vp, _i32, _lng, ctypes.c_void_p, _lng]

# IOHIDEventSystemClient
_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes  = [_vp, _vp, _vp]

# IOHIDEvent
_IOKit.IOHIDEventGetType.restype          = _i32
_IOKit.IOHIDEventGetType.argtypes         = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype    = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes   = [_vp, _i32]
_IOKit.IOHIDEventGetIntegerValue.restype  = _i64
_IOKit.IOHIDEventGetIntegerValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetChildren.restype      = _vp
_IOKit.IOHIDEventGetChildren.argtypes     = [_vp]

kIOHIDOptionsTypeNone              = 0x00
kIOHIDOptionsTypeSeizeDevice       = 0x01
kIOHIDEventSystemClientTypePassive = 4
kIOHIDReportTypeFeature            = 2
kIOHIDEventTypeDigitizer           = 11

def _f(idx): return (kIOHIDEventTypeDigitizer << 16) | idx
kIOHIDEventFieldDigitizerX          = _f(0)
kIOHIDEventFieldDigitizerY          = _f(1)
kIOHIDEventFieldDigitizerTipSwitch  = _f(11)
kIOHIDEventFieldDigitizerCollection = _f(15)
kIOHIDEventFieldDigitizerIdentity   = _f(17)

# ── Helper: enumerate device paths ──────────────────────────────────────────
def _get_paths():
    paths = {}
    for d in hid.enumerate(VID, PID):
        iface = d.get('interface_number', -1)
        paths[iface] = d['path']
    return paths  # {0: path, 1: path, 2: path}

# ── PHASE 1: try hidapi send_feature_report ──────────────────────────────────
def try_hidapi_feature(paths):
    print("\n── Phase 1: hidapi send_feature_report ─────────────────────────────")

    iface0 = paths.get(0)
    if not iface0:
        print("  Interface 0 path not found — skipping")
        return False

    # Report 0x21: Input Mode=2 (multitouch), Device ID=0
    payload_21 = bytes([0x21, 0x02, 0x00])
    # Report 0x0A: Max Contacts = 10
    payload_0A = bytes([0x0A, 0x0A])

    dev = hid.device()
    try:
        dev.open_path(iface0)
        print(f"  Interface 0 opened via hidapi (path={iface0})")
    except Exception as e:
        print(f"  Interface 0 open failed: {e}")
        print("  (Expected — exclusive access. Trying anyway via control transfer…)")
        # Some hidapi builds let you send feature reports without a full open
        # by using the raw path. Worth trying.
        dev = None

    success = False
    if dev:
        for name, payload in [("0x21 Input Mode", payload_21),
                               ("0x0A Max Contacts", payload_0A)]:
            try:
                r = dev.send_feature_report(list(payload))
                print(f"  send_feature_report({name}): returned {r}  ✓")
                success = True
            except Exception as e:
                print(f"  send_feature_report({name}): {e}")
        dev.close()

    return success

# ── PHASE 2: IOHIDManager + IOHIDDeviceSetReport ─────────────────────────────
def try_iokit_set_report():
    print("\n── Phase 2: IOHIDManager IOHIDDeviceSetReport ──────────────────────")

    mgr = _IOKit.IOHIDManagerCreate(None, kIOHIDOptionsTypeNone)
    if not mgr:
        print("  IOHIDManagerCreate failed")
        return False

    # Match by VID+PID+usage_page (digitizer = 13)
    d = _CF.CFDictionaryCreateMutable(None, 0, None, None)
    _CF.CFDictionarySetValue(d, _cfstr("VendorID"),         _cfnum(VID))
    _CF.CFDictionarySetValue(d, _cfstr("ProductID"),        _cfnum(PID))
    _CF.CFDictionarySetValue(d, _cfstr("PrimaryUsagePage"), _cfnum(0x000D))
    _IOKit.IOHIDManagerSetDeviceMatching(mgr, d)

    # Need a run loop to let the manager enumerate
    rl = _CF.CFRunLoopGetCurrent()
    _IOKit.IOHIDManagerScheduleWithRunLoop(mgr, rl, _mode)

    ret = _IOKit.IOHIDManagerOpen(mgr, kIOHIDOptionsTypeNone)
    print(f"  IOHIDManagerOpen (no seize): 0x{ret & 0xFFFFFFFF:08X}",
          "✓" if ret == 0 else "✗")

    if ret != 0:
        return False

    # Give the manager a moment to enumerate devices
    time.sleep(0.3)

    devices = _IOKit.IOHIDManagerCopyDevices(mgr)
    if not devices:
        print("  No devices found in manager")
        return False

    n = _CF.CFArrayGetCount(devices)
    print(f"  Found {n} device(s) in manager")

    success = False
    for i in range(n):
        dev_ref = _CF.CFArrayGetValueAtIndex(devices, i)
        if not dev_ref:
            continue

        # Report 0x21: [report_id, input_mode=2, device_id=0]
        for report_id, payload_bytes in [
            (0x21, bytes([0x02, 0x00])),   # Input Mode = 2, Device ID = 0
            (0x0A, bytes([0x0A])),          # Max Contacts = 10
        ]:
            buf = (ctypes.c_uint8 * len(payload_bytes))(*payload_bytes)
            r = _IOKit.IOHIDDeviceSetReport(
                dev_ref,
                kIOHIDReportTypeFeature,
                report_id,
                buf,
                len(payload_bytes),
            )
            status = "✓" if r == 0 else f"✗ 0x{r & 0xFFFFFFFF:08X}"
            print(f"  IOHIDDeviceSetReport(0x{report_id:02X}): {status}")
            if r == 0:
                success = True

    return success

# ── PHASE 3: vendor output Report 0x51 on Interface 1 ────────────────────────
def try_vendor_output(paths):
    print("\n── Phase 3: vendor Output Report 0x51 (Interface 1) ───────────────")

    iface1 = paths.get(1)
    if not iface1:
        print("  Interface 1 path not found")
        return False

    dev = hid.device()
    try:
        dev.open_path(iface1)
        print(f"  Interface 1 opened (path={iface1})")
    except Exception as e:
        print(f"  Interface 1 open failed: {e}")
        return False

    # Attempt 1: wrap the standard HID Set_Report payload for report 0x21
    # (Input Mode = 2, Device ID = 0) as a 63-byte vendor packet
    # We don't know the protocol, so try the obvious layout first.
    success = False

    payloads = [
        # (description, bytes)
        ("raw Set_Report 0x21 [2,0] at offset 0",
         bytes([0x51, 0x21, 0x02, 0x00] + [0x00]*59)),
        ("raw Set_Report 0x21 [2,0] at offset 1",
         bytes([0x51, 0x00, 0x21, 0x02, 0x00] + [0x00]*58)),
        # Try the UPDD-style command (speculative based on common WCH firmware)
        ("speculative UPDD init [0x01, 0x00] (mode enable)",
         bytes([0x51, 0x01, 0x00] + [0x00]*60)),
    ]

    for desc, payload in payloads:
        try:
            r = dev.write(list(payload))
            print(f"  write({desc}): returned {r}")
            time.sleep(0.05)
            # Quick read to see if device responds
            resp = dev.read(64, timeout_ms=100)
            if resp:
                print(f"    → response: {bytes(resp).hex(' ')}")
            success = (r > 0)
        except Exception as e:
            print(f"  write({desc}): {e}")

    dev.close()
    return success

# ── PHASE 4: listen for digitizer events via IOHIDEventSystemClient ──────────
_event_count    = [0]
_multitouch_seen = [False]
_rl             = [None]

@ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)
def _event_cb(target, refcon, service, event):
    if not event:
        return
    etype = _IOKit.IOHIDEventGetType(event)
    if etype != kIOHIDEventTypeDigitizer:
        return

    _event_count[0] += 1
    is_coll = bool(_IOKit.IOHIDEventGetIntegerValue(
        event, kIOHIDEventFieldDigitizerCollection))

    if is_coll:
        children = _IOKit.IOHIDEventGetChildren(event)
        n = _CF.CFArrayGetCount(children) if children else 0
        _multitouch_seen[0] = _multitouch_seen[0] or (n > 1)
        contacts = []
        for i in range(n):
            child = _CF.CFArrayGetValueAtIndex(children, i)
            if child and _IOKit.IOHIDEventGetType(child) == kIOHIDEventTypeDigitizer:
                x   = _IOKit.IOHIDEventGetFloatValue(child, kIOHIDEventFieldDigitizerX)
                y   = _IOKit.IOHIDEventGetFloatValue(child, kIOHIDEventFieldDigitizerY)
                tip = bool(_IOKit.IOHIDEventGetIntegerValue(
                    child, kIOHIDEventFieldDigitizerTipSwitch))
                cid = int(_IOKit.IOHIDEventGetIntegerValue(
                    child, kIOHIDEventFieldDigitizerIdentity))
                contacts.append(f"finger{cid}({'↓' if tip else '↑'}) "
                                 f"x={x:.3f} y={y:.3f}")
        print(f"  [DIGITIZER COLLECTION] {n} contacts: {', '.join(contacts)}",
              flush=True)
    else:
        x   = _IOKit.IOHIDEventGetFloatValue(event, kIOHIDEventFieldDigitizerX)
        y   = _IOKit.IOHIDEventGetFloatValue(event, kIOHIDEventFieldDigitizerY)
        tip = bool(_IOKit.IOHIDEventGetIntegerValue(
            event, kIOHIDEventFieldDigitizerTipSwitch))
        print(f"  [DIGITIZER] x={x:.3f} y={y:.3f} tip={'↓' if tip else '↑'}",
              flush=True)


def listen_for_events(duration=20):
    print(f"\n── Phase 4: IOHIDEventSystemClient — listening {duration}s ─────────")
    print("  Touch the Xeneon Edge (try two fingers!) …\n")

    client = _IOKit.IOHIDEventSystemClientCreateWithType(
        None, kIOHIDEventSystemClientTypePassive, None)
    if not client:
        print("  IOHIDEventSystemClientCreateWithType returned NULL")
        print("  → Grant Input Monitoring to Terminal in System Settings → Privacy")
        return

    _IOKit.IOHIDEventSystemClientRegisterEventCallback(client, _event_cb, None, None)
    _rl[0] = _CF.CFRunLoopGetCurrent()
    _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(client, _rl[0], _mode)

    def _stop():
        time.sleep(duration)
        _CF.CFRunLoopStop(_rl[0])
    threading.Thread(target=_stop, daemon=True).start()

    _CF.CFRunLoopRun()

    print(f"\n  Total digitizer events: {_event_count[0]}")
    if _event_count[0] == 0:
        print("  → 0 events. Possible causes:")
        print("    1. Input Monitoring not granted to Terminal")
        print("    2. Device not yet in multitouch mode (mode switch failed)")
        print("    3. AppleUserHIDDevice not generating events for this device")
    elif _multitouch_seen[0]:
        print("  ★ MULTITOUCH CONFIRMED — multiple contacts in a single collection!")
    else:
        print("  Single-touch events seen. Mode switch may still be needed.")


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    print("═" * 60)
    print("  Xeneon Edge — multitouch mode-switch probe")
    print("═" * 60)

    paths = _get_paths()
    print(f"\nDevice paths: { {k: v for k,v in paths.items()} }")

    if not paths:
        sys.exit("WCH device not found — is the Xeneon Edge connected?")

    r1 = try_hidapi_feature(paths)
    r2 = try_iokit_set_report()
    r3 = try_vendor_output(paths)

    print(f"\n── Mode switch summary ─────────────────────────────────────────────")
    print(f"  hidapi feature report:        {'✓ sent' if r1 else '✗ failed'}")
    print(f"  IOHIDDeviceSetReport:         {'✓ sent' if r2 else '✗ failed'}")
    print(f"  vendor output (speculative):  {'✓ sent' if r3 else '✗ failed'}")

    listen_for_events(duration=25)

    print("\nDone.")


if __name__ == "__main__":
    main()
