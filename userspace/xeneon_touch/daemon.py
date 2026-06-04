"""Main daemon loop."""

import logging
import signal
import sys
import time

from .discovery import find_xeneon_display
from .display import DisplayMapper
from .hid_mouse import HIDMouseReader
from .injector import TouchInjector

log = logging.getLogger(__name__)


class XeneonTouchDaemon:
    def __init__(self):
        self._running  = False
        self._reader   = None
        self._injector = None

    def run(self):
        log.info("xeneon-touch starting…")

        bounds, display_id = find_xeneon_display()
        if bounds is None:
            log.error("Xeneon Edge display not found. Exiting.")
            sys.exit(1)

        log.info("Xeneon Edge display found: %s", bounds)

        mapper   = DisplayMapper(bounds)
        injector = TouchInjector(mapper)

        reader = HIDMouseReader()
        reader.start()

        injector.attach_reader(reader)
        injector.start()

        self._injector = injector
        self._reader   = reader
        self._running  = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

        log.info("Running — touch the Xeneon Edge screen.")

        try:
            while self._running:
                time.sleep(0.5)
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
