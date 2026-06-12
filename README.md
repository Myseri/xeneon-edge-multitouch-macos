# xeneon-edge-multitouch-macos

macOS touch support for the **Corsair Xeneon Edge** (14.5" 32:9 USB-C touchscreen).

Working single-touch with correct display mapping today, plus the most complete
public investigation into why **multitouch does not work on macOS** with this
device — including a working DriverKit driver, a Windows USB protocol capture
of the multitouch unlock sequence, and wire-level proof that the firmware
refuses to honor it on macOS hosts.

**TL;DR: this is a firmware decision, not a missing driver.** See
[docs/DIAGNOSTIC_LOG.md](docs/DIAGNOSTIC_LOG.md) for the full evidence.

---

## The Problem

The Xeneon Edge exposes a WingCoolTouch USB controller (`VID 0x27C0 PID 0x0859`)
with three interfaces:

| Interface | Function | macOS behaviour |
|-----------|----------|-----------------|
| 0 — HID digitizer (page 0x0D) | 10-finger multitouch, absolute coords, report 0x0D | **Completely silent** — never sends a single report |
| 1 — vendor channel (page 0xFF0A) | 64-byte private protocol (reports 0x50/0x51) | Unused |
| 2 — HID mouse (page 0x01) | Single touch as relative pointer, report 0x07 | Works, but clicks land on the active display |

On Windows, the OS sends a standard HID feature report
(`SET_REPORT Feature 0x21 = Input Mode 2`) and interface 0 starts streaming
10-finger multitouch immediately. We captured that exact exchange
([docs/xeneon_win11_unlock.pcapng](docs/xeneon_win11_unlock.pcapng)) and
replayed it **byte-for-byte** from a working macOS DriverKit driver. Every
control transfer succeeds with responses identical to Windows'. The firmware
accepts the mode switch — and never streams. Three independent macOS stacks
(this driver, Apple's HID stack, and the commercial UPDD driver with exclusive
device access) fail identically. The firmware appears to fingerprint the host
OS during enumeration, below anything host software can influence.

---

## What's In This Repo

### `userspace/` — single-touch daemon (works today)

Python daemon that reads the touch data macOS *does* get and injects clicks at
the correct absolute position on the Edge's display. No kernel code, no
signing, installs in seconds. → [userspace/README.md](userspace/README.md)

### `driverkit/` — DriverKit multitouch driver (complete; blocked by firmware)

A fully working dext: signs, loads, exclusively owns the digitizer interface,
arms the interrupt pipe, and replays the captured Windows unlock sequence at
every device attach. If the firmware ever honors the mode switch on macOS (or
a firmware update changes behavior), this driver is ready to receive and
forward 10-finger reports. Requires SIP disabled + sysext developer mode (it's
development-signed). → [driverkit/README.md](driverkit/README.md)

Hard-won DriverKit lessons documented in the diagnostic log, including: dev
provisioning profiles exact-match the `transport.usb` wildcard entitlement;
HID dexts need `IOClass = AppleUserHIDDevice` with
`CFBundleIdentifierKernel = com.apple.iokit.IOHIDFamily`; and
`amfi_get_out_of_my_way` *breaks* dext loading rather than helping it.

### `linux/` — unlock replay test for Linux hosts

pyusb script that replays the Windows unlock from a Linux machine and listens
for multitouch reports. Determines whether the firmware gate is
"Windows-only" or "anything-but-macOS" — which decides what a USB middlebox
would need to emulate. → [linux/replay_unlock.py](linux/replay_unlock.py)

### `docs/` — the evidence

- [DIAGNOSTIC_LOG.md](docs/DIAGNOSTIC_LOG.md) — full investigation record:
  every hypothesis tested and eliminated, with hardware-verified results
- [xeneon_win11_unlock.pcapng](docs/xeneon_win11_unlock.pcapng) — USBPcap
  capture of Windows 11 unlocking multitouch (the money packets: 110–113)
- ioreg dumps, HID report descriptor decode, driver session logs

---

## Status

| Feature | Status |
|---------|--------|
| Correct-display click injection (userspace) | ✅ Working |
| Single-touch absolute coordinates (userspace) | ✅ Working |
| DriverKit driver: build, sign, load, own interface 0 | ✅ Working |
| Windows unlock sequence captured & decoded | ✅ Done |
| Byte-exact unlock replay from macOS | ✅ Sent & ACK'd — firmware ignores it |
| 10-finger multitouch on macOS | ❌ Blocked by firmware host-OS gating |
| Linux host verdict | 🔬 Test script ready, result pending |
| USB middlebox (Pi 4/5 proxy) | 📋 Designed, contingent on Linux verdict |

## Known Mac Ecosystem

Both other public macOS projects for this device are single-touch userspace
daemons that (correctly) concluded the hardware "only exposes single touch":
[ajvwhite/MacXeneonEdgeTouchDriver](https://github.com/ajvwhite/MacXeneonEdgeTouchDriver),
[ymlaine/TouchscreenDriver](https://github.com/ymlaine/TouchscreenDriver).
This repo documents *why*: the multitouch hardware is fully present and
advertised in the HID descriptor macOS receives — the firmware just refuses to
stream it to a macOS host. UPDD (commercial) is blocked identically.

## Contributing / How You Can Help

- **Run the Linux test** (`linux/replay_unlock.py`) and report the verdict
- **Corsair owners**: ask Corsair support about multitouch on non-Windows
  hosts — the fix is almost certainly a firmware flag
- Captures of the Edge under other OSes (ChromeOS, Android hosts) welcome
- Middlebox prototyping (Pi 4/5 gadget mode) — see the diagnostic log

## License

MIT — see [userspace/LICENSE](userspace/LICENSE).
