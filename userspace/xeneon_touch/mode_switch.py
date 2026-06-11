"""
Send HID feature reports to switch Xeneon Edge touch controller to multitouch mode.

Feature reports (Interface 0, digitizer):
  0x21  Input Mode = 2 (multitouch), Device ID = 0
  0x0A  Max Contacts = 10
"""

import logging
import time

try:
    import hid as _hid
except ImportError:
    _hid = None

from .config import VID, PID, USAGE_PAGE_DIGITIZER

log = logging.getLogger(__name__)


def send_mode_switch() -> bool:
    """
    Open the digitizer HID interface and send the two mode-switch feature
    reports.  Returns True if both reports were sent without error.

    Requires hidapi: pip install hidapi
    """
    if _hid is None:
        log.error("hidapi not installed — run: pip install hidapi")
        return False

    path = _find_digitizer_path()
    if path is None:
        log.error(
            "Digitizer interface not found (VID=0x%04X PID=0x%04X "
            "usage_page=0x%04X) — is the Xeneon Edge connected?",
            VID, PID, USAGE_PAGE_DIGITIZER,
        )
        return False

    dev = _hid.device()
    try:
        dev.open_path(path)
    except Exception as exc:
        log.error("Failed to open digitizer HID path %s: %s", path, exc)
        return False

    ok = True
    try:
        # Report 0x21: Input Mode = 2 (multitouch), Device ID = 0
        # Try both 3-byte and 2-byte payloads; some WCH firmware variants
        # only accept the 2-byte form (report_id + mode, no device_id byte).
        sent_21 = False
        for payload in ([0x21, 0x02, 0x00], [0x21, 0x02]):
            try:
                r = dev.send_feature_report(payload)
                if r > 0:
                    log.info(
                        "Feature report 0x21 (Input Mode=2, %d bytes): sent ✓  (ret=%d)",
                        len(payload), r,
                    )
                    sent_21 = True
                    break
            except Exception as exc:
                log.debug("send_feature_report 0x21 %d-byte attempt: %s",
                          len(payload), exc)
        if not sent_21:
            log.warning("Feature report 0x21 failed on all payload lengths")
            ok = False

        # Report 0x0A: Max Contacts = 10
        r = dev.send_feature_report([0x0A, 0x0A])
        if r > 0:
            log.info("Feature report 0x0A (Max Contacts=10): sent ✓  (ret=%d)", r)
        else:
            log.warning("Feature report 0x0A returned %d", r)
            ok = False

        # Read back 0x21 to confirm mode was accepted.
        # macOS hidapi prepends 0xa1 to feature-report read responses, so
        # the layout is [0xa1, mode, device_id] not [report_id, mode, device_id].
        try:
            resp = dev.get_feature_report(0x21, 4)
            raw = bytes(resp).hex(" ")
            if resp and resp[0] == 0xa1:
                mode = resp[1] if len(resp) > 1 else "?"
            else:
                mode = resp[1] if len(resp) > 1 else "?"
            log.info(
                "Read-back 0x21: %s  (Input Mode=%s%s)",
                raw, mode,
                " ✓" if mode == 2 else " — expected 2; device may need replug to apply"
            )
        except Exception as exc:
            log.debug("Read-back 0x21 failed (non-fatal): %s", exc)

    except Exception as exc:
        log.error("Feature report error: %s", exc)
        ok = False
    finally:
        dev.close()

    if ok:
        # Give the controller a moment to switch modes before we start reading
        time.sleep(0.15)

    return ok


def _find_digitizer_path() -> bytes | None:
    """
    Return the hidapi path best suited for sending feature reports 0x21/0x0A.

    Interface 0 exposes three HID top-level collections:
      usage_page=0x0D, usage=0x04  — Touch Screen (input reports)
      usage_page=0x0D, usage=0x0E  — Configuration (feature reports 0x21, 0x0A)  ← want this
      usage_page=0x0D, usage=0x22  — Finger (individual contact sub-reports)

    hidapi enumerates each collection as a separate "device".  We prefer the
    Configuration collection (usage=0x0E) because that's where the Input Mode
    and Max Contacts feature reports live per the HID digitizer spec.
    """
    if _hid is None:
        return None

    devices = _hid.enumerate(VID, PID)
    if not devices:
        return None

    # Log all found paths for debugging
    for d in devices:
        log.debug(
            "HID path: usage_page=0x%04X usage=0x%04X iface=%s path=%s",
            d.get("usage_page", 0), d.get("usage", 0),
            d.get("interface_number", "?"), d["path"],
        )

    # 1st preference: Configuration collection (usage_page=0x0D, usage=0x0E)
    for d in devices:
        if d.get("usage_page") == 0x000D and d.get("usage") == 0x000E:
            log.debug("Using Configuration collection path: %s", d["path"])
            return d["path"]

    # 2nd preference: any digitizer usage page
    for d in devices:
        if d.get("usage_page") == USAGE_PAGE_DIGITIZER:
            log.debug("Using first digitizer path: %s", d["path"])
            return d["path"]

    # Last resort: first path found
    log.debug("Falling back to first available path: %s", devices[0]["path"])
    return devices[0]["path"]
