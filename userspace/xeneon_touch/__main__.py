"""Entry point: python3 -m xeneon_touch"""

import logging
import sys

from .daemon import XeneonTouchDaemon


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    daemon = XeneonTouchDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
