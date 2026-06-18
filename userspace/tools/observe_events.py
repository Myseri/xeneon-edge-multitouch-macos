#!/usr/bin/env python3
"""
Diagnostic: passively observe ALL IOHIDEvents and print their type + positional
fields. No device open (avoids the exclusive-access lock on interface 2).

Run it, then touch the Xeneon Edge. Whatever event type spikes is the one the
mouse interface produces; f0/f1 are its first two positional fields (often X/Y).

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/hidapi/lib \
      python3 tools/observe_events.py

Needs Input Monitoring granted to the launching app (Terminal).
"""
import ctypes, time

_IOKit = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')
_CF    = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
_vp, _i32, _u32, _dbl, _i64 = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_double, ctypes.c_int64

_CF.CFRunLoopGetCurrent.restype = _vp
_CF.CFStringCreateWithCString.restype = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
_CF.CFArrayGetCount.restype = ctypes.c_long
_CF.CFArrayGetCount.argtypes = [_vp]
_CF.CFArrayGetValueAtIndex.restype = _vp
_CF.CFArrayGetValueAtIndex.argtypes = [_vp, ctypes.c_long]

_IOKit.IOHIDEventSystemClientCreateWithType.restype = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes = [_vp, _vp, _vp]
_IOKit.IOHIDEventGetType.restype = _i32
_IOKit.IOHIDEventGetType.argtypes = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetIntegerValue.restype = _i64
_IOKit.IOHIDEventGetIntegerValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetChildren.restype = _vp
_IOKit.IOHIDEventGetChildren.argtypes = [_vp]

kPassive = 4
mode = _CF.CFStringCreateWithCString(None, b"kCFRunLoopDefaultMode", 0x08000100)
_CB = ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)

seen = {}

def describe(ev, depth=0):
    t = _IOKit.IOHIDEventGetType(ev)
    f0 = _IOKit.IOHIDEventGetFloatValue(ev, (t << 16) | 0)
    f1 = _IOKit.IOHIDEventGetFloatValue(ev, (t << 16) | 1)
    i0 = _IOKit.IOHIDEventGetIntegerValue(ev, (t << 16) | 0)
    i1 = _IOKit.IOHIDEventGetIntegerValue(ev, (t << 16) | 1)
    seen[t] = seen.get(t, 0) + 1
    print(f"{'  '*depth}type={t:<3} f0={f0:9.4f} f1={f1:9.4f} i0={i0} i1={i1}")
    ch = _IOKit.IOHIDEventGetChildren(ev)
    if ch:
        for i in range(_CF.CFArrayGetCount(ch)):
            describe(_CF.CFArrayGetValueAtIndex(ch, i), depth + 1)

def cb(target, refcon, service, event):
    if event:
        describe(event)

_cb = _CB(cb)
client = _IOKit.IOHIDEventSystemClientCreateWithType(None, kPassive, None)
if not client:
    print("client NULL — Input Monitoring not granted to this app?"); raise SystemExit(1)
_IOKit.IOHIDEventSystemClientRegisterEventCallback(client, _cb, None, None)
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop(client, _CF.CFRunLoopGetCurrent(), mode)
print("Observing — touch the Xeneon Edge now. Ctrl-C to stop and see the type tally.")
try:
    _CF.CFRunLoopRun.argtypes = []
    _CF.CFRunLoopRun()
except KeyboardInterrupt:
    pass
finally:
    print("\nEvent type tally:", seen)
