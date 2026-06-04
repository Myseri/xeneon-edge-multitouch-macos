#!/usr/bin/env python3
"""
Diagnostic for IOHIDEventSystemClient.

Runs with NO device filter so we see every event type flowing through
the system. Useful for:
  1. Confirming events arrive at all (if 0, try Input Monitoring permission)
  2. Finding which event types the WCH touch controller emits
  3. Checking what VID/PID the IOHIDServiceClient reports for the device

Run: python3 tools/test_events.py
Touch the Xeneon Edge + wiggle the regular mouse to produce events.
"""

import sys, os, time, ctypes, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ── load frameworks ──────────────────────────────────────────────────────────
_IOKit = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/IOKit.framework/IOKit')
_CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64,
)

# CF basics
_CF.CFStringCreateWithCString.restype  = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
_CF.CFStringGetCString.restype         = ctypes.c_bool
_CF.CFStringGetCString.argtypes        = [_vp, ctypes.c_char_p, _lng, _u32]
_CF.CFGetTypeID.restype                = ctypes.c_ulong
_CF.CFGetTypeID.argtypes               = [_vp]
_CF.CFNumberGetTypeID.restype          = ctypes.c_ulong
_CF.CFNumberGetTypeID.argtypes         = []
_CF.CFNumberGetValue.restype           = ctypes.c_bool
_CF.CFNumberGetValue.argtypes          = [_vp, _lng, _vp]
_CF.CFRunLoopGetCurrent.restype        = _vp
_CF.CFRunLoopGetCurrent.argtypes       = []
_CF.CFRunLoopRun.restype               = None
_CF.CFRunLoopRun.argtypes              = []
_CF.CFRunLoopStop.restype              = None
_CF.CFRunLoopStop.argtypes             = [_vp]

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt64Type   = 4

def _cfstr(s):
    return _CF.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)

def _cfstr_to_py(ref) -> str:
    if not ref:
        return "(null)"
    buf = ctypes.create_string_buffer(256)
    ok = _CF.CFStringGetCString(ref, buf, 256, kCFStringEncodingUTF8)
    return buf.value.decode() if ok else "(unreadable)"

def _cfnum_to_int(ref) -> int:
    v = ctypes.c_int64(0)
    _CF.CFNumberGetValue(ref, kCFNumberSInt64Type, ctypes.byref(v))
    return v.value

# IOHIDEventSystemClient
_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes = [_vp, _vp, _vp]

# IOHIDServiceClient property access
_IOKit.IOHIDServiceClientCopyProperty.restype  = _vp
_IOKit.IOHIDServiceClientCopyProperty.argtypes = [_vp, _vp]

# IOHIDEvent
_IOKit.IOHIDEventGetType.restype         = _i32
_IOKit.IOHIDEventGetType.argtypes        = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype   = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes  = [_vp, _i32]
_IOKit.IOHIDEventGetIntegerValue.restype  = _i64
_IOKit.IOHIDEventGetIntegerValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetChildren.restype     = _vp
_IOKit.IOHIDEventGetChildren.argtypes    = [_vp]
_CF.CFArrayGetCount.restype              = _lng
_CF.CFArrayGetCount.argtypes             = [_vp]
_CF.CFArrayGetValueAtIndex.restype       = _vp
_CF.CFArrayGetValueAtIndex.argtypes      = [_vp, _lng]

# Constants
kIOHIDEventSystemClientTypeMonitor  = 2
kIOHIDEventSystemClientTypePassive  = 4
kIOHIDEventTypeDigitizer            = 11

def _f(idx): return (kIOHIDEventTypeDigitizer << 16) | idx
kIOHIDEventFieldDigitizerX          = _f(0)
kIOHIDEventFieldDigitizerY          = _f(1)
kIOHIDEventFieldDigitizerTipSwitch  = _f(11)
kIOHIDEventFieldDigitizerCollection = _f(15)
kIOHIDEventFieldDigitizerIdentity   = _f(17)

_kDefaultMode = _cfstr("kCFRunLoopDefaultMode")

# ── state ────────────────────────────────────────────────────────────────────
_counts   = {}      # event_type → count
_vid_seen = set()   # (vid, pid) pairs seen
_rl       = None
_deadline = 0.0

_TARGET_VID = 0x27C0
_TARGET_PID = 0x0859

def _svc_prop_int(service, key: str) -> int:
    ref = _IOKit.IOHIDServiceClientCopyProperty(service, _cfstr(key))
    if not ref:
        return -1
    return _cfnum_to_int(ref)

# ── callback ─────────────────────────────────────────────────────────────────
@ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)
def _cb(target, refcon, service, event):
    global _rl
    if not event:
        return

    etype = _IOKit.IOHIDEventGetType(event)
    _counts[etype] = _counts.get(etype, 0) + 1

    vid = _svc_prop_int(service, "VendorID")
    pid = _svc_prop_int(service, "ProductID")
    _vid_seen.add((vid, pid))

    # Detailed print for digitizer events
    if etype == kIOHIDEventTypeDigitizer:
        is_coll = bool(_IOKit.IOHIDEventGetIntegerValue(
            event, kIOHIDEventFieldDigitizerCollection))
        if is_coll:
            children = _IOKit.IOHIDEventGetChildren(event)
            n = _CF.CFArrayGetCount(children) if children else 0
            print(f"[DIGITIZER COLLECTION] vid=0x{vid:04X} pid=0x{pid:04X}  "
                  f"{n} children")
            for i in range(n):
                child = _CF.CFArrayGetValueAtIndex(children, i)
                if child and _IOKit.IOHIDEventGetType(child) == kIOHIDEventTypeDigitizer:
                    x   = _IOKit.IOHIDEventGetFloatValue(child, kIOHIDEventFieldDigitizerX)
                    y   = _IOKit.IOHIDEventGetFloatValue(child, kIOHIDEventFieldDigitizerY)
                    tip = bool(_IOKit.IOHIDEventGetIntegerValue(
                        child, kIOHIDEventFieldDigitizerTipSwitch))
                    cid = int(_IOKit.IOHIDEventGetIntegerValue(
                        child, kIOHIDEventFieldDigitizerIdentity))
                    print(f"  finger {cid}: x={x:.4f} y={y:.4f} tip={'↓' if tip else '↑'}")
        else:
            x   = _IOKit.IOHIDEventGetFloatValue(event, kIOHIDEventFieldDigitizerX)
            y   = _IOKit.IOHIDEventGetFloatValue(event, kIOHIDEventFieldDigitizerY)
            tip = bool(_IOKit.IOHIDEventGetIntegerValue(
                event, kIOHIDEventFieldDigitizerTipSwitch))
            print(f"[DIGITIZER] vid=0x{vid:04X} pid=0x{pid:04X}  "
                  f"x={x:.4f} y={y:.4f} tip={'↓' if tip else '↑'}")

    # Stop after deadline (checked on each event to avoid timer setup)
    if time.monotonic() > _deadline:
        _CF.CFRunLoopStop(_rl)


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    global _rl, _deadline

    print("Trying kIOHIDEventSystemClientTypeMonitor (type=2) — no filter")
    print("Touch the Xeneon Edge + move mouse for 20 seconds …\n")

    for type_name, type_val in [
        ("Monitor (2)",  kIOHIDEventSystemClientTypeMonitor),
        ("Passive (4)",  kIOHIDEventSystemClientTypePassive),
    ]:
        _counts.clear(); _vid_seen.clear()
        client = _IOKit.IOHIDEventSystemClientCreateWithType(None, type_val, None)
        if not client:
            print(f"  {type_name}: IOHIDEventSystemClientCreateWithType returned NULL")
            continue

        # NO matching — receive everything
        _IOKit.IOHIDEventSystemClientRegisterEventCallback(client, _cb, None, None)

        import threading
        _deadline = time.monotonic() + 10.0
        _rl_holder = [None]

        def _run():
            global _rl
            _rl = _CF.CFRunLoopGetCurrent()
            _rl_holder[0] = _rl
            _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(
                client, _rl, _kDefaultMode)
            _CF.CFRunLoopRun()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=12)

        print(f"\n── {type_name} results ──")
        if not _counts:
            print("  0 events received")
        else:
            print(f"  Devices seen: {[f'VID=0x{v:04X} PID=0x{p:04X}' for v,p in sorted(_vid_seen)]}")
            print(f"  Event type counts: {dict(sorted(_counts.items()))}")
            print(f"  (type 11 = Digitizer, 1 = Button, 4 = Scroll, 5 = Pointer, 12 = Keyboard)")
        print()

        # Stop the run loop if still going
        if _rl_holder[0]:
            _CF.CFRunLoopStop(_rl_holder[0])

if __name__ == "__main__":
    main()
