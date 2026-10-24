"""Driving: robot HTTP server, drive loop, safety. Run: python -m rover.drive"""

from rover import config

# Deployment configuration maps physical ArUco IDs to backend room labels. Numeric labels address
# their matching marker directly, so all valid IDs can be used without source changes.
MARKER_ROOMS = config.MARKER_ROOMS
ROOMS = frozenset(MARKER_ROOMS.values())
LED_STATES = ("idle", "listening", "nurse_on_way", "emergency")
WATCHDOG_S = 5.0  # no fresh command this long in follow/face mode -> stop
# A go_to is sent once (by the backend dispatcher) and nobody repeats it, so a drive in progress
# may not be cut off at WATCHDOG_S. It is authorised for this long after the last go_to, then the
# robot stops and its LED goes idle: a backend that went away cannot leave it driving.
DRIVE_TIMEOUT_S = 60.0
HOME_ROOM = config.HOME_ROOM
