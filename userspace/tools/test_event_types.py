#!/usr/bin/env python3
"""
Catch ALL IOHIDEventSystemClient event types across all client type values.
Also reads Interface 2 simultaneously to see if report format changes after
the mode switch.

Objective: figure out what event type (if any) the digitizer actually emits,
and whether Interface 2 changes after Input Mode = 2 is sent.
"""

import sys, os, time, ctypes, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

from xeneon_touch.config import VID, PID, TOUCH_X_MAX, TOUCH_Y_MAX

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

_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]
_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes = [_vp, _vp, _vp]

_IOKit.IOHIDEventGetType.restype  = _i32
_IOKit.IOHIDEventGetType.argtypes = [_vp]

kCFStringEncodingUTF8 = 0x08000100
_mode = _CF.CFStringCreateWithCString(None, b"kCFRunLoopDefaultMode", kCFStringEncodingUTF8)

EVENT_TYPE_NAMES = {
    0: "Null", 1: "VendorDefined", 2: "Button", 3: "KeyboardEvent",
    4: "Scroll", 5: "Pointer", 6: "Temperature", 7: "Accel",
    8: "Gyro", 9: "Compass", 10: "ZoomToggle", 11: "Digitizer",
    12: "Ambient", 13: "Power", 14: "Proximity", 15: "Progress",
    16: "MultiAxisPointer", 17: "Force", 18: "Motion", 19: "AmbientLight",
    20: "Count",
}

# ── send mode switch ─────────────────────────────────────────────────────────
def send_mode_switch():
    print("Sending mode switch (Input Mode = 2) …")
    for d in hid.enumerate(VID, PID):
        if d.get('usage_page') == 0x000D:
            dev = hid.device()
            try:
                dev.open_path(d['path'])
                r1 = dev.send_feature_report([0x21, 0x02, 0x00])
                r2 = dev.send_feature_report([0x0A, 0x0A])
                # read back to confirm
                rb = dev.get_feature_report(0x21, 3)
                mode_val = rb[1] if len(rb) > 1 else -1
                print(f"  0x21 sent (ret={r1}), 0x0A sent (ret={r2}), "
                      f"read-back Input Mode = {mode_val}")
                dev.close()
                return True
            except Exception as e:
                print(f"  send failed: {e}")
                try: dev.close()
                except: pass
    print("  Interface 0 not found")
    return False


# ── IOHIDEventSystemClient: try client types 0-4 ────────────────────────────
_counts     = {}   # client_type → {event_type → count}
_rl_holder  = [None]
_active_type = [None]

def _make_cb(client_type):
    @ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)
    def _cb(target, refcon, service, event):
        if not event:
            return
        etype = _IOKit.IOHIDEventGetType(event)
        ct = _active_type[0]
        if ct not in _counts:
            _counts[ct] = {}
        _counts[ct][etype] = _counts[ct].get(etype, 0) + 1
        name = EVENT_TYPE_NAMES.get(etype, f"type_{etype}")
        print(f"  [client={ct}] event type={etype} ({name})", flush=True)
    return _cb   # caller must keep reference

_callbacks = []  # prevent GC

def try_client_type(ctype, duration=8):
    global _rl_holder
    _active_type[0] = ctype
    cb = _make_cb(ctype)
    _callbacks.append(cb)  # keep alive

    client = _IOKit.IOHIDEventSystemClientCreateWithType(None, ctype, None)
    if not client:
        print(f"  type={ctype}: CreateWithType returned NULL — skipping")
        return

    _IOKit.IOHIDEventSystemClientRegisterEventCallback(client, cb, None, None)

    done = threading.Event()
    rl = [None]

    def _run():
        rl[0] = _CF.CFRunLoopGetCurrent()
        _rl_holder[0] = rl[0]
        _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(client, rl[0], _mode)
        _CF.CFRunLoopRun()
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(duration)
    if rl[0]:
        _CF.CFRunLoopStop(rl[0])
    done.wait(timeout=2)

    got = _counts.get(ctype, {})
    total = sum(got.values())
    print(f"  → type={ctype}: {total} events  {dict(sorted(got.items()))}")


# ── Interface 2 monitor (runs in background throughout) ─────────────────────
_iface2_reports = []
_iface2_stop    = threading.Event()

def _run_iface2():
    path = None
    for d in hid.enumerate(VID, PID):
        if d.get('usage_page') == 0x0001 and d.get('usage') == 0x0002:
            path = d['path']
            break
    if not path:
        return

    dev = hid.device()
    try:
        dev.open_path(path)
        dev.set_nonblocking(True)
    except Exception as e:
        print(f"[iface2] open failed: {e}")
        return

    last = None
    while not _iface2_stop.is_set():
        data = dev.read(16)
        if data:
            raw = bytes(data)
            if raw != last:
                _iface2_reports.append((time.monotonic(), raw.hex(' ')))
                last = raw
        else:
            time.sleep(0.001)
    dev.close()


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    print("═" * 60)
    print("  Event type survey + Interface 2 monitor")
    print("═" * 60)

    # start Interface 2 background reader
    t2 = threading.Thread(target=_run_iface2, daemon=True)
    t2.start()

    send_mode_switch()
    time.sleep(0.2)

    print("\nTrying IOHIDEventSystemClient types 0–4 (8 s each).")
    print("Touch the Xeneon Edge screen during each window.\n")

    for ctype in range(5):
        print(f"\n── Client type {ctype} — touch the screen now for 8 s ──")
        try_client_type(ctype, duration=8)

    _iface2_stop.set()
    t2.join(timeout=1)

    print("\n── Interface 2 report changes during this run ──────────────────")
    if not _iface2_reports:
        print("  (no reports — device not touched or not readable)")
    for ts, hexdata in _iface2_reports[-30:]:   # last 30 unique reports
        print(f"  t+{ts:.2f}  {hexdata}")

    print("\nDone.")


if __name__ == "__main__":
    main()

