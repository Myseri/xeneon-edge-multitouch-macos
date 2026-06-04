# Xeneon Edge Touch — DriverKit Extension

DriverKit driver for 5-point multitouch on the Corsair Xeneon Edge.

## Current State

The driver is **functionally complete and hardware-verified** but requires an Apple Developer Program membership to sign and run.

What works:
- Correctly matches `IOUSBHostInterface` (VID=0x27C0, PID=0x0859, bInterfaceNumber=0)
- Outbids `AppleUserHIDDevice` at `IOProbeScore 200000 vs 50001`
- `IODEXTMatchCount=1` confirmed in ioreg — hardware match is live
- Sends HID Input Mode=2 feature report at init to unlock multitouch
- Parses 10-finger Report 0x0D and dispatches `dispatchDigitizerContactEvent`

What's blocked:
- `TeamIdentifier=not set` on self-signed certificates → user server process never launches
- Requires an Apple-issued certificate with a real Team ID

## Requirements to Build and Run

1. **Apple Developer Program** ($99/yr) — [developer.apple.com/programs/enroll](https://developer.apple.com/programs/enroll)
2. **DriverKit USB transport entitlement** — request at [developer.apple.com/contact/request/system-extension](https://developer.apple.com/contact/request/system-extension)
3. Xcode 15 or later
4. macOS 13 or later (deployment target: DriverKit 21.0+)

## Build Instructions

> **Note:** The project's bundle IDs use `com.jonathanmartin.*` as placeholders.
> Replace with your own Team ID prefix before building.
> The run script also references a local signing certificate named `"XeneonDext"` —
> replace with your Developer ID certificate name.

1. Open `XeneonTouchDriverApp.xcodeproj` in Xcode
2. Add your Apple Developer account in Xcode → Settings → Accounts
3. Update bundle identifiers to match your Team ID:
   - App: `com.YOURTEAM.XeneonTouchDriverApp`
   - Extension: `com.YOURTEAM.XeneonTouchDriverApp.XeneonTouchDriver`
4. Enable Automatically Manage Signing on both targets
5. Build (⌘B) → Run (⌘R) → click **Install Driver**
6. Approve in System Settings → General → Login Items & Extensions → Driver Extensions
7. Replug the Xeneon Edge USB-C

## Architecture

```
XeneonTouchDriverApp.app          ← macOS wrapper (required by DriverKit)
└── Contents/
    └── Library/
        └── SystemExtensions/
            └── XeneonTouchDriver.dext   ← DriverKit extension
```

The `.dext` matches on `IOUSBHostInterface` with the WCH VID/PID and claims Interface 0
before `AppleUserHIDDevice`. On `Start()`:

1. `IOSleep(50)` — lets USB stack settle
2. `setReport(0x21, [0x02, 0x00])` — Input Mode = 2 (multitouch)
3. `setReport(0x0A, [0x0A])` — Max Contacts = 10

On each `handleReport()` for Report ID `0x0D`:

```
Report layout (54 bytes total):
  [0]     Report ID (0x0D)
  [1..50] 10 × 5 bytes per contact:
            bit 0:    tip switch (touch down)
            bits 1-3: padding
            bits 4-7: contact ID (0-15)
            [+1,+2]:  X (16-bit LE, 0-16383)
            [+3,+4]:  Y (16-bit LE, 0-9599)
  [51-52] Scan time (16-bit)
  [53]    Active contact count
```

Each contact calls `dispatchDigitizerContactEvent()` with normalised (0.0–1.0) coordinates.

## Files

| File | Description |
|------|-------------|
| `XeneonTouchDriver/XeneonTouchDriver.iig` | DriverKit interface definition (Start, Stop) |
| `XeneonTouchDriver/XeneonTouchDriver.cpp` | Driver implementation |
| `XeneonTouchDriver/Info.plist` | IOKit matching rules (VID, PID, interface, probe score) |
| `XeneonTouchDriver/XeneonTouchDriver.entitlements` | DriverKit entitlements |
| `XeneonTouchDriverApp/ContentView.swift` | Install/uninstall UI |
| `XeneonTouchDriverApp/XeneonTouchDriverApp.swift` | App entry point |

## IOKit Matching

```xml
IOProviderClass:   IOUSBHostInterface
idVendor:          10176  (0x27C0)
idProduct:         2137   (0x0859)
bInterfaceNumber:  0
bInterfaceClass:   3      (HID)
IOProbeScore:      200000
```

## Verified Hardware Behaviour

- **Windows:** 5-point multitouch works natively, no drivers needed
- **macOS (USB-C only):** firmware serves a reduced descriptor; Input Mode defaults to 1
- **macOS (HDMI + USB-C):** full 10-finger descriptor exposed; Input Mode still defaults to 1
- **DriverKit intervention:** claims Interface 0, sends Input Mode=2, multitouch activates

The firmware deliberately presents different descriptors per OS. The Input Mode feature
report is the unlock command — equivalent to what UPDD sends at init.
