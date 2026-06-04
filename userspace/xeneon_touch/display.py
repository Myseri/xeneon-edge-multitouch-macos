"""Map normalised touch coordinates to macOS screen coordinates."""

import logging
from typing import Optional, Tuple

import Quartz

log = logging.getLogger(__name__)


class DisplayMapper:
    """
    Converts normalised touch coords (0..1) to absolute CGPoint coordinates
    on the target display, accounting for Retina scaling and display origin.
    """

    def __init__(self, bounds: Quartz.CGRect):
        """
        bounds  — the CGRect of the target display in global screen coordinates.
                  Obtained from Quartz.CGDisplayBounds() or NSScreen.frame().
        """
        self.bounds = bounds
        log.info(
            "DisplayMapper: origin=(%.0f,%.0f) size=%.0fx%.0f",
            bounds.origin.x, bounds.origin.y,
            bounds.size.width, bounds.size.height,
        )

    def to_screen(self, x_norm: float, y_norm: float) -> Quartz.CGPoint:
        """
        Convert normalised touch coordinates to absolute screen point.

        x_norm, y_norm  — each in range [0.0, 1.0]
        Returns CGPoint in global screen coordinates (origin = top-left of primary display).
        """
        # Clamp
        x_norm = max(0.0, min(1.0, x_norm))
        y_norm = max(0.0, min(1.0, y_norm))

        x = self.bounds.origin.x + x_norm * self.bounds.size.width
        y = self.bounds.origin.y + y_norm * self.bounds.size.height
        return Quartz.CGPoint(x, y)
