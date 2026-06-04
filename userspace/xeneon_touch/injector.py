"""
Touch injector — warps cursor and posts synthetic click events.

CGWarpMouseCursorPosition moves the cursor visually, but click events
from the WCH device register at the pre-warp position. We post our own
synthetic mouse events at the correct Xeneon Edge coordinates.
"""

import ctypes
import logging
import threading
import time
from typing import Optional

from .display import DisplayMapper

log = logging.getLogger(__name__)

# ── frameworks ────────────────────────────────────────────────────────────────
_QZ = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')

_vp  = ctypes.c_void_p
_i32 = ctypes.c_int32
_u32 = ctypes.c_uint32
_dbl = ctypes.c_double

class _CGPoint(ctypes.Structure):
    _fields_ = [("x", _dbl), ("y", _dbl)]

_QZ.CGWarpMouseCursorPosition.restype  = _i32
_QZ.CGWarpMouseCursorPosition.argtypes = [_CGPoint]

_QZ.CGEventCreateMouseEvent.restype  = _vp
_QZ.CGEventCreateMouseEvent.argtypes = [_vp, _u32, _CGPoint, _u32]

_QZ.CGEventPost.restype  = None
_QZ.CGEventPost.argtypes = [_u32, _vp]

_QZ.CFRelease.restype  = None
_QZ.CFRelease.argtypes = [_vp]

kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp   = 2
kCGEventMouseMoved    = 5
kCGHIDEventTap        = 0
kCGMouseButtonLeft    = 0


class TouchInjector:
    def __init__(self, mapper: DisplayMapper):
        self.mapper   = mapper
        self._reader  = None
        self._thread: Optional[threading.Thread] = None
        self._active  = False

    def attach_reader(self, reader):
        self._reader = reader

    def start(self):
        self._active = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="TouchInject")
        self._thread.start()
        log.info("Touch injector started.")

    def stop(self):
        self._active = False

    def _post(self, event_type: int, pt: _CGPoint):
        ev = _QZ.CGEventCreateMouseEvent(None, event_type, pt, kCGMouseButtonLeft)
        if ev:
            _QZ.CGEventPost(kCGHIDEventTap, ev)
            _QZ.CFRelease(ev)

    def _loop(self):
        was_touching = False

        while self._active:
            if self._reader is None:
                time.sleep(0.01)
                continue

            report = self._reader.read(timeout=0.02)
            if report is None:
                continue

            pt = self._map(report.x_norm, report.y_norm)

            if report.touch:
                # Always warp cursor to correct position
                _QZ.CGWarpMouseCursorPosition(pt)

                if not was_touching:
                    # Touch down — post a left mouse down
                    time.sleep(0.008)   # let warp settle first
                    self._post(kCGEventLeftMouseDown, pt)
                    log.debug("DOWN → (%.1f, %.1f)", pt.x, pt.y)
                else:
                    # Drag
                    self._post(kCGEventMouseMoved, pt)

                was_touching = True

            elif was_touching:
                # Touch up — post left mouse up
                self._post(kCGEventLeftMouseUp, pt)
                log.debug("UP   → (%.1f, %.1f)", pt.x, pt.y)
                was_touching = False

    def _map(self, x_norm: float, y_norm: float) -> _CGPoint:
        pt = self.mapper.to_screen(x_norm, y_norm)
        return _CGPoint(x=pt.x, y=pt.y)
