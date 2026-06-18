"""Main daemon — a single long-lived supervisor.

Rather than exiting when the Xeneon Edge is absent (which made the LaunchAgent
relaunch us every few seconds, blinking the Dock icon), we stay running and
poll for the display. When it appears we run a touch session; when it
disconnects we tear the session down and go back to waiting — all in one
process, so the agent never has to restart us.
"""

import logging
import signal
import time

from .config import VID, PID
from .discovery import find_xeneon_display
from .display import DisplayMapper
from .mouse_frame_reader import MouseFrameReader
from .hid_mouse import find_mouse_path
from .injector import TouchInjector
from .mode_switch import send_mode_switch
from .permissions import ensure_accessibility

log = logging.getLogger(__name__)

_WAIT_POLL_S   = 3.0   # how often to look while the Edge is disconnected
_WATCH_POLL_S  = 2.0   # how often to confirm the Edge is still present while running
_HID_WAIT_S    = 6.0   # max wait for the touch USB interface after a hot-plug
_HID_SETTLE_S  = 0.6   # let enumeration settle before opening
_RETRY_PACE_S  = 2.0   # backoff before re-establishing a session


class XeneonTouchDaemon:
    def __init__(self):
        self._running = False

    def run(self):
        log.info("xeneon-touch starting…")

        # Request Accessibility once up front. The cursor warps without it, but
        # clicks/drags are dropped until it's granted.
        ensure_accessibility(prompt=True)

        self._running = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

        while self._running:
            bounds = self._wait_for_display()
            if not self._running or bounds is None:
                continue
            self._run_session(bounds)
            # If we left the session while the Edge is still connected, the
            # reader died (vs. a clean unplug) — pace the retry so we don't spin.
            if self._running:
                still_here, _ = find_xeneon_display(quiet=True)
                if still_here is not None:
                    time.sleep(_RETRY_PACE_S)

        log.info("Done.")

    def _wait_for_hid(self) -> bool:
        """Wait for the touch USB interface to enumerate after a hot-plug.

        On reconnect the display reappears a beat before USB finishes
        enumerating, so opening immediately grabs a half-ready device that drops
        a second later. Poll for the mouse interface, then let it settle.
        """
        deadline = time.time() + _HID_WAIT_S
        while self._running and time.time() < deadline:
            try:
                if find_mouse_path() is not None:
                    time.sleep(_HID_SETTLE_S)
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    # ── supervisor helpers ───────────────────────────────────────────────────

    def _wait_for_display(self):
        """Poll quietly until the Edge appears, or we're shutting down."""
        bounds, _ = find_xeneon_display(quiet=True)
        if bounds is not None:
            return bounds

        log.info("Xeneon Edge not connected — waiting…")
        while self._running:
            time.sleep(_WAIT_POLL_S)
            bounds, _ = find_xeneon_display(quiet=True)
            if bounds is not None:
                log.info("Xeneon Edge connected.")
                return bounds
        return None

    def _run_session(self, bounds):
        """Run one connected session until the Edge disconnects or we shut down."""
        log.info("Xeneon Edge display found: %s", bounds)

        if not self._wait_for_hid():
            log.info("Touch USB interface not ready yet — will retry.")
            return

        log.info("Sending mode switch (Input Mode=2, Max Contacts=10)…")
        if not send_mode_switch():
            log.warning("Mode switch failed — continuing in single-touch mode.")

        mapper   = DisplayMapper(bounds)
        reader   = MouseFrameReader(VID, PID)
        injector = TouchInjector(mapper)

        reader.start()
        injector.attach_reader(reader)
        injector.start()

        log.info("Running — touch the Xeneon Edge screen.")
        try:
            while self._running:
                time.sleep(_WATCH_POLL_S)
                present, _ = find_xeneon_display(quiet=True)
                if present is None:
                    log.info("Xeneon Edge disconnected — waiting for it to return.")
                    break
                if not reader.alive():
                    log.info("Touch reader stopped while still connected — "
                             "re-establishing session.")
                    break
        finally:
            injector.stop()
            reader.stop()

    def _handle_signal(self, signum, frame):
        log.info("Signal %d — shutting down…", signum)
        self._running = False
