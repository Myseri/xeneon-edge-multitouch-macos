#!/usr/bin/env python3
"""Quick test: can we receive HID reports via IOHIDManager?"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xeneon_touch.hid_reader import IOHIDReader

print("Starting IOHIDReader for WCH touch controller (VID=0x27C0 PID=0x0859)...")
print("Touch the Xeneon Edge screen. Reports should appear below.\n")

reader = IOHIDReader(
    vendor_id=0x27C0, product_id=0x0859,
    usage_page=13,    # Digitizer
    usage=4,          # Touch Screen
)
reader.start()
time.sleep(0.2)  # let run loop initialise

count = 0
deadline = time.time() + 20
try:
    while time.time() < deadline:
        data = reader.read(timeout=0.1)
        if data:
            count += 1
            print(f"  [{count:3d}] {data.hex(' ')}")
except KeyboardInterrupt:
    pass
finally:
    reader.stop()

if count == 0:
    print("\nNo reports received — IOHIDManager may have failed to open.")
    print("Check the log above for 'IOHIDManagerOpen returned' error code.")
else:
    print(f"\nReceived {count} reports. IOHIDManager is working!")
