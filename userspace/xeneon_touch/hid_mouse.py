"""
HID mouse interface reader for the WCH touch controller.

Opens Interface 2 (UsagePage=0x0001, Usage=0x0002) with shared access —
no exclusive lock. Enumerated dynamically so the path doesn't need to be
hard-coded (DevSrvsID:... changes on every reconnect).

Report format (7 bytes, Report ID 0x07):
  [0] 0x07        — Report ID
  [1] buttons     — bit 0 = touch down (1) / lifted (0)
  [2] x_lo        ┐
  [3] x_hi        ┘ 16-bit LE, range 0–16383
  [4] y_lo        ┐
  [5] y_hi        ┘ 16-bit LE, range 0–9599
  [6] wheel       — signed 8-bit, usually 0
"""

import threading
import queue
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

try:
    import hid
except ImportError:
    raise ImportError("pip install hidapi") from None

from .config import VID, PID, TOUCH_X_MAX, TOUCH_Y_MAX

# Mouse interface identifiers
_MOUSE_USAGE_PAGE = 0x0001
_MOUSE_USAGE      = 0x0002
_REPORT_ID        = 0x07


@dataclass
class MouseTouchReport:
    x_raw:  int    # 0–TOUCH_X_MAX
    y_raw:  int    # 0–TOUCH_Y_MAX
    touch:  bool   # True = finger down

    @property
    def x_norm(self) -> float:
        return self.x_raw / TOUCH_X_MAX

    @property
    def y_norm(self) -> float:
        return self.y_raw / TOUCH_Y_MAX


def find_mouse_path() -> Optional[bytes]:
    """Return the hidapi path for the WCH mouse interface, or None."""
    for d in hid.enumerate(VID, PID):
        if (d['usage_page'] == _MOUSE_USAGE_PAGE and
                d['usage'] == _MOUSE_USAGE):
            return d['path']
    return None


class HIDMouseReader:
    """
    Reads touch reports from Interface 2 in a background thread.

    The path is re-enumerated on every open so reconnects are handled cleanly.
    """

    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="HIDMouseReader")
        self._thread.start()

    def stop(self):
        self._running = False

    def alive(self) -> bool:
        """True while the read thread is running (False once the device drops)."""
        return self._thread is not None and self._thread.is_alive()

    def read(self, timeout: float = 0.05) -> Optional[MouseTouchReport]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        path = find_mouse_path()
        if not path:
            log.error("WCH mouse interface not found — "
                      "is the Xeneon Edge connected?")
            return

        log.info("Opening HID mouse interface at %s", path)
        dev = hid.device()
        try:
            dev.open_path(path)
        except OSError as e:
            log.error("Cannot open mouse interface %s: %s", path, e)
            return

        dev.set_nonblocking(True)
        log.info("HIDMouseReader running — VID=0x%04X PID=0x%04X", VID, PID)

        last_touch = False
        while self._running:
            try:
                data = dev.read(16)
            except (OSError, ValueError) as e:
                # Device went away (monitor unplugged) — exit cleanly; the
                # daemon's supervisor will notice and wait for reconnect.
                log.info("Mouse interface read ended (%s) — device gone?", e)
                break
            if not data:
                time.sleep(0.001)
                continue

            raw = bytes(data)
            if len(raw) < 6 or raw[0] != _REPORT_ID:
                continue

            touch = bool(raw[1] & 0x01)
            x_raw = raw[2] | (raw[3] << 8)
            y_raw = raw[4] | (raw[5] << 8)

            # Clamp (sanity)
            x_raw = max(0, min(x_raw, TOUCH_X_MAX))
            y_raw = max(0, min(y_raw, TOUCH_Y_MAX))

            # Only queue state changes or movement while touching
            if touch or last_touch:
                report = MouseTouchReport(x_raw=x_raw, y_raw=y_raw, touch=touch)
                try:
                    self._q.put_nowait(report)
                except queue.Full:
                    pass

            last_touch = touch

        try:
            dev.close()
        except Exception:
            pass
        log.info("HIDMouseReader stopped.")
