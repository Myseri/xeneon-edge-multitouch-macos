"""Entry point: python3 -m xeneon_touch"""

import logging
import sys


def _run_as_background_agent():
    """Hide the Dock icon / menu-bar presence.

    Framework Python launches as a GUI app (the bouncing Python rocket in the
    Dock) the moment AppKit is imported. Setting the activation policy to
    Accessory — the programmatic equivalent of LSUIElement — makes it a UI-less
    background agent. Done before importing the daemon so it takes effect before
    discovery.py pulls in AppKit/NSScreen.
    """
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
        )
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        # Non-fatal: worst case the Dock icon shows; touch still works.
        pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    _run_as_background_agent()

    from .daemon import XeneonTouchDaemon

    daemon = XeneonTouchDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
