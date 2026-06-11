"""
Touch injector — maps IOHIDEventReader contacts to macOS input events.

State machine:
  IDLE   → no fingers down
  SINGLE → exactly 1 finger: mouse move / left-click / drag
  SCROLL → exactly 2 fingers: two-finger scroll (vertical + horizontal)
  3+ fingers are ignored (any active gesture is cancelled first).

Scroll uses CGEventCreateScrollWheelEvent with kCGScrollEventUnitPixel and
phase markers (Began/Changed/Ended) so apps that honour scroll phases (Safari,
Maps, Photos, etc.) get proper rubber-band / momentum behaviour.
"""

import ctypes
import logging
import threading
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from .display import DisplayMapper
from .event_reader import TouchContact

log = logging.getLogger(__name__)

# ── Quartz / ApplicationServices ─────────────────────────────────────────────
_QZ = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)

_vp  = ctypes.c_void_p
_i32 = ctypes.c_int32
_i64 = ctypes.c_int64
_u32 = ctypes.c_uint32
_dbl = ctypes.c_double


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", _dbl), ("y", _dbl)]


# CGWarpMouseCursorPosition
_QZ.CGWarpMouseCursorPosition.restype  = _i32
_QZ.CGWarpMouseCursorPosition.argtypes = [_CGPoint]

# CGEventCreateMouseEvent(source, mouseType, mouseCursorPosition, mouseButton)
_QZ.CGEventCreateMouseEvent.restype  = _vp
_QZ.CGEventCreateMouseEvent.argtypes = [_vp, _u32, _CGPoint, _u32]

# CGEventCreateScrollWheelEvent(source, units, wheelCount, wheel1, wheel2)
_QZ.CGEventCreateScrollWheelEvent.restype  = _vp
_QZ.CGEventCreateScrollWheelEvent.argtypes = [_vp, _u32, _u32, _i32, _i32]

# CGEventSetIntegerValueField(event, field, value)
_QZ.CGEventSetIntegerValueField.restype  = None
_QZ.CGEventSetIntegerValueField.argtypes = [_vp, _i32, _i64]

# CGEventPost(tap, event)
_QZ.CGEventPost.restype  = None
_QZ.CGEventPost.argtypes = [_u32, _vp]

# CFRelease
_QZ.CFRelease.restype  = None
_QZ.CFRelease.argtypes = [_vp]

# ── CGEvent constants ─────────────────────────────────────────────────────────
kCGEventLeftMouseDown    = 1
kCGEventLeftMouseUp      = 2
kCGEventLeftMouseDragged = 6
kCGHIDEventTap           = 0
kCGMouseButtonLeft       = 0

kCGScrollEventUnitPixel  = 1

# CGEventField index for scroll phase (IOLLEvent.h kCGScrollWheelEventScrollPhase)
_kScrollPhaseField = 132

# Phase bitmasks (match NSEventPhase)
kCGScrollEventPhaseNone    = 0
kCGScrollEventPhaseBegan   = 1
kCGScrollEventPhaseChanged = 2
kCGScrollEventPhaseEnded   = 4

# ── Tuning ────────────────────────────────────────────────────────────────────
# Pixels of scroll per normalised unit of finger travel (0..1 = full display).
# Increase if scrolling feels sluggish; decrease if it's too sensitive.
SCROLL_SENSITIVITY_V = 8.0
SCROLL_SENSITIVITY_H = 8.0


class _State(Enum):
    IDLE   = auto()
    SINGLE = auto()
    SCROLL = auto()


class TouchInjector:
    def __init__(self, mapper: DisplayMapper):
        self.mapper  = mapper
        self._display_w = mapper.bounds.size.width
        self._display_h = mapper.bounds.size.height

        self._reader  = None
        self._thread: Optional[threading.Thread] = None
        self._active  = False

        self._state   = _State.IDLE
        self._last_pt = _CGPoint(x=0.0, y=0.0)
        # {contact_id: (x_norm, y_norm)} from the previous frame
        self._prev_fingers: Dict[int, Tuple[float, float]] = {}

        self._first_event_logged = False

    # ── public API ────────────────────────────────────────────────────────────

    def attach_reader(self, reader) -> None:
        self._reader = reader

    def start(self) -> None:
        self._active = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="TouchInject"
        )
        self._thread.start()
        log.info("Touch injector started.")

    def stop(self) -> None:
        self._active = False

    # ── low-level event helpers ───────────────────────────────────────────────

    def _post_mouse(self, ev_type: int, pt: _CGPoint) -> None:
        ev = _QZ.CGEventCreateMouseEvent(None, ev_type, pt, kCGMouseButtonLeft)
        if ev:
            _QZ.CGEventPost(kCGHIDEventTap, ev)
            _QZ.CFRelease(ev)

    def _post_scroll(self, dy: int, dx: int, phase: int) -> None:
        ev = _QZ.CGEventCreateScrollWheelEvent(
            None, kCGScrollEventUnitPixel, 2, dy, dx
        )
        if ev:
            if phase != kCGScrollEventPhaseNone:
                _QZ.CGEventSetIntegerValueField(ev, _kScrollPhaseField, phase)
            _QZ.CGEventPost(kCGHIDEventTap, ev)
            _QZ.CFRelease(ev)

    def _map(self, x_norm: float, y_norm: float) -> _CGPoint:
        pt = self.mapper.to_screen(x_norm, y_norm)
        return _CGPoint(x=pt.x, y=pt.y)

    # ── main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._active:
            if self._reader is None:
                time.sleep(0.01)
                continue

            frame = self._reader.read(timeout=0.02)
            if frame is None:
                continue

            # Log first event so we can verify coordinate range in the output
            if not self._first_event_logged and frame:
                c0 = frame[0]
                log.info(
                    "First touch event — x=%.5f y=%.5f tip=%s id=%d  "
                    "(expected x/y in 0..1; if not, DisplayMapper scaling is off)",
                    c0.x, c0.y, c0.tip_switch, c0.contact_id,
                )
                self._first_event_logged = True

            active: Dict[int, TouchContact] = {
                c.contact_id: c for c in frame if c.active
            }
            n = len(active)

            if n == 0:
                self._on_lift()
            elif n == 1:
                self._on_single(next(iter(active.values())))
            elif n == 2:
                self._on_scroll(list(active.values()))
            else:
                # 3+ fingers: cancel any active gesture and ignore
                self._on_lift()

            self._prev_fingers = {
                cid: (c.x, c.y) for cid, c in active.items()
            }

    # ── gesture handlers ──────────────────────────────────────────────────────

    def _on_lift(self) -> None:
        if self._state == _State.SINGLE:
            self._post_mouse(kCGEventLeftMouseUp, self._last_pt)
            log.debug("UP   → (%.1f, %.1f)", self._last_pt.x, self._last_pt.y)
        elif self._state == _State.SCROLL:
            self._post_scroll(0, 0, phase=kCGScrollEventPhaseEnded)
            log.debug("SCROLL END")
        self._state = _State.IDLE
        self._prev_fingers = {}

    def _on_single(self, contact: TouchContact) -> None:
        # Cleanly end an active scroll before switching to single-touch
        if self._state == _State.SCROLL:
            self._post_scroll(0, 0, phase=kCGScrollEventPhaseEnded)

        pt = self._map(contact.x, contact.y)
        _QZ.CGWarpMouseCursorPosition(pt)

        if self._state != _State.SINGLE:
            # New touch-down — short delay so cursor warp settles first
            time.sleep(0.008)
            self._post_mouse(kCGEventLeftMouseDown, pt)
            log.debug("DOWN → (%.1f, %.1f)", pt.x, pt.y)
        else:
            # Drag
            self._post_mouse(kCGEventLeftMouseDragged, pt)

        self._last_pt = pt
        self._state   = _State.SINGLE

    def _on_scroll(self, contacts: List[TouchContact]) -> None:
        # Cleanly end a single-touch gesture before switching to scroll
        if self._state == _State.SINGLE:
            self._post_mouse(kCGEventLeftMouseUp, self._last_pt)

        # Centroid of the two fingers this frame
        cx = sum(c.x for c in contacts) / 2.0
        cy = sum(c.y for c in contacts) / 2.0

        if len(self._prev_fingers) == 2:
            prev_cx = sum(x for x, _y in self._prev_fingers.values()) / 2.0
            prev_cy = sum(_y for _x, _y in self._prev_fingers.values()) / 2.0

            ddx = cx - prev_cx   # positive → fingers moved right
            ddy = cy - prev_cy   # positive → fingers moved down

            # macOS scroll convention (wheel1 = vertical, wheel2 = horizontal):
            #   positive wheel1 → content scrolls up   (fingers moved up → ddy < 0)
            #   positive wheel2 → content scrolls left (fingers moved left → ddx < 0)
            # So: scroll_v = -(ddy * height * scale),  scroll_h = -(ddx * width * scale)
            scroll_v = int(-ddy * self._display_h * SCROLL_SENSITIVITY_V)
            scroll_h = int(-ddx * self._display_w * SCROLL_SENSITIVITY_H)

            phase = (
                kCGScrollEventPhaseBegan
                if self._state != _State.SCROLL
                else kCGScrollEventPhaseChanged
            )
            self._post_scroll(scroll_v, scroll_h, phase=phase)
            log.debug(
                "SCROLL  v=%+d h=%+d  (Δnorm dx=%.4f dy=%.4f)",
                scroll_v, scroll_h, ddx, ddy,
            )

        elif self._state != _State.SCROLL:
            # First scroll frame: open the phase with zero movement
            self._post_scroll(0, 0, phase=kCGScrollEventPhaseBegan)
            log.debug("SCROLL BEGIN")

        self._state = _State.SCROLL
