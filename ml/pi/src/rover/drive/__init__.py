"""Driving: robot HTTP server, drive loop, safety. Run: python -m rover.drive"""

from rover import config

# Deployment configuration maps physical ArUco IDs to backend room labels. Numeric labels address
# their matching marker directly, so all valid IDs can be used without source changes.
MARKER_ROOMS = config.MARKER_ROOMS
ROOMS = frozenset(MARKER_ROOMS.values())
LED_STATES = ("idle", "listening", "nurse_on_way", "emergency")
WATCHDOG_S = 5.0  # no fresh command this long in follow/face mode -> stop
# A drive in progress may not be cut off at WATCHDOG_S; see config.DRIVE_TIMEOUT_S.
DRIVE_TIMEOUT_S = config.DRIVE_TIMEOUT_S
HOME_ROOM = config.HOME_ROOM
