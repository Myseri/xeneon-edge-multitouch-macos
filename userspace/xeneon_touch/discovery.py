"""Find the WCH touch controller HID interface and the Xeneon Edge display."""

import hid
import logging
from typing import Optional, Tuple

import Quartz
import AppKit

from .config import (
    VENDOR_ID, PRODUCT_ID,
    TARGET_USAGE_PAGE, TARGET_USAGE,
    DISPLAY_NAME_HINTS, DISPLAY_RESOLUTION,
    DISPLAY_CG_VENDOR, DISPLAY_CG_MODEL,
)

log = logging.getLogger(__name__)


def find_digitizer_path() -> Optional[bytes]:
    """Return the hidapi path for the Touch Screen digitizer interface."""
    found = []
    for device in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        log.debug(
            "Interface: usage_page=0x%02X usage=0x%02X interface=%d path=%s",
            device["usage_page"], device["usage"],
            device["interface_number"], device["path"],
        )
        found.append(device)
        if (device["usage_page"] == TARGET_USAGE_PAGE and
                device["usage"] == TARGET_USAGE):
            log.info(
                "Found Touch Screen digitizer at path %s (interface %d)",
                device["path"], device["interface_number"],
            )
            return device["path"]

    if not found:
        log.error(
            "No WCH touch controller found (VID=0x%04X PID=0x%04X). "
            "Is the Xeneon Edge connected via USB-C?",
            VENDOR_ID, PRODUCT_ID,
        )
    else:
        log.error(
            "Touch controller found but no digitizer interface "
            "(usage_page=0x%02X usage=0x%02X). "
            "Interfaces present: %s",
            TARGET_USAGE_PAGE, TARGET_USAGE,
            [(d["usage_page"], d["usage"]) for d in found],
        )
    return None


def _online_display_ids() -> Tuple[int, ...]:
    """CGGetOnlineDisplayList ids — a live window-server query (always fresh)."""
    try:
        _err, ids, _count = Quartz.CGGetOnlineDisplayList(16, None, None)
        return tuple(ids) if ids else ()
    except Exception as e:  # pragma: no cover
        log.debug("CGGetOnlineDisplayList failed: %s", e)
        return ()


def find_xeneon_display(quiet: bool = False) -> Tuple[Optional[object], Optional[int]]:
    """Return (CGRect frame, CGDirectDisplayID) for the Xeneon Edge, or (None, None).

    Detection is CoreGraphics-first: CG reports each display's hardware identity
    and online status live, whereas NSScreen.screens() caches its list for the
    life of the process and will keep reporting an unplugged display. quiet=True
    downgrades logging to debug for repeated polling (waiting/watching).
    """
    info = log.debug if quiet else log.info
    err  = log.debug if quiet else log.error

    online = _online_display_ids()

    # Primary: match the Edge by CG hardware identity (vendor + model). Fresh.
    for display_id in online:
        if (Quartz.CGDisplayVendorNumber(display_id) == DISPLAY_CG_VENDOR and
                Quartz.CGDisplayModelNumber(display_id) == DISPLAY_CG_MODEL):
            frame = Quartz.CGDisplayBounds(display_id)
            info(
                "Found Xeneon Edge (CG vendor=%s model=%s) id=%s "
                "origin=(%.0f,%.0f) size=%.0fx%.0f",
                DISPLAY_CG_VENDOR, DISPLAY_CG_MODEL, display_id,
                frame.origin.x, frame.origin.y, frame.size.width, frame.size.height,
            )
            return frame, display_id

    # Fallback: NSScreen name match, but only accept it if CG confirms that
    # display is actually online right now (NSScreen's list may be stale).
    for screen in AppKit.NSScreen.screens():
        name = str(screen.localizedName()) if hasattr(screen, "localizedName") else ""
        for hint in DISPLAY_NAME_HINTS:
            if hint.upper() in name.upper():
                display_id = _nsscreen_to_cgdisplay(screen)
                if display_id not in online:
                    continue   # stale NSScreen entry — not really connected
                frame = Quartz.CGDisplayBounds(display_id)
                info(
                    "Found Xeneon Edge by name '%s' id=%s "
                    "origin=(%.0f,%.0f) size=%.0fx%.0f",
                    name, display_id,
                    frame.origin.x, frame.origin.y, frame.size.width, frame.size.height,
                )
                return frame, display_id

    err(
        "Xeneon Edge display not found (CG vendor=%s model=%s; name hints=%s).",
        DISPLAY_CG_VENDOR, DISPLAY_CG_MODEL, DISPLAY_NAME_HINTS,
    )
    return None, None


def _nsscreen_to_cgdisplay(screen) -> int:
    desc       = screen.deviceDescription()
    display_id = desc.get("NSScreenNumber")
    return int(display_id) if display_id is not None else 0
