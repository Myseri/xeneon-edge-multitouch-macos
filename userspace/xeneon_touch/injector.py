"""
Inject pointer events into macOS using CGEvent.

Strategy
--------
The WingCoolTouch mouse interface already generates relative mouse events,
which land on whatever monitor is currently "active" — the wrong screen.

We use a CGEventTap to intercept those mouse events from the specific device
and replace their position with the absolute coordinates from our digitizer
parser, mapped to the Xeneon Edge display.

Requires Accessibility permission (System Settings → Privacy → Accessibility).
"""

import logging
import threading
import time
from typing import Optional

import Quartz
from Quartz import (
    CGEventTapCreate, CGEventTapEnable,
    CGEventCreateMouseEvent, CGEventSetLocation,
    CGEventPost, CGEventGetType, CGEventGetLocation,
    kCGEventMouseMoved, kCGEventLeftMouseDown,
    kCGEventLeftMouseUp, kCGEventRightMouseDown,
    kCGEventRightMouseUp, kCGHIDEventTap,
    kCGHeadInsertEventTap, kCGEventTapOptionDefault,
    CGEventMaskBit, CGEventGetIntegerValueField,
    kCGMouseEventSubtype,
    CGRunLoopSourceCreate, CFRunLoopAddSource,
    CFRunLoopGetCurrent, CFRunLoopRun, CFRunLoopStop,
    kCFRunLoopDefaultMode,
)

from .display import DisplayMapper
from .parser import TouchContact

log = logging.getLogger(__name__)

# CGEvent field for device ID — lets us filter by which device generated it
kCGEventSourceUnixProcessID = 41
kCGMouseEventWindowUnderMousePointer = 62


class TouchInjector:
    """
    Intercepts mouse events from the WingCoolTouch device and remaps
    their position to the Xeneon Edge display.
    """

    def __init__(self, mapper: DisplayMapper):
        self.mapper = mapper
        self._last_point: Optional[Quartz.CGPoint] = None
        self._last_touch_time: float = 0.0
        self._tap = None
        self._loop = None
        self._thread: Optional[threading.Thread] = None
        self._active = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_touch(self, contact: Optional[TouchContact]):
        """Called by the HID reader thread whenever a touch event arrives."""
        if contact is None or not contact.tip_switch:
            self._last_point = None
            return
        self._last_point = self.mapper.to_screen(contact.x_norm, contact.y_norm)
        self._last_touch_time = time.monotonic()

    def start(self):
        """Install event tap and start run-loop thread."""
        mask = (
            CGEventMaskBit(kCGEventMouseMoved)     |
            CGEventMaskBit(kCGEventLeftMouseDown)  |
            CGEventMaskBit(kCGEventLeftMouseUp)    |
            CGEventMaskBit(kCGEventRightMouseDown) |
            CGEventMaskBit(kCGEventRightMouseUp)
        )

        self._tap = CGEventTapCreate(
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            self._tap_callback,
            None,
        )

        if self._tap is None:
            raise PermissionError(
                "Could not create CGEventTap. "
                "Grant Accessibility permission to this terminal / Python in "
                "System Settings → Privacy & Security → Accessibility, then restart."
            )

        self._active = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("Event tap installed.")

    def stop(self):
        self._active = False
        if self._tap:
            CGEventTapEnable(self._tap, False)
        if self._loop:
            CFRunLoopStop(self._loop)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self):
        source = CGRunLoopSourceCreate(None, 0, self._tap)
        self._loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._loop, source, kCFRunLoopDefaultMode)
        CGEventTapEnable(self._tap, True)
        CFRunLoopRun()

    def _tap_callback(self, proxy, event_type, event, user_info):
        """
        Called for every intercepted CGEvent on the HID event tap.
        If we have a recent touch position, replace the event location.
        """
        if not self._active:
            return event

        point = self._last_point
        if point is None:
            return event

        # Only remap if touch was recent (avoids stale remap after finger lifts)
        age = time.monotonic() - self._last_touch_time
        if age > 0.15:  # 150 ms
            return event

        CGEventSetLocation(event, point)
        return event
