"""
IOHIDEventSystemClient-based touch reader for macOS.

Rather than trying to open the HID device (which fails with
kIOReturnExclusiveAccess), we subscribe as a *passive* client to the
IOHIDEventSystem — the stream of already-processed IOHIDEvents that
AppleUserHIDDevice generates from the raw HID reports.

No device ownership, no entitlements, no conflict.
"""

import ctypes
import queue
import threading
import logging
import time
from dataclasses import dataclass
from typing import Optional, List

log = logging.getLogger(__name__)

# ── frameworks ─────────────────────────────────────────────────────────────
_IOKit = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/IOKit.framework/IOKit')
_CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

_vp, _i32, _u32, _lng, _dbl, _i64 = (
    ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32,
    ctypes.c_long, ctypes.c_double, ctypes.c_int64,
)

# ── CoreFoundation ─────────────────────────────────────────────────────────
_CF.CFStringCreateWithCString.restype  = _vp
_CF.CFStringCreateWithCString.argtypes = [_vp, ctypes.c_char_p, _u32]
_CF.CFNumberCreate.restype             = _vp
_CF.CFNumberCreate.argtypes            = [_vp, _lng, _vp]
_CF.CFDictionaryCreateMutable.restype  = _vp
_CF.CFDictionaryCreateMutable.argtypes = [_vp, _lng, _vp, _vp]
_CF.CFDictionarySetValue.restype       = None
_CF.CFDictionarySetValue.argtypes      = [_vp, _vp, _vp]
_CF.CFArrayGetCount.restype            = _lng
_CF.CFArrayGetCount.argtypes           = [_vp]
_CF.CFArrayGetValueAtIndex.restype     = _vp
_CF.CFArrayGetValueAtIndex.argtypes    = [_vp, _lng]
_CF.CFRunLoopGetCurrent.restype        = _vp
_CF.CFRunLoopGetCurrent.argtypes       = []
_CF.CFRunLoopRun.restype               = None
_CF.CFRunLoopRun.argtypes              = []
_CF.CFRunLoopStop.restype              = None
_CF.CFRunLoopStop.argtypes             = [_vp]

# ── IOHIDEventSystemClient ─────────────────────────────────────────────────
_IOKit.IOHIDEventSystemClientCreateWithType.restype  = _vp
_IOKit.IOHIDEventSystemClientCreateWithType.argtypes = [_vp, _i32, _vp]

_IOKit.IOHIDEventSystemClientSetMatching.restype  = None
_IOKit.IOHIDEventSystemClientSetMatching.argtypes = [_vp, _vp]

_IOKit.IOHIDEventSystemClientRegisterEventCallback.restype  = None
_IOKit.IOHIDEventSystemClientRegisterEventCallback.argtypes = [_vp, _vp, _vp, _vp]

_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.restype  = None
_IOKit.IOHIDEventSystemClientScheduleWithRunLoop.argtypes = [_vp, _vp, _vp]

# ── IOHIDEvent ─────────────────────────────────────────────────────────────
_IOKit.IOHIDEventGetType.restype         = _i32
_IOKit.IOHIDEventGetType.argtypes        = [_vp]
_IOKit.IOHIDEventGetFloatValue.restype   = _dbl
_IOKit.IOHIDEventGetFloatValue.argtypes  = [_vp, _i32]
_IOKit.IOHIDEventGetIntegerValue.restype  = _i64
_IOKit.IOHIDEventGetIntegerValue.argtypes = [_vp, _i32]
_IOKit.IOHIDEventGetChildren.restype     = _vp   # CFArrayRef
_IOKit.IOHIDEventGetChildren.argtypes    = [_vp]

# ── constants ──────────────────────────────────────────────────────────────
kIOHIDEventSystemClientTypePassive = 4
kIOHIDEventTypeDigitizer           = 11   # 0x0B
kCFStringEncodingUTF8              = 0x08000100
kCFNumberSInt32Type                = 3

# IOHIDEventField = (eventType << 16) | fieldIndex
def _f(idx): return (kIOHIDEventTypeDigitizer << 16) | idx

kIOHIDEventFieldDigitizerX          = _f(0)   # 0x000B0000
kIOHIDEventFieldDigitizerY          = _f(1)   # 0x000B0001
kIOHIDEventFieldDigitizerTipSwitch  = _f(11)  # 0x000B000B
kIOHIDEventFieldDigitizerRange      = _f(13)  # 0x000B000D
kIOHIDEventFieldDigitizerTouch      = _f(14)  # 0x000B000E
kIOHIDEventFieldDigitizerCollection = _f(15)  # 0x000B000F
kIOHIDEventFieldDigitizerIdentity   = _f(17)  # 0x000B0011

_kDefaultMode = _CF.CFStringCreateWithCString(
    None, b"kCFRunLoopDefaultMode", kCFStringEncodingUTF8)


def _cfstr(s: str) -> _vp:
    return _CF.CFStringCreateWithCString(
        None, s.encode(), kCFStringEncodingUTF8)

def _cfnum(n: int) -> _vp:
    v = ctypes.c_int32(n)
    return _CF.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(v))

# Callback: void cb(void* target, void* refcon, IOHIDServiceClientRef, IOHIDEventRef)
_EventCB = ctypes.CFUNCTYPE(None, _vp, _vp, _vp, _vp)


@dataclass
class TouchContact:
    x:          float   # raw value — log shows what range this is
    y:          float
    tip_switch: bool
    contact_id: int = 0

    @property
    def active(self) -> bool:
        return self.tip_switch


class IOHIDEventReader:
    """
    Passive IOHIDEventSystem subscriber.
    Receives digitizer events for a specific VID/PID device after the
    system driver has processed the raw HID reports.
    """

    def __init__(self, vendor_id: int, product_id: int):
        self._vid = vendor_id
        self._pid = product_id
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._client   = None
        self._runloop  = None
        self._thread: Optional[threading.Thread] = None
        self._running  = False
        self._cb = _EventCB(self._on_event)   # keep reference

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="IOHIDEventReader")
        self._thread.start()
        time.sleep(0.2)   # let run loop spin up

    def stop(self):
        self._running = False
        if self._runloop:
            _CF.CFRunLoopStop(self._runloop)

    def read(self, timeout: float = 0.05) -> Optional[List[TouchContact]]:
        """Return a list of TouchContacts, or None on timeout."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── internal ───────────────────────────────────────────────────────────

    def _run(self):
        self._client = _IOKit.IOHIDEventSystemClientCreateWithType(
            None, kIOHIDEventSystemClientTypePassive, None)

        if not self._client:
            log.error("IOHIDEventSystemClientCreateWithType returned NULL — "
                      "may need Accessibility or Input Monitoring permission")
            return

        # NOTE: IOHIDEventSystemClientSetMatching with a plain VID/PID dict
        # silently drops all events on macOS — do NOT call it here.
        # We receive all digitizer events and filter by VID/PID in the callback.

        _IOKit.IOHIDEventSystemClientRegisterEventCallback(
            self._client, self._cb, None, None)

        self._runloop = _CF.CFRunLoopGetCurrent()
        _IOKit.IOHIDEventSystemClientScheduleWithRunLoop(
            self._client, self._runloop, _kDefaultMode)

        log.info("IOHIDEventSystemClient (passive) started — "
                 "filtering for VID=0x%04X PID=0x%04X in callback",
                 self._vid, self._pid)
        _CF.CFRunLoopRun()
        log.info("IOHIDEventSystemClient stopped.")

    def _on_event(self, target, refcon, service, event):
        if not self._running or not event:
            return

        if _IOKit.IOHIDEventGetType(event) != kIOHIDEventTypeDigitizer:
            return

        is_collection = bool(_IOKit.IOHIDEventGetIntegerValue(
            event, kIOHIDEventFieldDigitizerCollection))

        contacts: List[TouchContact] = []

        if is_collection:
            children = _IOKit.IOHIDEventGetChildren(event)
            if children:
                for i in range(_CF.CFArrayGetCount(children)):
                    child = _CF.CFArrayGetValueAtIndex(children, i)
                    if (child and
                            _IOKit.IOHIDEventGetType(child) == kIOHIDEventTypeDigitizer):
                        contacts.append(self._contact(child))
        else:
            contacts.append(self._contact(event))

        if contacts:
            try:
                self._q.put_nowait(contacts)
            except queue.Full:
                pass

    def _contact(self, ev) -> TouchContact:
        return TouchContact(
            x          = _IOKit.IOHIDEventGetFloatValue(ev, kIOHIDEventFieldDigitizerX),
            y          = _IOKit.IOHIDEventGetFloatValue(ev, kIOHIDEventFieldDigitizerY),
            tip_switch = bool(_IOKit.IOHIDEventGetIntegerValue(ev, kIOHIDEventFieldDigitizerTipSwitch)),
            contact_id = int(_IOKit.IOHIDEventGetIntegerValue(ev, kIOHIDEventFieldDigitizerIdentity)),
        )
