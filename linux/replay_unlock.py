#!/usr/bin/env python3
"""
Xeneon Edge (WingCoolTouch 27c0:0859) multitouch unlock test for Linux.

Replays the exact Windows 11 unlock sequence captured in
docs/xeneon_win11_unlock.pcapng (dev 27, pkts 78-113), then listens on
interface 0's interrupt IN endpoint (0x81) for report 0x0D multitouch data.

This is the same sequence the macOS DriverKit dext sends (v17/v18) — every
transfer succeeds there but the firmware never streams. Running it from a
Linux host answers: is the firmware gate "Windows-only" or "not-macOS"?

Usage:
    sudo apt install -y python3-usb   # or: pip install pyusb
    sudo python3 replay_unlock.py

Touch the screen (two fingers!) during the 30-second listen window.

Verdicts:
    UNLOCKED  -> 0x0D reports observed: gate is macOS-specific; a Pi/Linux
                 middlebox (or deeper macOS work) is provably viable.
    LOCKED    -> firmware demands Windows-specific behavior below the
                 post-SET_CONFIGURATION window; middlebox must emulate it.
"""

import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pyusb missing: sudo apt install python3-usb  (or pip install pyusb)")

VID, PID = 0x27C0, 0x0859
EP_IN = 0x81           # interface 0 interrupt IN, 64B, 1ms
REPORT_MT = 0x0D       # 54-byte 10-finger multitouch report
LISTEN_SECS = 30

# bmRequestType values
H2D_CLASS_IFACE = 0x21
D2H_CLASS_IFACE = 0xA1
D2H_STD_DEVICE  = 0x80

GET_DESCRIPTOR = 0x06
GET_REPORT     = 0x01
SET_REPORT     = 0x09
SET_IDLE       = 0x0A
FEATURE        = 0x03 << 8


def ctrl_in(dev, bm, breq, wval, widx, wlen, tag):
    try:
        data = dev.ctrl_transfer(bm, breq, wval, widx, wlen, timeout=1000)
        head = " ".join(f"{b:02x}" for b in data[:8])
        print(f"  {tag:<22} -> OK  xfer={len(data):<4} {head}")
        return bytes(data)
    except usb.core.USBError as e:
        print(f"  {tag:<22} -> FAIL ({e})")
        return None


def ctrl_out(dev, bm, breq, wval, widx, payload, tag):
    try:
        n = dev.ctrl_transfer(bm, breq, wval, widx, payload, timeout=1000)
        print(f"  {tag:<22} -> OK  xfer={n}")
        return True
    except usb.core.USBError as e:
        print(f"  {tag:<22} -> FAIL ({e})")
        return False


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit(f"Device {VID:04x}:{PID:04x} not found — is the monitor's USB plugged in?")
    print(f"Found WingCoolTouch at bus {dev.bus} addr {dev.address}")

    # Take interfaces 0-2 away from usbhid so we control the wire.
    for ifnum in range(3):
        try:
            if dev.is_kernel_driver_active(ifnum):
                dev.detach_kernel_driver(ifnum)
                print(f"  detached kernel driver from interface {ifnum}")
        except usb.core.USBError as e:
            print(f"  detach iface {ifnum}: {e}")

    usb.util.claim_interface(dev, 0)

    print("\n── Windows unlock replay (capture pkts 78-113) ──")
    # 3x double string fetch, Windows-style (string idx 2, lang 0x0409)
    for _ in range(3):
        ctrl_in(dev, D2H_STD_DEVICE, GET_DESCRIPTOR, 0x0302, 0x0409, 4,  "GET_STR2 len4")
        ctrl_in(dev, D2H_STD_DEVICE, GET_DESCRIPTOR, 0x0302, 0x0409, 24, "GET_STR2 len24")

    # idle + report-descriptor read per interface, in capture order
    rd_len = [768, 102, 144]
    for ifnum in range(3):
        ctrl_out(dev, H2D_CLASS_IFACE, SET_IDLE, 0x0000, ifnum, b"", f"SET_IDLE iface {ifnum}")
        ctrl_in(dev, 0x81, GET_DESCRIPTOR, 0x2200, ifnum, rd_len[ifnum], f"RD{ifnum}")

    # trailing oversized string fetch (pkt 108)
    ctrl_in(dev, D2H_STD_DEVICE, GET_DESCRIPTOR, 0x0302, 0x0409, 514, "GET_STR2 len514")

    # GET_REPORT Feature 0x0A — expect 0a 0f (pkt 110)
    ctrl_in(dev, D2H_CLASS_IFACE, GET_REPORT, FEATURE | 0x0A, 0, 2, "GET_REPORT 0x0A")

    # SET_REPORT Feature 0x21 = 21 02 00 (pkt 112) — the mode switch
    ctrl_out(dev, H2D_CLASS_IFACE, SET_REPORT, FEATURE | 0x21, 0,
             bytes([0x21, 0x02, 0x00]), "SET_REPORT 0x21 mode=2")

    print(f"\n── Listening on EP 0x81 for {LISTEN_SECS}s — TOUCH THE SCREEN (two fingers) ──")
    mt_seen = 0
    other_seen = 0
    deadline = time.time() + LISTEN_SECS
    while time.time() < deadline:
        try:
            data = dev.read(EP_IN, 64, timeout=500)
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError as e:
            print(f"  read error: {e}")
            break
        if not len(data):
            continue
        hexs = " ".join(f"{b:02x}" for b in data[:24])
        if data[0] == REPORT_MT:
            mt_seen += 1
            if mt_seen <= 10 or mt_seen % 100 == 0:
                contacts = data[54 - 1] if len(data) >= 54 else "?"
                print(f"  0x0D MULTITOUCH #{mt_seen} (contacts={contacts}): {hexs}")
        else:
            other_seen += 1
            if other_seen <= 5:
                print(f"  other report id=0x{data[0]:02x}: {hexs}")

    print("\n── VERDICT ──")
    if mt_seen:
        print(f"UNLOCKED: {mt_seen} multitouch reports on interface 0.")
        print("The firmware gate is macOS-specific, NOT Windows-only.")
        print("-> Middlebox approach is proven viable.")
    elif other_seen:
        print(f"PARTIAL: {other_seen} non-0x0D reports on interface 0 but no multitouch.")
    else:
        print("LOCKED: interface 0 silent, same as macOS.")
        print("-> Firmware demands Windows-specific enumeration behavior.")


if __name__ == "__main__":
    main()
