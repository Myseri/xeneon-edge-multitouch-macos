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

import logging

log = logging.getLogger(__name__)


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
