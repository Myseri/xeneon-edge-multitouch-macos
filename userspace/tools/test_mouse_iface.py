#!/usr/bin/env python3
"""
Try to open the WCH mouse interface (Interface 2, UsagePage=1 Usage=2)
directly with hidapi and dump raw HID reports.

The digitizer interface (Interface 0) is exclusively locked by
AppleUserHIDDevice, but the mouse interface may allow shared access.
If we can read Interface 2 raw reports, we'll see the full multi-touch
contact bytes that macOS currently discards.

Run: python3 tools/test_mouse_iface.py
Then touch the screen (single and multiple fingers) for 15 seconds.
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import hid
except ImportError:
    sys.exit("pip install hidapi")

VID = 0x27C0
PID = 0x0859

def dump_report(prefix: str, data: bytes):
    hex_str = " ".join(f"{b:02X}" for b in data)
    print(f"{prefix}  [{len(data):2d}]  {hex_str}")

def try_open_path(path: bytes) -> bool:
    """Try to open a device path. Returns True if successful."""
    dev = hid.device()
    try:
        dev.open_path(path)
        return True, dev
    except Exception as e:
        return False, str(e)

def main():
    print(f"Enumerating VID=0x{VID:04X} PID=0x{PID:04X} ...\n")

    all_devs = hid.enumerate(VID, PID)
    if not all_devs:
        sys.exit("No WCH devices found.")

    for d in all_devs:
        print(f"  path={d['path']}  iface={d['interface_number']}"
              f"  usage_page=0x{d['usage_page']:04X}  usage=0x{d['usage']:04X}"
              f"  manufacturer='{d['manufacturer_string']}'")

    # Find mouse interface (UsagePage=1, Usage=2)
    mouse_iface = [d for d in all_devs
                   if d['usage_page'] == 0x0001 and d['usage'] == 0x0002]
    # Also try UsagePage=1 Usage=1 (Pointer)
    pointer_iface = [d for d in all_devs
                     if d['usage_page'] == 0x0001 and d['usage'] == 0x0001]

    targets = mouse_iface + pointer_iface
    if not targets:
        print("\nNo mouse/pointer interface found — trying all interfaces")
        targets = all_devs

    print(f"\nWill try {len(targets)} interface(s):\n")

    for d in targets:
        path = d['path']
        print(f"Trying iface={d['interface_number']} "
              f"usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:04X} ...")

        ok, result = try_open_path(path)
        if not ok:
            print(f"  FAILED: {result}\n")
            continue

        dev = result
        dev.set_nonblocking(True)
        print(f"  OPENED! Reading for 15 seconds — touch the screen ...\n")

        deadline = time.monotonic() + 15.0
        last_report = None
        count = 0

        while time.monotonic() < deadline:
            data = dev.read(64)
            if not data:
                time.sleep(0.002)
                continue

            raw = bytes(data)
            count += 1

            # Show first report in full
            if count == 1:
                print(f"  First report (will show all changed bytes):")
                dump_report("  FIRST:", raw)
                last_report = raw

            # Subsequent: show only if different from last
            elif raw != last_report:
                changed = []
                for i, (a, b) in enumerate(zip(raw, last_report)):
                    if a != b:
                        changed.append(f"[{i}]:{b:02X}→{a:02X}")
                prefix = f"  [{count:4d}] chg:" + " ".join(changed) + "  "
                dump_report(prefix, raw)
                last_report = raw

        print(f"\n  {count} reports read in 15 s")
        dev.close()
        print()

if __name__ == "__main__":
    main()
