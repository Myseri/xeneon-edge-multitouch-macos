#!/usr/bin/env python3
"""
Same IOHIDEventSystemClient test, but forces execution on the MAIN run loop.
Some CoreFoundation event sources only deliver to the main thread's run loop.

Run: python3 tools/test_events_main.py
Then touch + move mouse for 15 seconds.
"""

import sys, os, ctypes, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_IOKit = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')
_CF    = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64)

_CF.CFStringCreateWithCString.restype   = _vp
_CF.CFStringCreateWithCString.argtypes  = [_vp, ctypes.c_char_p, _u32]
_CF.CFRunLoopGetCurrent.restype         = _vp
_CF.CFRunLoopGetCurrent.argtypes        = []
_CF.CFRunLoopRun.restype                = None
_CF.CFRunLoopRun.argtypes               = []
_CF.CFRunLoopStop.restype               = None
_CF.CFRunLoopStop.argtypes              = [_vp]

_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes  = [_vp, _vp, _vp]
_IOKit.IOHIDEventGetType.restype        = _i32
_IOKit.IOHIDEventGetType.argtypes       = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype  = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes = [_vp, _i32]

kCFStringEncodingUTF8               = 0x08000100
kIOHIDEventSystemClientTypeMonitor  = 2
kIOHIDEventTypeDigitizer            = 11

def _cfstr(s):
    return _CF.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)

_mode = _cfstr("kCFRunLoopDefaultMode")

_count = [0]
_rl    = [None]

@ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)
def _cb(target, refcon, service, event):
    if not event:
        return
    etype = _IOKit.IOHIDEventGetType(event)
    _count[0] += 1
    print(f"[event] type={etype}  total={_count[0]}", flush=True)

def main():
    client = _IOKit.IOHIDEventSystemClientCreateWithType(
        None, kIOHIDEventSystemClientTypeMonitor, None)
    if not client:
        sys.exit("IOHIDEventSystemClientCreateWithType returned NULL")
    print(f"client OK: 0x{client:X}")

    _IOKit.IOHIDEventSystemClientRegisterEventCallback(client, _cb, None, None)

    # Get the MAIN thread run loop (this IS the main thread)
    _rl[0] = _CF.CFRunLoopGetCurrent()
    print(f"run loop: 0x{_rl[0]:X}")

    _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(client, _rl[0], _mode)
    print("Scheduled. Listening on main run loop for 15 s — touch the screen…\n")

    def _stop():
        time.sleep(15)
        print(f"\nTimeout. {_count[0]} events received.")
        _CF.CFRunLoopStop(_rl[0])
    threading.Thread(target=_stop, daemon=True).start()

    _CF.CFRunLoopRun()   # blocks main thread

if __name__ == "__main__":
    main()
