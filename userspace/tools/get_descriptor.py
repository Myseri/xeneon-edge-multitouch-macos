#!/usr/bin/env python3
"""
Read the HID report descriptor from Interface 2 (mouse, path DevSrvsID:4295057798).
The descriptor tells us the exact logical X/Y min/max so we can scale correctly.

Also tries to read the Interface 0 (digitizer) descriptor from IORegistry
without opening it — IORegistry properties are readable without device access.

Run: python3 tools/get_descriptor.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

VID = 0x27C0
PID = 0x0859

# ── parse HID descriptor ────────────────────────────────────────────────────
GLOBAL_TAGS = {
    0x04: "Usage Page", 0x14: "Logical Min", 0x24: "Logical Max",
    0x34: "Physical Min", 0x44: "Physical Max", 0x54: "Unit Exp",
    0x64: "Unit", 0x74: "Report Size", 0x84: "Report ID",
    0x94: "Report Count",
}
LOCAL_TAGS  = {0x08: "Usage", 0x18: "Usage Min", 0x28: "Usage Max"}
MAIN_TAGS   = {0xA0: "Collection", 0xC0: "End Collection",
               0x80: "Input", 0x90: "Output", 0xB0: "Feature"}

def _signed(v, size):
    if size == 1 and v >= 0x80: return v - 0x100
    if size == 2 and v >= 0x8000: return v - 0x10000
    return v

def parse_descriptor(raw: bytes):
    """Minimal HID descriptor parser — extracts usages and logical ranges."""
    items = []
    i = 0
    state = {}
    while i < len(raw):
        b = raw[i]
        tag  = b & 0xFC
        size = b & 0x03
        if size == 3: size = 4
        val = 0
        for j in range(size):
            val |= raw[i + 1 + j] << (j * 8)
        signed_val = _signed(val, size)
        i += 1 + size

        label = (GLOBAL_TAGS.get(tag) or LOCAL_TAGS.get(tag) or
                 MAIN_TAGS.get(tag & 0xFC) or f"0x{tag:02X}")
        items.append((label, val, signed_val))

    return items

def format_items(items):
    indent = 0
    for label, val, sval in items:
        if label == "End Collection":
            indent = max(0, indent - 2)
        line = " " * indent + f"{label}: "
        if label == "Usage Page":
            pages = {1:"Generic Desktop", 13:"Digitizer", 0x0D:"Digitizer",
                     0xFF0A:"Vendor"}
            line += pages.get(val, f"0x{val:04X}")
        elif label in ("Usage", "Usage Min", "Usage Max"):
            usages = {0x01:"Pointer/Joystick", 0x02:"Mouse", 0x04:"Joystick",
                      0x30:"X", 0x31:"Y", 0x32:"Z", 0x38:"Wheel",
                      0x04:"Touch Screen", 0x22:"Finger",
                      0x30:"X", 0x31:"Y"}
            line += usages.get(val, f"0x{val:04X}")
        elif label in ("Logical Min", "Logical Max"):
            line += f"{sval}  (0x{val:X})"
        elif label == "Collection":
            colls = {0:"Physical", 1:"Application", 2:"Logical"}
            line += colls.get(val, str(val))
        elif label == "Report ID":
            line += f"0x{val:02X} ({val})"
        else:
            line += f"{val}"
        print(line)
        if label == "Collection":
            indent += 2

def main():
    devs = hid.enumerate(VID, PID)
    if not devs:
        sys.exit("WCH device not found")

    # Try each distinct path
    seen = set()
    for d in devs:
        path = d['path']
        if path in seen:
            continue
        seen.add(path)

        dev = hid.device()
        try:
            dev.open_path(path)
        except Exception as e:
            print(f"\n── path={path}  iface={d['interface_number']}: "
                  f"CANNOT OPEN ({e})")
            continue

        try:
            desc = bytes(dev.get_report_descriptor())
            print(f"\n── path={path}  iface={d['interface_number']}  "
                  f"usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:04X}  "
                  f"({len(desc)} bytes)")
            print("  Raw:", desc.hex())
            print()
            items = parse_descriptor(desc)
            format_items(items)
        except Exception as e:
            print(f"  get_report_descriptor failed: {e}")
        finally:
            dev.close()

if __name__ == "__main__":
    main()
