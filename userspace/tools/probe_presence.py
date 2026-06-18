#!/usr/bin/env python3
"""
Which presence signal updates live in a long-lived process?

Prints, once a second for ~60s:
  hid = number of WCH touch-controller HID interfaces enumerated (IOKit, live)
  NS  = NSScreen.localizedName list (may be cached)
  CG  = CGGetOnlineDisplayList ids (window-server query)

Run it, then UNPLUG the Edge for a few seconds, then REPLUG. Watch which of
hid / NS / CG actually change. Whichever flips reliably is what the daemon
should poll for connect/disconnect.

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/hidapi/lib \
      python3 tools/probe_presence.py
"""
import time
import hid
import Quartz
import AppKit
from Foundation import NSRunLoop, NSDate

VID, PID = 0x27C0, 0x0859

for _ in range(60):
    # pump run loop in case AppKit needs it to refresh NSScreen
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    n_hid = len(hid.enumerate(VID, PID))
    ns = [str(s.localizedName()) for s in AppKit.NSScreen.screens()]
    _, ids, _ = Quartz.CGGetOnlineDisplayList(16, None, None)
    print(f"hid={n_hid}  NS={ns}  CG={list(ids)}", flush=True)
    time.sleep(1)
