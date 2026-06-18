"""
Adapter: present the single-touch HIDMouseReader to the injector using the
same frame API the injector already expects from IOHIDEventReader — a list of
TouchContact objects.

Why this exists: on macOS the WCH controller only streams touch data on the
interface-2 "mouse" endpoint (absolute X/Y, report 0x07). The multitouch
digitizer on interface 0 is firmware-gated and never emits a report, so the
IOHIDEventSystemClient digitizer path receives nothing. Reading interface 2
via hidapi needs no Input Monitoring permission and is the only path that
carries data on this device under macOS.

Single-touch only by nature: interface 2 reports one absolute point, so this
yields at most one contact per frame. The injector's two-finger scroll branch
simply never triggers.
"""

import logging
from typing import List, Optional

from .hid_mouse import HIDMouseReader
from .event_reader import TouchContact

log = logging.getLogger(__name__)


class MouseFrameReader:
    """Wraps HIDMouseReader and emits injector-compatible frames."""

    def __init__(self, vendor_id: int = None, product_id: int = None):
        # VID/PID accepted only for call-signature parity with IOHIDEventReader;
        # HIDMouseReader locates the device by enumeration.
        self._mouse = HIDMouseReader()

    def start(self) -> None:
        self._mouse.start()

    def stop(self) -> None:
        self._mouse.stop()

    def alive(self) -> bool:
        return self._mouse.alive()

    def read(self, timeout: float = 0.05) -> Optional[List[TouchContact]]:
        rpt = self._mouse.read(timeout=timeout)
        if rpt is None:
            return None
        if not rpt.touch:
            return []          # finger lifted → 0 active contacts → injector lifts
        return [
            TouchContact(
                x=rpt.x_norm,          # already normalised 0..1
                y=rpt.y_norm,
                tip_switch=True,
                contact_id=0,
            )
        ]
