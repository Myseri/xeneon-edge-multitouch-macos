# xeneon-edge-multitouch-macos

macOS touch driver for the **Corsair Xeneon Edge** (21:9 USB-C touchscreen monitor).

This project brings proper touch support to the Xeneon Edge on macOS — fixing wrong-monitor clicks and working toward full 5-point multitouch, with no kernel extensions, no UPDD, and no phone-home.

---

## The Problem

The Xeneon Edge exposes a WingCoolTouch USB HID controller (`VID 0x27C0 PID 0x0859`) with two interfaces:

| Interface | Usage | macOS behaviour |
|-----------|-------|----------------|
| Digitizer (HID page 0x0D) | 10-finger multitouch, absolute coordinates | Claimed by `AppleUserHIDDevice` — no usable output |
| Mouse (HID page 0x01) | Single touch, relative pointer | Works, but clicks land on whichever display is currently active — not the Xeneon Edge |

The result: touch "works" but clicks land on the wrong monitor.

---

## This Project

Two components, tackling the problem at different levels:

### `userspace/` — Python single-touch daemon (works today)

Reads the digitizer's absolute coordinates via HID and injects corrected click events at the right position on the Xeneon Edge. No signing required, installs in seconds.

**What it does:**
- Fixes wrong-monitor clicks
- Maps touch coordinates correctly to the Xeneon Edge display
- Runs as a background LaunchAgent

**What it doesn't do (yet):**
- Multitouch gestures (scroll, pinch, etc.)

→ [userspace/README.md](userspace/README.md)

### `driverkit/` — DriverKit extension (multitouch, pending signing)

A proper macOS DriverKit driver that claims Interface 0 before `AppleUserHIDDevice`, sends the HID Input Mode = 2 feature report to activate multitouch, and dispatches 5-point digitizer events to the OS.

**Current state:** The driver correctly matches the hardware (`IODEXTMatchCount=1`, outbids Apple's driver at `IOProbeScore 200000 vs 50001`). The final step — launching the user server process — requires a real Apple TeamIdentifier, which requires the Apple Developer Program.

→ [driverkit/README.md](driverkit/README.md)

---

## Hardware

```
Monitor:    Corsair Xeneon Edge 14.5" (CC-9011306-WW)
Touch IC:   WingCoolTouch / WCH (Nanjing Qinheng)
VID/PID:    0x27C0 / 0x0859
Interface:  USB-C (touch data) + HDMI or USB-C (display)

HID descriptor (Interface 0, confirmed):
  Report 0x0D — 10-finger multitouch
    X: 0–16383  (216.9 mm physical)
    Y: 0–9599   (90.6 mm physical)
  Report 0x21 — Input Mode feature (0=mouse, 1=single-touch, 2=multitouch)
  Report 0x0A — Max Contacts feature
```

**Key finding:** The firmware serves a different HID descriptor on macOS vs Windows. On Windows, 5-point multitouch works natively with no drivers. On macOS, the firmware defaults to single-touch mode. The DriverKit driver sends Report 0x21 (Input Mode=2) at init to unlock multitouch.

---

## Status

| Feature | Status |
|---------|--------|
| Correct-monitor click injection | ✅ Working (userspace) |
| Single-touch with correct coordinates | ✅ Working (userspace) |
| DriverKit driver matching hardware | ✅ Working (needs signing) |
| Multitouch mode switch (Report 0x21) | ✅ Implemented (needs signing) |
| 5-point multitouch event dispatch | 🔧 Implemented (needs signing + testing) |
| Scroll synthesis | 📋 Planned |

---

## Contributing

The userspace driver is ready to use and improve today. The DriverKit driver needs someone with an Apple Developer Program membership and the `com.apple.developer.driverkit.transport.usb` entitlement to sign, test, and complete the multitouch dispatch.

PRs welcome. See `userspace/tools/diagnose.py` to dump raw HID reports.

---

## License

MIT — see [userspace/LICENSE](userspace/LICENSE)

The DriverKit extension source is also MIT. If you ship a commercial product based on this work, a credit would be appreciated but is not required.
