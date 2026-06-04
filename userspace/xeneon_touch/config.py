"""Configuration constants for the Xeneon Edge touch controller."""

# WCH (Nanjing Qinheng Microelectronics) USB HID controller
# Manufacturer string: "wch.cn", Product string: "TouchScreen"
VENDOR_ID  = 0x27C0   # 10176 decimal
PRODUCT_ID = 0x0859   # 2137 decimal

# Shorter aliases used throughout the package
VID = VENDOR_ID
PID = PRODUCT_ID

# HID interface layout (from enumeration):
#   Interface 0 path DevSrvsID:... — digitizer, three top-level collections:
#     UsagePage=13 Usage=4  → Touch Screen  (main container, Reports 1-N)
#     UsagePage=13 Usage=14 → Configuration (feature reports)
#     UsagePage=13 Usage=34 → Finger        (individual contact sub-reports)
#   Interface 1 — vendor control (0xFF0A/255)
#   Interface 2 — mouse (UsagePage=1 Usage=2) ← causes "wrong screen" problem

# HID usage pages
USAGE_PAGE_GENERIC_DESKTOP = 0x01
USAGE_PAGE_DIGITIZER       = 0x0D   # 13 decimal
USAGE_PAGE_VENDOR_CONTROL  = 0xFF0A

# HID Digitizer usages (Usage Page 0x0D)
USAGE_TOUCHSCREEN    = 0x04   # 4  — top-level Touch Screen application collection
USAGE_CONFIGURATION  = 0x0E   # 14 — device configuration/feature reports
USAGE_FINGER         = 0x22   # 34 — individual finger/contact collection

# Which interface to open for touch data
TARGET_USAGE_PAGE = USAGE_PAGE_DIGITIZER
TARGET_USAGE      = USAGE_TOUCHSCREEN

# Display identification
DISPLAY_NAME_HINTS = ("XENEON EDGE", "XENEON", "CRXED00")
DISPLAY_RESOLUTION = (2560, 1080)

# HID read settings
READ_TIMEOUT_MS = 10
DAEMON_SLEEP_S  = 0.001

# Touch coordinate ranges — confirmed from HID report descriptor:
#   X: 0 – 16383  (14-bit, physical 216.9 mm ≈ 2560 px)
#   Y: 0 –  9599  (physical  90.6 mm ≈ 1080 px)
TOUCH_X_MAX = 16383
TOUCH_Y_MAX = 9599

# Touch liftoff: how long after last report before we consider finger lifted
TOUCH_LIFTOFF_TIMEOUT = 0.08
