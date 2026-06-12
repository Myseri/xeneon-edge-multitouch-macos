# Xeneon Edge DriverKit — Diagnostic Log (2026-06-11)

Status at end of session: **driver fully operational; firmware refuses to
enter multitouch mode on macOS hosts.** Every host-side software avenue has
been tested and eliminated.

## Hardware

- Corsair Xeneon Edge 14.5" (CC-9011306-WW), WingCoolTouch / WCH controller
- VID `0x27C0` (10176), PID `0x0859` (2137), USB 2.0 full-speed
- Interface 0: HID digitizer (EP 0x81 int-IN, 64B, 1ms) — 10-finger report 0x0D
- Interface 1: vendor channel (usagePage 0xFF0A) — 63B reports, IN 0x50 / OUT 0x51
- Interface 2: HID mouse — report 0x07, 7B (this is where touches actually go)

## Driver state (v18, working)

- DriverKit dext, `IOUserUSBHostHIDDevice` subclass, matches IOUSBHostInterface
- Signing: Apple Development cert; **entitlement must claim
  `transport.usb idVendor = "*"` (string) in development** — exact-match
  against profile, NOT pattern-match (Apple DTS, forums thread 798049)
- Personality: `IOClass = AppleUserHIDDevice`,
  `CFBundleIdentifierKernel = com.apple.iokit.IOHIDFamily` (kernel half of
  HID stack; generic IOUserService makes super Start fail 0xE00002C7)
- `kUSBHIDDeviceIdlePolicy = 0` (no effect on the bug, kept anyway)
- Boot env: SIP off, sysext developer mode on, **NO amfi_get_out_of_my_way**
  (that boot-arg breaks provisioning-profile validation → taskgated SIGKILL)

## Bugs fixed this session (chronological)

1. `amfi_get_out_of_my_way=1` → Code Signature Invalid kill loop. Removed.
2. Entitlement claimed concrete idVendor 10176; dev profile grants `"*"`,
   matched by exact value → "Unsatisfied entitlements". Claim `"*"`.
3. Personality `IOClass IOUserService` → super Start kIOReturnUnsupported.
   Use `AppleUserHIDDevice` (copied from Apple's AppleUserHIDDrivers.dext).
4. sysextd serves stale staged builds when CFBundleVersion doesn't change;
   an upgrade can wedge in `beingReplaced` (fix: uninstall + reboot).
5. HID-layer `setReport` from a dext → kIOReturnBadArgument. Use raw
   `DeviceRequest` SET_REPORT control transfers instead.

## The remaining problem

Touches stream as mouse (report 0x07, interface 2) regardless of any mode
switch. Interface 0 never sends a single input report on macOS.

### What Windows does (USBPcap capture, docs/"xeneon logs.pcapng", dev 27)

Plain enumeration, then: 3×(GET_STRING idx2 len4+len24) → SET_IDLE(0) →
read RD0 → SET_IDLE(1) → read RD1 → SET_IDLE(2) → read RD2 →
GET_STRING idx2 len514 → GET_REPORT feat 0x0A (returns `0a 0f`) →
SET_REPORT feat 0x21 data `21 02 00` → 0x0D multitouch reports flow ~3ms
later. 54-byte reports: ID + 10×(flags, X16, Y16) + scantime16 + count8.

### Eliminated hypotheses (each tested on hardware)

- UPDD retest (2026-06-12, v07.00.5): claimed the ENTIRE composite device
  exclusively from userspace (UsbExclusiveOwner = updd daemon) — still no
  multitouch. Third independent stack (our dext, Apple's, UPDD) to fail
  identically on macOS. Retested after full reboot with SIP RE-ENABLED
  (UPDD's supported config) — still single-touch only.

- SET_REPORT framing (with/without ID byte) — both accepted, no effect
- Writing Max Contacts 0x0A — Windows never writes it; removed
- MS OS descriptors — device STALLs string 0xEE; no MSFT100 support
- HID-layer vs USB-layer SET_REPORT — both paths, no effect
- SET_IDLE on iface 0 only vs all 3 — no effect
- Reading report descriptors of all 3 interfaces in Windows order (v17 =
  complete byte-exact replay of capture pkts 78-113; every response byte
  identical to Windows', incl. GET 0x0A = `0a 0f`) — no effect
- Boot-protocol (iface is subclass 0, not boot) — n/a
- Interrupt pipe not armed (initInputReport = 0, inputReportSize 54) — armed
- USB topology / alt-mode: HDMI video + USB-A-adapter + dock (Dell-identical
  upstream) — no effect
- Pipe idle policy 0 — no effect
- GET_REPORT read-back as verification — firmware echoes the SETUP packet
  back as data; useless signal

### Surviving hypothesis

Firmware fingerprints the **host OS during bus enumeration** (descriptor
request pattern of the USB stack itself, pre-driver) and only honors the
0x21 mode switch when the fingerprint says Windows. Nothing a dext does
post-enumeration can alter what the host stack already did.

## Next experiments

1. **Windows VM with USB passthrough** (VMware Fusion free tier / UTM /
   Parallels) on the Mac. Pass VID 0x27C0 through to Win11 guest.
   - Multitouch works in guest → fingerprint theory DEAD (no physical
     re-enumeration happened); capture inside guest with USBPcap, diff vs
     v17, implement what's missing.
   - Multitouch dead in guest → fingerprint confirmed at bus level.
2. If fingerprint confirmed: investigate vendor channel 0x50/0x51 for a
   persistent (EEPROM) mode flag settable once from Windows/iCUE; check
   iCUE touch settings on the Dell. Hardware USB proxy (Cynthion) is the
   last resort.
3. Fallback that works today: this dext + userspace daemon (corrected
   single-touch click injection on the right display).

## Useful commands

```bash
# driver log
log stream --level debug --predicate 'sender == "com.jonathanmartin.XeneonTouchDriverApp.XeneonTouchDriver.dext"'
# installed version
systemextensionsctl list | grep -i xeneon
# raw HID reports per interface (mouse iface shows touches)
python3 userspace/tools/test_mouse_iface.py
# full uninstall when an upgrade wedges
systemextensionsctl uninstall S27RQRV4GX com.jonathanmartin.XeneonTouchDriverApp.XeneonTouchDriver  # then reboot
```
