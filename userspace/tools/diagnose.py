#!/usr/bin/env python3
"""
Diagnostic tool — dumps raw HID reports from the Xeneon Edge touch controller.

Usage:
    python3 tools/diagnose.py

Output shows:
  - All HID interfaces the device exposes
  - Raw bytes from each interface (press Ctrl+C to stop)
  - Colour-coded diffs between reports to help identify live fields

This is the tool to run if you want to contribute a new report format
to parser.py, or if touch isn't working and you need to debug.
"""

import sys
import os
import time
import threading
import struct

# Make sure the package root is on the path when run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import hid
except ImportError:
    print("ERROR: hid not installed. Run: brew install hidapi && pip3 install hid")
    sys.exit(1)

from xeneon_touch.config import VENDOR_ID, PRODUCT_ID, USAGE_PAGE_DIGITIZER

ANSI_RESET  = "\033[0m"
ANSI_GREEN  = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED    = "\033[31m"
ANSI_CYAN   = "\033[36m"
ANSI_BOLD   = "\033[1m"


def list_interfaces():
    print(f"\n{ANSI_BOLD}=== WingCoolTouch interfaces (VID=0x{VENDOR_ID:04X} PID=0x{PRODUCT_ID:04X}) ==={ANSI_RESET}\n")
    found = []
    for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        usage_page = d["usage_page"]
        usage      = d["usage"]
        label = {
            0x01: "Generic Desktop (Mouse/Keyboard)",
            0x0D: "Digitizer ← TOUCH DATA HERE",
            0xFF0A: "Vendor Control",
        }.get(usage_page, f"Unknown (0x{usage_page:04X})")

        color = ANSI_GREEN if usage_page == USAGE_PAGE_DIGITIZER else ANSI_YELLOW
        print(f"  {color}UsagePage=0x{usage_page:04X} ({usage_page:5d})  Usage=0x{usage:02X}  {label}{ANSI_RESET}")
        print(f"    path: {d['path']}")
        print()
        found.append(d)
    if not found:
        print(f"  {ANSI_RED}No device found. Is the Xeneon Edge plugged in via USB-C?{ANSI_RESET}")
    return found


def dump_interface(path: str, usage_page: int, label: str, duration: int = 30):
    print(f"\n{ANSI_BOLD}=== Reading from {label} (usage_page=0x{usage_page:04X}) for {duration}s ==={ANSI_RESET}")
    print("Touch the screen and watch the bytes change.\n")

    try:
        dev = hid.device()
        dev.open_path(path)
        dev.nonblocking = False
    except Exception as e:
        print(f"{ANSI_RED}Could not open device: {e}{ANSI_RESET}")
        print("Try running with sudo, or check that UPDD is not running.\n")
        return

    prev = None
    report_count = 0
    start = time.time()

    try:
        while time.time() - start < duration:
            data = dev.read(64, timeout_ms=50)
            if not data:
                continue

            raw = bytes(data)
            report_count += 1

            # Build hex display with changed bytes highlighted
            parts = []
            for i, b in enumerate(raw):
                if prev and i < len(prev) and prev[i] != b:
                    parts.append(f"{ANSI_GREEN}{b:02X}{ANSI_RESET}")
                else:
                    parts.append(f"{b:02X}")

            ts = time.time() - start
            print(f"  [{ts:6.2f}s] #{report_count:4d}  {' '.join(parts)}")
            prev = raw

    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()

    print(f"\n{ANSI_CYAN}Read {report_count} reports in {time.time()-start:.1f}s{ANSI_RESET}")
    if report_count > 0:
        print(f"\nHint: Report ID is the first byte (dec {prev[0]} / hex 0x{prev[0]:02X})")
        print("      Changed bytes (green) are live data fields.")
        print("      X and Y coordinates appear as 2-byte little-endian pairs.")


def try_parse_as_digitizer(path: str):
    """Quick heuristic parse attempt to show if we can extract X/Y."""
    print(f"\n{ANSI_BOLD}=== Attempting auto-parse of digitizer reports ==={ANSI_RESET}\n")
    try:
        from xeneon_touch.parser import TouchParser
        dev = hid.device()
        dev.open_path(path)
        dev.nonblocking = False
        parser = TouchParser()
        count = 0
        start = time.time()
        while time.time() - start < 15 and count < 100:
            data = dev.read(64, timeout_ms=100)
            if not data:
                continue
            frame = parser.parse(bytes(data))
            if frame:
                active = [c for c in frame.contacts if c.tip_switch]
                if active:
                    c = active[0]
                    print(f"  contact_id={c.contact_id}  "
                          f"x={c.x:5d} ({c.x_norm:.3f})  "
                          f"y={c.y:5d} ({c.y_norm:.3f})  "
                          f"tip={c.tip_switch}")
                    count += 1
        reader2.stop()
        if count == 0:
            print("  No active touch contacts detected in 15s.")
            print("  Try touching the screen, or the report format may need updating.")
    except Exception as e:
        print(f"  {ANSI_RED}Parse error: {e}{ANSI_RESET}")


def main():
    interfaces = list_interfaces()
    if not interfaces:
        sys.exit(1)

    # Find digitizer interface
    digitizer = next((d for d in interfaces if d["usage_page"] == USAGE_PAGE_DIGITIZER), None)
    if digitizer is None:
        print(f"{ANSI_RED}No digitizer interface found. Cannot dump touch data.{ANSI_RESET}")
        sys.exit(1)

    print(f"Touch the Xeneon Edge screen during the next 30 seconds…\n")

    dump_interface(
        path=digitizer["path"],
        usage_page=digitizer["usage_page"],
        label="Digitizer",
        duration=30,
    )

    try_parse_as_digitizer(digitizer["path"])

    print(f"\n{ANSI_BOLD}Done.{ANSI_RESET} If the auto-parse worked, run: python3 -m xeneon_touch\n")


if __name__ == "__main__":
    main()
