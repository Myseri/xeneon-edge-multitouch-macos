# Xeneon Edge Touch — Userspace Driver

Single-touch daemon for the Corsair Xeneon Edge on macOS. Makes taps, clicks,
and drags land at the correct spot **on the Edge** instead of on whatever
display the cursor happened to be on — with no kernel extension, no SIP changes,
and no UPDD.

It installs as a per-user LaunchAgent: starts at login, runs as a quiet
background process (no Dock icon), and recovers on its own when you unplug and
replug the monitor. Multitouch is not possible from userspace (or at all on
macOS today) because the firmware withholds it — see the
[top-level README](../README.md) and [diagnostic log](../docs/DIAGNOSTIC_LOG.md).

## Requirements

- macOS 12 (Monterey) or later
- Python 3.9+ (the python.org framework build or Homebrew python both work)
- [Homebrew](https://brew.sh) — used for the native `libhidapi` library
- The Python packages `hidapi`, `pyobjc-framework-Quartz`,
  `pyobjc-framework-ApplicationServices` (the installer handles these)

> **Architecture note (Apple Silicon):** the native `libhidapi.dylib` must be
> the same architecture as your Python. The installer detects this and uses the
> matching Homebrew (`/opt/homebrew` for arm64 Python, `/usr/local` for x86_64),
> so an Intel/Rosetta brew can't hand an arm64 Python a library it can't load.

## Install

```bash
git clone https://github.com/Myseri/xeneon-edge-multitouch-macos
cd xeneon-edge-multitouch-macos/userspace
./install.sh
```

The installer:

1. Resolves your `python3` to its real, versioned binary (TCC permissions
   attach to the concrete binary, so this survives a `python3` symlink moving).
2. Installs the arch-matched `hidapi` Homebrew formula and the required pip
   packages (removing the conflicting `hid`/pyhidapi package if present).
3. Renders the LaunchAgent into `~/Library/LaunchAgents/`, passing the python
   binary, the working directory, and the `libhidapi` location
   (`DYLD_FALLBACK_LIBRARY_PATH`) — a GUI agent doesn't inherit your shell's
   library path, so this must be explicit.
4. Loads and starts the agent.

## Permissions (one-time)

The daemon needs two macOS permissions, both attached to the **python binary**
the installer prints:

- **Input Monitoring** — to read the touch HID interface. macOS prompts for this
  on first run; click Allow.
- **Accessibility** — to inject corrected click/drag events. The daemon requests
  this on startup, which shows the grant dialog and registers the binary in the
  list (a manual file-picker add of a framework-python binary stays greyed out,
  which is why the daemon asks programmatically).

Grant both in **System Settings → Privacy & Security**, then restart the agent:

```bash
launchctl kickstart -k gui/$(id -u)/com.github.xeneon-touch
```

> If you later upgrade Python to a new version (e.g. 3.14 → 3.15), the pinned
> binary path changes and the grants no longer apply — rerun `./install.sh` and
> re-grant the two permissions to the new binary.

## Usage

```bash
# Status
launchctl print gui/$(id -u)/com.github.xeneon-touch | grep state

# Restart (after granting permissions, or to reload code)
launchctl kickstart -k gui/$(id -u)/com.github.xeneon-touch

# Logs
tail -f /tmp/xeneon-touch.log

# Run in the foreground (for debugging; needs the dylib on the path)
DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix hidapi)/lib" python3 -m xeneon_touch

# Uninstall (removes the LaunchAgent; leaves the TCC grants in place)
./uninstall.sh
```

## How It Works

The touch controller exposes three USB HID interfaces. The multitouch digitizer
(Interface 0) never streams a report on macOS — the firmware gates it on host OS.
Touch data is only available on Interface 2, which presents as a mouse
(Report ID 0x07) carrying **absolute** X/Y. macOS handles that interface as a
relative-ish pointer, which is why clicks land on the wrong display by default.

The daemon:

1. **Identifies the Edge display via CoreGraphics** by hardware identity
   (vendor/model). CoreGraphics reports this live, whereas `NSScreen`'s screen
   list is cached for the life of the process and would report a stale display
   after a hot-plug.
2. **Reads Interface 2 via hidapi** (shared access — no exclusive lock needed),
   parses the absolute coordinates, and normalizes them.
3. **Maps to the Edge's display bounds** and injects a corrected `CGEvent` at the
   right absolute position (`CGWarpMouseCursorPosition` + mouse down/drag/up).
4. **Supervises itself**: waits for the Edge when it's absent, runs a touch
   session while it's present, and tears down + re-establishes on disconnect —
   all in one long-lived process, so the LaunchAgent never has to relaunch it
   (which would blink a Dock icon). It also sets its activation policy to
   "accessory" so there's no Dock icon at all.

## Known Limitations

- **Single-touch only.** Interface 2 reports one point; the 10-finger digitizer
  is firmware-gated on macOS. Two-finger scroll in the injector therefore never
  triggers. (The DriverKit driver in `../driverkit/` is ready to forward
  multitouch *if* a firmware update ever honors it — see the top-level README.)
- **Brief reconnect retry.** On replug the display can reappear before USB
  finishes enumerating, so the first open may grab a half-ready device that
  drops. The daemon detects this and re-establishes within a few seconds — it's
  automatic and logged, but not instantaneous.
- **Hardcoded display identity.** The CG vendor/model (`3672`/`60672`) is taken
  from a real unit. It's stable across all Xeneon Edge panels, and a name-based
  `NSScreen` fallback (cross-checked against the live CG list) covers other
  cases.

## Diagnostics

Handy tools under `tools/` (run with
`DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix hidapi)/lib"` prefixed if hidapi
isn't on the default path):

```bash
python3 tools/diagnose.py            # enumerate device + dump raw HID reports
python3 tools/get_descriptor.py      # HID report descriptor (X/Y ranges, IDs)
python3 tools/test_mouse_iface.py    # raw Interface 2 (mouse) dump
python3 tools/cg_identity.py         # CG vendor/model/bounds of every display
python3 tools/probe_presence.py      # compare hid / NSScreen / CG liveness
python3 tools/observe_events.py      # dump all IOHIDEvents (passive observer)
```

## Hardware Reference

```
VID:          0x27C0  (WingCoolTouch / wch.cn)
PID:          0x0859
Display (CG): vendor 3672, model 60672
Interface 2:  Mouse, Report ID 0x07, 7 bytes
  [0] 0x07         — Report ID
  [1] 0x01/0x00    — touch down / lifted (bit 0)
  [2-3] X          — 16-bit LE, 0–16383
  [4-5] Y          — 16-bit LE, 0–9599
  [6] 0x00         — wheel (unused)
```
