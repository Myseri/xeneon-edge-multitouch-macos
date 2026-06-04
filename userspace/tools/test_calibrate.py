#!/usr/bin/env python3
"""
Calibration / correlation test v2.

Prints two independent streams side-by-side:
  LEFT  — HID touch-down transitions (0→1 on byte[1])
  RIGHT — all CGEvent LMouseDown events

No timing correlation — just see both side by side so we can manually match.

Run: python3 tools/test_calibrate.py
Touch the Xeneon Edge. Also move the regular mouse to confirm CGEventTap is alive.
"""

import sys, os, ctypes, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

from xeneon_touch.hid_mouse import find_mouse_path, _REPORT_ID
from xeneon_touch.config import VID, PID, TOUCH_X_MAX, TOUCH_Y_MAX

# ── CGEventTap ────────────────────────────────────────────────────────────────
_QZ = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
_CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _dbl = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_double

class _CGPoint(ctypes.Structure):
    _fields_ = [("x", _dbl), ("y", _dbl)]

for sig in [
    (_CF, 'CFStringCreateWithCString', _vp, [_vp, ctypes.c_char_p, _u32]),
    (_CF, 'CFRunLoopGetCurrent',        _vp, []),
    (_CF, 'CFRunLoopRun',               None, []),
    (_CF, 'CFRunLoopStop',              None, [_vp]),
    (_QZ, 'CGEventTapCreate',           _vp,  [_i32,_i32,_i32,ctypes.c_uint64,_vp,_vp]),
    (_QZ, 'CGEventTapEnable',           None, [_vp, ctypes.c_bool]),
    (_QZ, 'CFMachPortCreateRunLoopSource', _vp, [_vp,_vp,ctypes.c_long]),
    (_QZ, 'CFRunLoopAddSource',         None, [_vp,_vp,_vp]),
    (_QZ, 'CGEventGetLocation',         _CGPoint, [_vp]),
    (_QZ, 'CGEventGetType',             _u32, [_vp]),
]:
    lib, name, res, args = sig
    fn = getattr(lib, name)
    fn.restype = res; fn.argtypes = args

def _cfstr(s):
    return _CF.CFStringCreateWithCString(None, s.encode(), 0x08000100)

_tap_ready = threading.Event()
_rl = [None]

@ctypes.CFUNCTYPE(_vp, _vp, _u32, _vp, _vp)
def _cg_cb(proxy, etype, event, refcon):
    loc = _QZ.CGEventGetLocation(event)
    t = time.monotonic()
    # Print immediately from callback (runs on tap thread)
    print(f"  CGEvent  loc=({loc.x:8.1f}, {loc.y:8.1f})  t={t:.3f}", flush=True)
    return event

def _run_tap():
    mask = (1 << 1) | (1 << 2) | (1 << 5)  # LDown, LUp, MouseMoved
    tap = _QZ.CGEventTapCreate(0, 0, 1, mask, _cg_cb, None)
    if not tap:
        print("[tap] FAILED — check Accessibility in System Settings")
        _tap_ready.set()
        return
    src = _QZ.CFMachPortCreateRunLoopSource(None, tap, 0)
    _rl[0] = _CF.CFRunLoopGetCurrent()
    _QZ.CFRunLoopAddSource(_rl[0], src, _cfstr("kCFRunLoopDefaultMode"))
    _QZ.CGEventTapEnable(tap, True)
    _tap_ready.set()
    _CF.CFRunLoopRun()

def _run_hid(stop_evt):
    path = find_mouse_path()
    if not path:
        print("[hid] WCH mouse interface not found")
        return
    dev = hid.device()
    dev.open_path(path)
    dev.set_nonblocking(True)

    last_state = None
    last_x, last_y = -1, -1

    print(f"[hid] opened {path}")

    while not stop_evt.is_set():
        data = dev.read(16)
        if not data:
            time.sleep(0.001)
            continue

        raw = bytes(data)
        if len(raw) < 6 or raw[0] != _REPORT_ID:
            continue

        state = bool(raw[1] & 0x01)
        x = raw[2] | (raw[3] << 8)
        y = raw[4] | (raw[5] << 8)

        # Print idle phantom if we see constant same-position touch at startup
        if last_state is None and state:
            print(f"  [HID] NOTE: first report already has touch=1 at "
                  f"({x}, {y}) — possible phantom touch", flush=True)

        # Print ALL transitions
        if state != last_state:
            t = time.monotonic()
            xn = x / TOUCH_X_MAX
            yn = y / TOUCH_Y_MAX
            arrow = "↓ DOWN" if state else "↑ UP  "
            print(f"  HID {arrow}  raw=({x:5d},{y:5d})  norm=({xn:.4f},{yn:.4f})  "
                  f"t={t:.3f}", flush=True)
            last_state = state
            last_x, last_y = x, y

        elif state and (abs(x - last_x) > 50 or abs(y - last_y) > 50):
            # Large movement while touching
            xn = x / TOUCH_X_MAX
            yn = y / TOUCH_Y_MAX
            print(f"  HID DRAG   raw=({x:5d},{y:5d})  norm=({xn:.4f},{yn:.4f})",
                  flush=True)
            last_x, last_y = x, y

    dev.close()

def main():
    path = find_mouse_path()
    if not path:
        sys.exit("WCH device not found")

    print(f"Mouse interface: {path}")
    print("="*70)
    print("Move mouse + tap Xeneon Edge. Both streams print independently.")
    print("CGEvent MouseMoved is throttled — just use it to confirm tap is alive.")
    print("="*70 + "\n")

    stop_evt = threading.Event()
    threading.Thread(target=_run_hid,  args=(stop_evt,), daemon=True).start()
    threading.Thread(target=_run_tap,  daemon=True).start()

    _tap_ready.wait(timeout=2.0)

    try:
        time.sleep(30)
    except KeyboardInterrupt:
        pass

    stop_evt.set()
    if _rl[0]:
        _CF.CFRunLoopStop(_rl[0])
    print("\nDone.")

if __name__ == "__main__":
    main()
