"""Main daemon loop."""

import logging
import signal
import sys
import time
from typing import Optional

from .config import VID, PID, TOUCH_X_MAX, TOUCH_Y_MAX
from .discovery import find_xeneon_display
from .event_reader import IOHIDEventReader, TouchContact
from .display import DisplayMapper
from .injector import TouchInjector

log = logging.getLogger(__name__)


def _normalise(contact: TouchContact) -> TouchContact:
    """
    Convert raw IOHIDEvent X/Y to 0.0–1.0 normalised coords.

    IOHIDEventGetFloatValue for digitizer X/Y can return:
      - 0.0–1.0  (already normalised — macOS >= 12 for some drivers)
      - 0–32767  (logical units from the HID report descriptor)

    We detect which case we're in and normalise accordingly.
    """
    x, y = contact.x, contact.y
    # If values are > 1.0 they must be logical units
    if x > 1.0 or y > 1.0:
        x = max(0.0, min(1.0, x / TOUCH_X_MAX))
        y = max(0.0, min(1.0, y / TOUCH_Y_MAX))
    return TouchContact(x=x, y=y,
                        tip_switch=contact.tip_switch,
                        contact_id=contact.contact_id)


class XeneonTouchDaemon:
    def __init__(self):
        self._running  = False
        self._reader: Optional[IOHIDEventReader] = None
        self._injector: Optional[TouchInjector]  = None

    def run(self):
        log.info("xeneon-touch starting…")

        bounds, display_id = find_xeneon_display()
        if bounds is None:
            log.error("Xeneon Edge display not found. Exiting.")
            sys.exit(1)

        mapper   = DisplayMapper(bounds)
        injector = TouchInjector(mapper)

        try:
            injector.start()
        except PermissionError as e:
            log.error("%s", e)
            sys.exit(1)

        self._injector = injector

        reader = IOHIDEventReader(vendor_id=VID, product_id=PID)
        reader.start()
        self._reader = reader

        self._running = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

        log.info("Running — touch the Xeneon Edge screen to test.")

        try:
            while self._running:
                contacts = reader.read(timeout=0.05)
                if not contacts:
                    continue

                # Pick the primary (first active) finger
                active = next(
                    (_normalise(c) for c in contacts if c.tip_switch), None)
                injector.update_touch(active)

        finally:
            self._cleanup()

    def _handle_signal(self, signum, frame):
        log.info("Signal %d — shutting down…", signum)
        self._running = False

    def _cleanup(self):
        log.info("Cleaning up…")
        if self._injector:
            self._injector.stop()
        if self._reader:
            self._reader.stop()
        log.info("Done.")
