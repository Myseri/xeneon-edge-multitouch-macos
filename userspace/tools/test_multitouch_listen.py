#!/usr/bin/env python3
"""
Send Input Mode feature report to activate multitouch, then listen for events.

Phase 1 confirmed: hidapi send_feature_report works on Interface 0.
This script skips the crashing IOHIDManager phase and goes straight to:
  1. Send feature reports (mode switch)
  2. Listen via IOHIDEventSystemClient for 30 s

Requires: Input Monitoring granted to Terminal in System Settings → Privacy.
"""

import sys, os, time, ctypes, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

from xeneon_touch.config import VID, PID

# ── frameworks ───────────────────────────────────────────────────────────────
_IOKit = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')
_CF    = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64)

_CF.CFStringCreateWithCString.restype  = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
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

_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes = [_vp, _vp, _vp]

_IOKit.IOHIDEventGetType.restype          = _i32
_IOKit.IOHIDEventGetType.argtypes         = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype    = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes   = [_vp, _i32]
_IOKit.IOHIDEventGetIntegerValue.restype  = _i64
_IOKit.IOHIDEventGetIntegerValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetChildren.restype      = _vp
_IOKit.IOHIDEventGetChildren.argtypes     = [_vp]

kCFStringEncodingUTF8              = 0x08000100
kIOHIDEventSystemClientTypePassive = 4
kIOHIDEventTypeDigitizer           = 11

def _f(i): return (kIOHIDEventTypeDigitizer << 16) | i
kDigitizerX          = _f(0)
kDigitizerY          = _f(1)
kDigitizerTipSwitch  = _f(11)
kDigitizerCollection = _f(15)
kDigitizerIdentity   = _f(17)

_mode = _CF.CFStringCreateWithCString(None, b"kCFRunLoopDefaultMode", kCFStringEncodingUTF8)

# ── Step 1: send mode-switch feature reports ─────────────────────────────────
def send_mode_switch():
    print("── Step 1: send mode-switch feature reports ────────────────────────")

    iface0_path = None
    for d in hid.enumerate(VID, PID):
        if d.get('usage_page') == 0x000D:
            iface0_path = d['path']
            break

    if not iface0_path:
        print("  Interface 0 (digitizer) not found")
        return False

    dev = hid.device()
    try:
        dev.open_path(iface0_path)
    except Exception as e:
        print(f"  open failed: {e}")
        return False

    results = []
    # Report 0x21: Input Mode = 2 (multitouch), Device ID = 0
    try:
        r = dev.send_feature_report([0x21, 0x02, 0x00])
        results.append(f"  Report 0x21 (Input Mode=2): returned {r} {'✓' if r > 0 else '✗'}")
    except Exception as e:
        results.append(f"  Report 0x21 (Input Mode=2): {e}")

    # Report 0x0A: Max Contacts = 10
    try:
        r = dev.send_feature_report([0x0A, 0x0A])
        results.append(f"  Report 0x0A (Max Contacts=10): returned {r} {'✓' if r > 0 else '✗'}")
    except Exception as e:
        results.append(f"  Report 0x0A (Max Contacts=10): {e}")

    # Read back Report 0x21 to confirm the mode was accepted
    try:
        resp = dev.get_feature_report(0x21, 3)
        results.append(f"  Read back 0x21: {bytes(resp).hex(' ')} "
                       f"(Input Mode = {resp[1] if len(resp) > 1 else '?'})")
    except Exception as e:
        results.append(f"  Read back 0x21: {e}")

    dev.close()
    for r in results:
        print(r)

    time.sleep(0.1)   # give controller time to switch modes
    return True


# ── Step 2: listen for IOHIDEventSystemClient events ────────────────────────
_event_total    = [0]
_max_contacts   = [0]
_rl             = [None]

@ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)
def _cb(target, refcon, service, event):
    if not event:
        return
    if _IOKit.IOHIDEventGetType(event) != kIOHIDEventTypeDigitizer:
        return

    _event_total[0] += 1
    is_coll = bool(_IOKit.IOHIDEventGetIntegerValue(event, kDigitizerCollection))

    if is_coll:
        children = _IOKit.IOHIDEventGetChildren(event)
        n = _CF.CFArrayGetCount(children) if children else 0
        if n > _max_contacts[0]:
            _max_contacts[0] = n

        contacts = []
        for i in range(n):
            child = _CF.CFArrayGetValueAtIndex(children, i)
            if child and _IOKit.IOHIDEventGetType(child) == kIOHIDEventTypeDigitizer:
                x   = _IOKit.IOHIDEventGetFloatValue(child, kDigitizerX)
                y   = _IOKit.IOHIDEventGetFloatValue(child, kDigitizerY)
                tip = bool(_IOKit.IOHIDEventGetIntegerValue(child, kDigitizerTipSwitch))
                cid = int(_IOKit.IOHIDEventGetIntegerValue(child, kDigitizerIdentity))
                contacts.append(f"f{cid}({'↓' if tip else '↑'}) ({x:.3f},{y:.3f})")

        tag = "★ MULTITOUCH" if n > 1 else "  single"
        print(f"  {tag}  [{n} contacts] {' | '.join(contacts)}", flush=True)
    else:
        x   = _IOKit.IOHIDEventGetFloatValue(event, kDigitizerX)
        y   = _IOKit.IOHIDEventGetFloatValue(event, kDigitizerY)
        tip = bool(_IOKit.IOHIDEventGetIntegerValue(event, kDigitizerTipSwitch))
        print(f"  [single digitizer] ({x:.3f},{y:.3f}) {'↓' if tip else '↑'}", flush=True)


def listen(duration=30):
    print(f"\n── Step 2: listening for digitizer events ({duration}s) ─────────────")
    print("  → Touch the Xeneon Edge. Try ONE finger, then TWO fingers.\n")

    client = _IOKit.IOHIDEventSystemClientCreateWithType(
        None, kIOHIDEventSystemClientTypePassive, None)

    if not client:
        print("  ✗ IOHIDEventSystemClientCreateWithType returned NULL")
        print("  → Grant Input Monitoring to Terminal:")
        print("    System Settings → Privacy & Security → Input Monitoring")
        return

    print(f"  IOHIDEventSystemClient created: 0x{client:X}")
    _IOKit.IOHIDEventSystemClientRegisterEventCallback(client, _cb, None, None)
    _rl[0] = _CF.CFRunLoopGetCurrent()
    _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(client, _rl[0], _mode)

    def _stop():
        time.sleep(duration)
        _CF.CFRunLoopStop(_rl[0])
    threading.Thread(target=_stop, daemon=True).start()

    _CF.CFRunLoopRun()

    print(f"\n── Results ─────────────────────────────────────────────────────────")
    print(f"  Total digitizer events : {_event_total[0]}")
    print(f"  Max contacts in one frame: {_max_contacts[0]}")

    if _event_total[0] == 0:
        print("\n  0 events — check:")
        print("  1. Input Monitoring: System Settings → Privacy & Security → Input Monitoring")
        print("     Terminal must be listed and checked.")
        print("  2. Try touching the screen AFTER the listener starts.")
        print("  3. Mode switch may not have taken effect — try unplugging/replugging USB-C.")
    elif _max_contacts[0] >= 2:
        print("\n  ★★★ MULTITOUCH CONFIRMED — we can build the full driver! ★★★")
    else:
        print("\n  Single-touch events only. Mode switch may not have taken effect.")
        print("  Try: unplug and replug USB-C, then run this script again.")


def main():
    print("═" * 60)
    print("  Xeneon Edge — multitouch activate + listen")
    print("═" * 60 + "\n")

    ok = send_mode_switch()
    if not ok:
        print("Mode switch failed — check device connection")

    listen(duration=30)
    print("\nDone.")


if __name__ == "__main__":
    main()
