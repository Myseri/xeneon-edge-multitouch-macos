"""
Parse raw HID digitizer reports from the WingCoolTouch controller.

The Xeneon Edge uses a standard HID Digitizer descriptor (Usage Page 0x0D).
Because hid.is_auto=1 in UPDD, the device self-describes via its HID report
descriptor. This parser handles the common WingCoolTouch multitouch format,
which follows the Windows Precision Touchpad / HID Digitizer spec.

Run `python3 tools/diagnose.py` with the monitor connected to dump raw reports
if you need to reverse-engineer the exact layout for a firmware variant.
"""

import struct
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .config import TOUCH_X_MAX, TOUCH_Y_MAX

log = logging.getLogger(__name__)


@dataclass
class TouchContact:
    contact_id: int = 0
    x: int = 0            # raw, 0..TOUCH_X_MAX
    y: int = 0            # raw, 0..TOUCH_Y_MAX
    tip_switch: bool = False   # True = finger down
    in_range: bool = False

    @property
    def x_norm(self) -> float:
        """Normalised X coordinate, 0.0 (left) .. 1.0 (right)."""
        return self.x / TOUCH_X_MAX

    @property
    def y_norm(self) -> float:
        """Normalised Y coordinate, 0.0 (top) .. 1.0 (bottom)."""
        return self.y / TOUCH_Y_MAX


@dataclass
class TouchFrame:
    contacts: List[TouchContact] = field(default_factory=list)
    contact_count: int = 0   # as reported by device


# ---------------------------------------------------------------------------
# Format registry — keyed by (report_id, bytes_per_contact, contacts_per_report)
# We try each in order and pick the first that parses cleanly.
# Populated automatically by the auto-detect routine below.
# ---------------------------------------------------------------------------

class ReportFormat:
    """Describes the binary layout of one HID touch report."""
    def __init__(self, report_id, contacts_per_report,
                 contact_size, x_offset, y_offset,
                 status_offset, id_offset, count_offset,
                 x_max=32767, y_max=32767):
        self.report_id          = report_id
        self.contacts_per_report = contacts_per_report
        self.contact_size       = contact_size
        self.x_offset           = x_offset     # within contact block
        self.y_offset           = y_offset
        self.status_offset      = status_offset
        self.id_offset          = id_offset
        self.count_offset       = count_offset  # absolute offset in report
        self.x_max              = x_max
        self.y_max              = y_max

    def parse(self, data: bytes) -> Optional[TouchFrame]:
        if not data or data[0] != self.report_id:
            return None
        frame = TouchFrame()
        for i in range(self.contacts_per_report):
            base = 1 + i * self.contact_size  # skip report-id byte
            if base + self.contact_size > len(data):
                break
            block = data[base:]
            status = block[self.status_offset]
            tip = bool(status & 0x01)
            in_range = bool(status & 0x02)
            cid = block[self.id_offset]
            x = struct.unpack_from('<H', block, self.x_offset)[0]
            y = struct.unpack_from('<H', block, self.y_offset)[0]
            frame.contacts.append(TouchContact(
                contact_id=cid, x=x, y=y,
                tip_switch=tip, in_range=in_range,
            ))
        if self.count_offset < len(data):
            frame.contact_count = data[self.count_offset]
        else:
            frame.contact_count = sum(1 for c in frame.contacts if c.tip_switch)
        return frame


# Common WingCoolTouch layouts (ordered by likelihood)
KNOWN_FORMATS = [
    # Format A: report_id=1, 6 bytes/contact [status, id, x_lo, x_hi, y_lo, y_hi], up to 10 contacts
    # contact_count byte follows last contact
    ReportFormat(
        report_id=1, contacts_per_report=10,
        contact_size=6,
        status_offset=0, id_offset=1,
        x_offset=2, y_offset=4,
        count_offset=61,   # 1 + 10*6 = 61
    ),
    # Format B: report_id=2, same layout
    ReportFormat(
        report_id=2, contacts_per_report=10,
        contact_size=6,
        status_offset=0, id_offset=1,
        x_offset=2, y_offset=4,
        count_offset=61,
    ),
    # Format C: report_id=1, 5 contacts, 8 bytes each [status, id, x(2), y(2), w(2)]
    ReportFormat(
        report_id=1, contacts_per_report=5,
        contact_size=8,
        status_offset=0, id_offset=1,
        x_offset=2, y_offset=4,
        count_offset=41,
    ),
]


class TouchParser:
    """
    Auto-detecting HID report parser.

    On first reports it tries all known formats. Once it finds one that
    produces plausible contact data it locks in. Falls back to raw dump
    if nothing matches.
    """

    def __init__(self):
        self._fmt: Optional[ReportFormat] = None
        self._candidates = list(KNOWN_FORMATS)
        self._raw_log_count = 0

    def parse(self, data: bytes) -> Optional[TouchFrame]:
        if not data:
            return None

        # Already locked to a format
        if self._fmt is not None:
            frame = self._fmt.parse(data)
            if frame is not None:
                return frame
            # Format stopped working — re-detect (firmware update?)
            log.warning("Active format stopped matching, re-detecting…")
            self._fmt = None
            self._candidates = list(KNOWN_FORMATS)

        # Auto-detect phase
        for fmt in list(self._candidates):
            frame = fmt.parse(data)
            if frame and self._plausible(frame):
                log.info(
                    "Locked to report format: id=%d contact_size=%d",
                    fmt.report_id, fmt.contact_size,
                )
                self._fmt = fmt
                return frame

        # Nothing matched — log raw bytes (first 20 reports only)
        if self._raw_log_count < 20:
            log.debug("Unknown report [%d bytes]: %s", len(data), data[:32].hex())
            self._raw_log_count += 1
        return None

    @staticmethod
    def _plausible(frame: TouchFrame) -> bool:
        """Sanity-check a parsed frame."""
        if not frame.contacts:
            return False
        for c in frame.contacts:
            if c.tip_switch and (c.x > 32767 or c.y > 32767):
                return False
        return True
