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


def find_xeneon_display() -> Tuple[Optional[object], Optional[int]]:
    """Return (NSRect frame, CGDirectDisplayID) for the Xeneon Edge display."""
    # Name-based detection (macOS 10.15+)
    for screen in AppKit.NSScreen.screens():
        name = str(screen.localizedName()) if hasattr(screen, "localizedName") else ""
        for hint in DISPLAY_NAME_HINTS:
            if hint.upper() in name.upper():
                display_id = _nsscreen_to_cgdisplay(screen)
                # Use CGDisplayBounds — same coordinate system as CGWarpMouseCursorPosition
                frame      = Quartz.CGDisplayBounds(display_id)
                log.info(
                    "Found Xeneon Edge: '%s' id=%s origin=(%.0f,%.0f) size=%.0fx%.0f",
                    name, display_id,
                    frame.origin.x, frame.origin.y,
                    frame.size.width, frame.size.height,
                )
                return frame, display_id

    # Resolution fallback
    log.warning(
        "Display name match failed, falling back to %dx%d",
        *DISPLAY_RESOLUTION,
    )
    _, display_list = Quartz.CGGetOnlineDisplayList(16, None, None)
    for display_id in display_list:
        bounds = Quartz.CGDisplayBounds(display_id)
        if (int(bounds.size.width), int(bounds.size.height)) == DISPLAY_RESOLUTION:
            log.info("Found %dx%d display id=%s", *DISPLAY_RESOLUTION, display_id)
            return bounds, display_id

    log.error(
        "Could not find Xeneon Edge display. "
        "Hints tried: %s, fallback resolution: %dx%d",
        DISPLAY_NAME_HINTS, *DISPLAY_RESOLUTION,
    )
    return None, None


def _nsscreen_to_cgdisplay(screen) -> int:
    desc       = screen.deviceDescription()
    display_id = desc.get("NSScreenNumber")
    return int(display_id) if display_id is not None else 0
