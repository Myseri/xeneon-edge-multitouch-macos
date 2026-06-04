#!/usr/bin/env python3
"""
CGEventTap diagnostic — dumps every field of mouse events.

This lets us see:
  - Whether touch events have absolute coords (kCGTabletEventPointX/Y)
  - What the source device ID is (to identify WCH events)
  - Delta vs absolute — which tells us the architecture we need

Requires Accessibility permission.

Run: python3 tools/test_cgevent_dump.py
Touch the Xeneon Edge AND move the regular mouse so we can compare.
"""

import sys, os, ctypes, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_QZ = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
_CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64)

# CF
_CF.CFRunLoopGetCurrent.restype  = _vp
_CF.CFRunLoopGetCurrent.argtypes = []
_CF.CFRunLoopRun.restype         = None
_CF.CFRunLoopRun.argtypes        = []
_CF.CFRunLoopStop.restype        = None
_CF.CFRunLoopStop.argtypes       = [_vp]

# CGEventTap
class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

_QZ.CGEventTapCreate.restype  = _vp
_QZ.CGEventTapCreate.argtypes = [_i32, _i32, _i32, ctypes.c_uint64, _vp, _vp]
_QZ.CGEventTapEnable.restype  = None
_QZ.CGEventTapEnable.argtypes = [_vp, ctypes.c_bool]
_QZ.CFMachPortCreateRunLoopSource.restype  = _vp
_QZ.CFMachPortCreateRunLoopSource.argtypes = [_vp, _vp, _lng]
_QZ.CFRunLoopAddSource.restype  = None
_QZ.CFRunLoopAddSource.argtypes = [_vp, _vp, _vp]
_QZ.CGEventGetLocation.restype  = _CGPoint
_QZ.CGEventGetLocation.argtypes = [_vp]
_QZ.CGEventGetIntegerValueField.restype  = _i64
_QZ.CGEventGetIntegerValueField.argtypes = [_vp, _i32]
_QZ.CGEventGetDoubleValueField.restype   = _dbl
_QZ.CGEventGetDoubleValueField.argtypes  = [_vp, _i32]
_QZ.CGEventGetType.restype  = _u32
_QZ.CGEventGetType.argtypes = [_vp]

_CF.CFStringCreateWithCString.restype   = _vp
_CF.CFStringCreateWithCString.argtypes  = [_vp, ctypes.c_char_p, _u32]

def _cfstr(s):
    return _CF.CFStringCreateWithCString(None, s.encode(), 0x08000100)

kCGHIDEventTap      = 0
kCGHeadInsertEventTap = 0
kCGEventTapOptionListenOnly = 1   # passive — no Accessibility needed to just listen
kCGEventMaskForAllEvents = (1 << 29) - 1   # all events

# CGEventType
kCGEventLeftMouseDown   = 1
kCGEventLeftMouseUp     = 2
kCGEventMouseMoved      = 5
kCGEventLeftMouseDragged = 6
kCGEventOtherMouseDown  = 25

# Event fields we care about
FIELDS = {
    "deltaX":           1,
    "deltaY":           2,
    "pressure":         3,
    "buttonNumber":     4,
    "tabletPointX":     14,
    "tabletPointY":     15,
    "tabletPointZ":     16,
    "tabletPressure":   18,
    "tabletDeviceID":   23,
    "sourceStateID":    43,
    "sourceDeviceID":   99,   # unofficial but sometimes works
    "unaccelX":         170,
    "unaccelY":         171,
}

_TYPE_NAMES = {
    1:"LMouseDown", 2:"LMouseUp", 5:"MouseMoved",
    6:"LDragged", 25:"OtherDown",
}

_rl   = [None]
_last = [0.0]
_count = [0]

@ctypes.CFUNCTYPE(_vp, _vp, _u32, _vp, _vp)
def _cb(proxy, etype, event, refcon):
    now = time.monotonic()
    if now - _last[0] < 0.05 and etype == 5:   # throttle MouseMoved
        return event
    _last[0] = now
    _count[0] += 1

    loc = _QZ.CGEventGetLocation(event)
    name = _TYPE_NAMES.get(etype, str(etype))
    print(f"\n── {name}  loc=({loc.x:.1f}, {loc.y:.1f})")

    for fname, fid in FIELDS.items():
        try:
            iv = _QZ.CGEventGetIntegerValueField(event, fid)
            dv = _QZ.CGEventGetDoubleValueField(event, fid)
            if iv != 0 or abs(dv) > 0.001:
                print(f"   {fname:<18} int={iv:>10}  dbl={dv:.4f}")
        except Exception:
            pass

    if _count[0] >= 30:
        _CF.CFRunLoopStop(_rl[0])

    return event

def main():
    mask = (
        (1 << kCGEventLeftMouseDown)  |
        (1 << kCGEventLeftMouseUp)    |
        (1 << kCGEventMouseMoved)     |
        (1 << kCGEventLeftMouseDragged)
    )
    tap = _QZ.CGEventTapCreate(
        kCGHIDEventTap, kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        mask, _cb, None)

    if not tap:
        sys.exit("CGEventTapCreate failed — grant Accessibility in System Settings "
                 "→ Privacy & Security → Accessibility")

    print("CGEventTap created. Touch Xeneon Edge + move regular mouse.")
    print("Will print up to 30 events then exit.\n")

    src = _QZ.CFMachPortCreateRunLoopSource(None, tap, 0)
    _rl[0] = _CF.CFRunLoopGetCurrent()
    _QZ.CFRunLoopAddSource(_rl[0], src, _cfstr("kCFRunLoopDefaultMode"))
    _QZ.CGEventTapEnable(tap, True)

    def _timeout():
        time.sleep(30)
        _CF.CFRunLoopStop(_rl[0])
    threading.Thread(target=_timeout, daemon=True).start()

    _CF.CFRunLoopRun()
    print(f"\nDone. {_count[0]} events captured.")

if __name__ == "__main__":
    main()
