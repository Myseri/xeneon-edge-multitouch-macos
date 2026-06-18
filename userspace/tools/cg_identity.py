#!/usr/bin/env python3
"""Print CG hardware identity + bounds for every online display.

Used to capture the Xeneon Edge's stable vendor/model numbers so the daemon can
identify it via CoreGraphics (which updates live) instead of NSScreen (stale in
a long-lived process). Run with the Edge connected.
"""
import Quartz

_, ids, _ = Quartz.CGGetOnlineDisplayList(16, None, None)
for d in ids:
    b = Quartz.CGDisplayBounds(d)
    print(
        f"id={d} "
        f"vendor={Quartz.CGDisplayVendorNumber(d)} "
        f"model={Quartz.CGDisplayModelNumber(d)} "
        f"serial={Quartz.CGDisplaySerialNumber(d)} "
        f"main={bool(Quartz.CGDisplayIsMain(d))} "
        f"bounds=({b.origin.x:.0f},{b.origin.y:.0f} {b.size.width:.0f}x{b.size.height:.0f})"
    )
