"""
IOHIDManager-based HID report reader for macOS.

Uses the native IOKit IOHIDManager C API via ctypes.
Receives HID input reports as a subscriber alongside any existing
driver — no exclusive access needed, no conflict with AppleUserHIDDevice.
"""

import ctypes
import queue
import threading
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# ── load frameworks ────────────────────────────────────────────────────────
_IOKit = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/IOKit.framework/IOKit')
_CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

# ── types ──────────────────────────────────────────────────────────────────
_vp  = ctypes.c_void_p
_u32 = ctypes.c_uint32
_i32 = ctypes.c_int32
_lng = ctypes.c_long

# ── CoreFoundation ─────────────────────────────────────────────────────────
_CF.CFStringCreateWithCString.restype  = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
_CF.CFNumberCreate.restype             = _vp
_CF.CFNumberCreate.argtypes            = [_vp, _lng, _vp]
_CF.CFDictionaryCreateMutable.restype  = _vp
_CF.CFDictionaryCreateMutable.argtypes = [_vp, _lng, _vp, _vp]
_CF.CFDictionarySetValue.restype       = None
_CF.CFDictionarySetValue.argtypes      = [_vp, _vp, _vp]
_CF.CFRunLoopGetCurrent.restype        = _vp
_CF.CFRunLoopGetCurrent.argtypes       = []
_CF.CFRunLoopRun.restype               = None
_CF.CFRunLoopRun.argtypes              = []
_CF.CFRunLoopStop.restype              = None
_CF.CFRunLoopStop.argtypes             = [_vp]

# ── IOHIDManager ───────────────────────────────────────────────────────────
_IOKit.IOHIDManagerCreate.restype                        = _vp
_IOKit.IOHIDManagerCreate.argtypes                       = [_vp, _u32]
_IOKit.IOHIDManagerOpen.restype                          = _i32
_IOKit.IOHIDManagerOpen.argtypes                         = [_vp, _u32]
_IOKit.IOHIDManagerClose.restype                         = _i32
_IOKit.IOHIDManagerClose.argtypes                        = [_vp, _u32]
_IOKit.IOHIDManagerSetDeviceMatching.restype             = None
_IOKit.IOHIDManagerSetDeviceMatching.argtypes            = [_vp, _vp]
_IOKit.IOHIDManagerRegisterInputReportCallback.restype   = None
_IOKit.IOHIDManagerRegisterInputReportCallback.argtypes  = [_vp, _vp, _vp]
_IOKit.IOHIDManagerScheduleWithRunLoop.restype           = None
_IOKit.IOHIDManagerScheduleWithRunLoop.argtypes          = [_vp, _vp, _vp]

# ── constants ──────────────────────────────────────────────────────────────
kIOHIDOptionsTypeNone        = 0x00
kIOHIDOptionsTypeSeizeDevice = 0x01
kCFNumberSInt32Type    = 3
kCFStringEncodingUTF8  = 0x08000100

_kCFRunLoopDefaultMode = _CF.CFStringCreateWithCString(
    None, b"kCFRunLoopDefaultMode", kCFStringEncodingUTF8)

# Callback type:
# void cb(void* ctx, IOReturn result, void* sender,
#         IOHIDReportType type, uint32_t reportID,
#         uint8_t* report, CFIndex reportLength)
_ReportCB = ctypes.CFUNCTYPE(
    None, _vp, _i32, _vp, _i32, _u32,
    ctypes.POINTER(ctypes.c_uint8), _lng,
)


def _cfstr(s: str) -> _vp:
    return _CF.CFStringCreateWithCString(
        None, s.encode(), kCFStringEncodingUTF8)


def _cfnum(n: int) -> _vp:
    v = ctypes.c_int32(n)
    return _CF.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(v))


def _make_matching(vendor_id: int, product_id: int,
                   usage_page: int, usage: int) -> _vp:
    d = _CF.CFDictionaryCreateMutable(None, 0, None, None)
    # Use both key name variants (IOKit accepts either)
    _CF.CFDictionarySetValue(d, _cfstr("VendorID"),          _cfnum(vendor_id))
    _CF.CFDictionarySetValue(d, _cfstr("ProductID"),         _cfnum(product_id))
    _CF.CFDictionarySetValue(d, _cfstr("PrimaryUsagePage"),  _cfnum(usage_page))
    _CF.CFDictionarySetValue(d, _cfstr("PrimaryUsage"),      _cfnum(usage))
    return d


class IOHIDReader:
    """
    Subscribe to HID input reports from a specific device.
    Uses IOHIDManager with kIOHIDOptionsTypeSeizeDevice — takes exclusive
    access to the digitizer, disconnecting AppleUserHIDDevice from it.
    """

    def __init__(self, vendor_id: int, product_id: int,
                 usage_page: int, usage: int):
        self._vid = vendor_id
        self._pid = product_id
        self._up  = usage_page
        self._u   = usage
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._manager  = None
        self._runloop  = None
        self._thread: Optional[threading.Thread] = None
        self._running  = False
        self._opened   = False
        # Keep reference so GC doesn't collect the C callback
        self._cb = _ReportCB(self._on_report)

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="IOHIDReader")
        self._thread.start()
        # Wait up to 1 s for the manager to open
        deadline = time.monotonic() + 1.0
        while not self._opened and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self._opened:
            log.warning("IOHIDManager did not open within 1 s")

    def stop(self):
        self._running = False
        if self._runloop:
            _CF.CFRunLoopStop(self._runloop)

    def read(self, timeout: float = 0.05) -> Optional[bytes]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_open(self) -> bool:
        return self._opened

    # ── internal ───────────────────────────────────────────────────────────

    def _run(self):
        self._manager = _IOKit.IOHIDManagerCreate(None, kIOHIDOptionsTypeNone)

        matching = _make_matching(self._vid, self._pid, self._up, self._u)
        _IOKit.IOHIDManagerSetDeviceMatching(self._manager, matching)
        _IOKit.IOHIDManagerRegisterInputReportCallback(
            self._manager, self._cb, None)

        self._runloop = _CF.CFRunLoopGetCurrent()
        _IOKit.IOHIDManagerScheduleWithRunLoop(
            self._manager, self._runloop, _kCFRunLoopDefaultMode)

        result = _IOKit.IOHIDManagerOpen(self._manager, kIOHIDOptionsTypeSeizeDevice)
        if result != 0:
            log.error(
                "IOHIDManagerOpen failed: IOReturn=0x%08X (%d)  "
                "VID=0x%04X PID=0x%04X page=0x%02X usage=0x%02X",
                result & 0xFFFFFFFF, result,
                self._vid, self._pid, self._up, self._u,
            )
            # Common codes:
            #   0xe00002c5 = kIOReturnExclusiveAccess
            #   0xe00002cd = kIOReturnNotPermitted
            #   0xe00002bc = kIOReturnNoDevice
            self._running = False
        return

        self._opened = True
        log.info(
            "IOHIDManager open — VID=0x%04X PID=0x%04X page=0x%02X usage=0x%02X",
            self._vid, self._pid, self._up, self._u,
        )
        _CF.CFRunLoopRun()
        _IOKit.IOHIDManagerClose(self._manager, kIOHIDOptionsTypeNone)
        log.info("IOHIDManager closed.")

    def _on_report(self, context, result, sender,
                   report_type, report_id, report_ptr, report_length):
        if not self._running:
            self._running = False
        return
        try:
            data = bytes([report_id]) + bytes(report_ptr[:report_length])
            self._q.put_nowait(data)
        except queue.Full:
            pass
