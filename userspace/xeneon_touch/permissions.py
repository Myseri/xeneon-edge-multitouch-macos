"""
Accessibility (AX) permission handling for CGEvent injection.

macOS gates synthetic mouse/keyboard events behind the Accessibility
(kTCCServiceAccessibility) permission. Unlike Input Monitoring, the system
never prompts for it automatically — a process must explicitly call
AXIsProcessTrustedWithOptions({prompt: True}). That call both (a) reports
whether we're trusted and (b) registers this binary in the Accessibility list
and shows the grant dialog, which is the only reliable way to get a bare
command-line / framework-python binary to appear there enabled (a manual
file-picker add of such a binary stays greyed out).
"""

import ctypes
import logging

log = logging.getLogger(__name__)

# IOHIDRequestType / IOHIDAccessType (IOKit/hid/IOHIDLibUserClient.h)
_kIOHIDRequestTypeListenEvent = 1
_kIOHIDAccessTypeGranted = 0


def ensure_input_monitoring(prompt: bool = True) -> bool:
    """Return True if this process may listen to HID input events.

    macOS gates reading HID devices behind Input Monitoring
    (kTCCServiceListenEvent). Opening the device via hidapi does NOT reliably
    trigger the prompt or register the binary, so we call IOHIDRequestAccess
    explicitly — the Input Monitoring analogue of AXIsProcessTrustedWithOptions.
    That registers *this* binary in the list (no need to add it by hand) and,
    when not yet granted, shows the prompt. Never raises.
    """
    try:
        iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        iokit.IOHIDCheckAccess.restype = ctypes.c_int
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
    except Exception as e:  # pragma: no cover
        log.warning("Could not load IOHID access API (%s); skipping check.", e)
        return True

    granted = iokit.IOHIDCheckAccess(_kIOHIDRequestTypeListenEvent) == _kIOHIDAccessTypeGranted
    if granted:
        log.info("Input Monitoring permission: granted.")
        return True

    if prompt:
        # Registers this binary in the Input Monitoring list and prompts.
        iokit.IOHIDRequestAccess(_kIOHIDRequestTypeListenEvent)
    log.warning(
        "Input Monitoring permission NOT granted — the touch device cannot be "
        "read. Enable this binary under System Settings -> Privacy & Security "
        "-> Input Monitoring, then restart the service "
        "(brew services restart xeneon-touch)."
    )
    return False


def ensure_accessibility(prompt: bool = True) -> bool:
    """Return True if this process is trusted for Accessibility.

    When not trusted and prompt=True, asks macOS to show the grant dialog and
    register this binary in System Settings → Privacy & Security →
    Accessibility. Never raises — injection is attempted regardless, but a
    warning is logged so the failure mode is obvious in the log.
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except Exception as e:  # pragma: no cover - import shape varies by pyobjc
        log.warning("Could not load Accessibility API (%s); skipping check.", e)
        return True

    options = {kAXTrustedCheckOptionPrompt: bool(prompt)}
    trusted = bool(AXIsProcessTrustedWithOptions(options))

    if trusted:
        log.info("Accessibility permission: granted.")
    else:
        log.warning(
            "Accessibility permission NOT granted — cursor will move but clicks "
            "and drags will be dropped. A system dialog should have appeared; "
            "enable this binary under System Settings → Privacy & Security → "
            "Accessibility, then restart the agent "
            "(launchctl kickstart -k gui/$(id -u)/com.github.xeneon-touch)."
        )
    return trusted
