# Xeneon Edge Touch — Userspace Driver

Single-touch daemon for the Corsair Xeneon Edge on macOS. Fixes wrong-monitor clicks with no kernel extension, no signing, no UPDD.

## Requirements

- macOS 12 (Monterey) or later
- Python 3.9+
- `pip install hidapi pyobjc-framework-Quartz pyobjc-framework-ApplicationServices --break-system-packages`

## Install

```bash
git clone https://github.com/YOUR_USERNAME/xeneon-edge-multitouch-macos
cd xeneon-edge-multitouch-macos/userspace
./install.sh
```

The installer builds the daemon, installs it to `~/Library/Application Support/`, and registers a LaunchAgent that starts it at login.

## Permissions

On first run macOS will prompt for:

- **Accessibility** — required to inject corrected click events
- **Input Monitoring** — required to read HID reports

Grant both in System Settings → Privacy & Security.

## Usage

```bash
# Run interactively
python3 -m xeneon_touch

# Check status
pgrep -f xeneon_touch && echo "running" || echo "stopped"

# View logs
tail -f /tmp/xeneon_touch.log

# Uninstall
./uninstall.sh
```

## Diagnostics

```bash
# Enumerate device and dump raw HID reports
python3 tools/diagnose.py

# Confirm HID report descriptor (X/Y ranges, report IDs)
python3 tools/get_descriptor.py

# Simultaneous HID + CGEvent stream — verify coordinate mapping
python3 tools/test_calibrate.py

# Raw Interface 2 (mouse) dump
python3 tools/test_mouse_iface.py
```

## How It Works

The touch controller sends absolute (x, y) on the HID digitizer interface (Interface 0).
macOS's `AppleUserHIDDevice` claims that interface but only generates generic cursor
movement — losing the absolute position and the display association.

This daemon reads Interface 2 (the mouse interface, which is openable with shared access),
extracts the absolute coordinates from the HID report, maps them to the Xeneon Edge's
display bounds via `NSScreen`, and injects a corrected `CGEvent` at the right position.

## Known Limitations

- Single-touch only — multitouch requires the DriverKit driver (see `../driverkit/`)
- A small `deltaX=1, deltaY=255` artifact appears in CGEvent on each touch (HID button byte
  being misread as delta by macOS's mouse driver). Cosmetic only.

## Hardware Reference

```
VID:          0x27C0  (WingCoolTouch / wch.cn)
PID:          0x0859
Interface 2:  Mouse, Report ID 0x07, 7 bytes
  [0] 0x07         — Report ID
  [1] 0x01/0x00    — touch down / lifted (bit 0)
  [2-3] X          — 16-bit LE, 0–16383
  [4-5] Y          — 16-bit LE, 0–9599
  [6] 0x00         — wheel (unused)
```
