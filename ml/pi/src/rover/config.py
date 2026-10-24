"""Settings card: every threshold in one place. Start values; tune on site and update here."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ML_DIR = Path(__file__).resolve().parents[2]  # ml/pi: the folder sent to the Pi
MODELS_DIR = ML_DIR / "models"
RUNS_DIR = ML_DIR / "runs"
AGENT_DIR = Path(__file__).resolve().parent / "agent"

load_dotenv(ML_DIR / ".env")

# Backend and robot
BELLHOP_API = os.environ.get("BELLHOP_API", "http://127.0.0.1:8000")
BELLHOP_API_KEY = os.environ.get("BELLHOP_API_KEY", "")
ROBOT_ID = os.environ.get("ROBOT_ID", "robot_1")
PI_SERVER_URL = os.environ.get("PI_SERVER_URL", "http://127.0.0.1:8080")
HTTP_TIMEOUT_S = 2.0
CALL_POLL_S = 1.0

# Camera (Pi Camera Module 3). Lock these for the room once tuned.
FRAME_SIZE = (640, 480)
LENS_POSITION = 0.7  # dioptres = 1 / distance in metres
SHUTTER_US = 8000  # short shutter cuts blur while turning
ANALOGUE_GAIN = 4.0
AWB_GAINS = (1.6, 1.6)
CAMERA_FPS = 15

# YOLO26n person tracking
YOLO_MODEL = MODELS_DIR / "yolo26n_ncnn_model"
YOLO_IMGSZ = 320  # must match the NCNN export size
YOLO_CONF = 0.4
TRACKER = "bytetrack.yaml"
COAST_S = 2.0  # keep the last target this long after it disappears
VISION_OMP_THREADS = 2  # torch + ncnn OpenMP pools; the default size oversubscribes the CPU

# YuNet face detection inside the person box
YUNET_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
FACE_SCORE = 0.9
FACE_SEEN_OF = (3, 5)  # seen in 3 of the last 5 frames
FACE_MIN_WIDTH_PX = 40  # set at ~1 m on site
FACE_SYMMETRY = 0.35  # max nose offset from the eye midpoint, as a share of eye distance

# ArUco door markers (the printed sheet)
ARUCO_DICT = "DICT_4X4_250"
MARKER_SIZE_M = 0.15
MARKER_FOCAL_PX = 470.0  # from scripts/check_marker.py with the marker at 1.0 m
ARRIVE_DISTANCE_M = 1.0
def _marker_rooms() -> dict[int, str]:
    """Load physical-marker-to-backend-room names from deployment configuration."""
    raw = os.environ.get("BELLHOP_MARKER_ROOMS", "{}").strip()
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("BELLHOP_MARKER_ROOMS must be a JSON object") from exc
    if not isinstance(rows, dict):
        raise ValueError("BELLHOP_MARKER_ROOMS must be a JSON object")
    parsed: dict[int, str] = {}
    for marker, room in rows.items():
        try:
            marker_id = int(marker)
        except (TypeError, ValueError) as exc:
            raise ValueError("BELLHOP_MARKER_ROOMS keys must be ArUco marker IDs") from exc
        if not 0 <= marker_id < 250 or not isinstance(room, str) or not room.strip():
            raise ValueError("BELLHOP_MARKER_ROOMS has an invalid marker or room")
        parsed[marker_id] = room.strip()
    return parsed


MARKER_ROOMS = _marker_rooms()
HOME_ROOM = os.environ.get("BELLHOP_HOME_ROOM", "lobby")


def room_for_marker(marker_id: int) -> str:
    """Configured logical name, or direct numeric addressing for any valid ArUco marker."""
    return MARKER_ROOMS.get(marker_id, str(marker_id))


def marker_for_room(room: str) -> int | None:
    """Resolve backend target to marker ID without embedding venue rooms in code."""
    for marker_id, configured_room in MARKER_ROOMS.items():
        if room == configured_room:
            return marker_id
    try:
        marker_id = int(room)
    except (TypeError, ValueError):
        return None
    return marker_id if 0 <= marker_id < 250 else None

# Driving (rover.drive owns the motors, servos, ultrasonic and the robot HTTP server)
FREENOVE_DIR = Path(
    os.environ.get(
        "FREENOVE_DIR",
        Path.home() / "Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi" / "Code" / "Server",
    )
)
FREENOVE_PCB_VERSION = int(os.environ.get("FREENOVE_PCB_VERSION", "2"))  # printed on the car board
DRIVE_PORT = 8080  # backend BELLHOP_ROBOT_URL and PI_SERVER_URL point here
DRIVE_LOOP_HZ = 20
STOP_DISTANCE_CM = 25.0  # ultrasonic: nothing moves forward closer than this
VISION_WATCHDOG_S = 0.5  # no fresh vision message this long -> stop
# Optional manual backup control. Linux exposes most USB/Bluetooth PS2 adapters as /dev/input/js*;
# it is off unless rover.drive is launched with --controller.
MANUAL_DEVICE = os.environ.get("BELLHOP_MANUAL_DEVICE", "/dev/input/js0")
MANUAL_DEADMAN_BUTTON = int(os.environ.get("BELLHOP_MANUAL_DEADMAN_BUTTON", "4"))
MANUAL_FORWARD_AXIS = int(os.environ.get("BELLHOP_MANUAL_FORWARD_AXIS", "1"))
MANUAL_TURN_AXIS = int(os.environ.get("BELLHOP_MANUAL_TURN_AXIS", "0"))
MANUAL_DEADZONE = float(os.environ.get("BELLHOP_MANUAL_DEADZONE", "0.12"))
MANUAL_MAX_DUTY = int(os.environ.get("BELLHOP_MANUAL_MAX_DUTY", "1000"))
MANUAL_TIMEOUT_S = float(os.environ.get("BELLHOP_MANUAL_TIMEOUT_S", "0.35"))
MANUAL_REFRESH_S = 0.1
PAN_CENTER = 90
TILT_DRIVE = 90  # level: door markers are mounted low
# Freenove's servo client applies a +10-degree calibration error. Although its UI permits
# pan 0..180, those end values overrun a normal servo's pulse range. Stock obstacle avoidance
# uses this proven 30/90/150 sweep. Tilt below 80 can hit the chassis.
HEAD_PAN_MIN = 30
HEAD_PAN_MAX = 150
HEAD_TILT_MIN = 80
HEAD_TILT_MAX = 180


def _head_scan_pans() -> tuple[int, ...]:
    """Parse safe, venue-tunable camera pan positions from the deployment environment."""
    raw = os.environ.get("BELLHOP_HEAD_SCAN_PANS", "30,90,150")
    try:
        pans = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError("BELLHOP_HEAD_SCAN_PANS must be comma-separated servo angles") from exc
    if not pans or any(not HEAD_PAN_MIN <= pan <= HEAD_PAN_MAX for pan in pans):
        raise ValueError(
            "BELLHOP_HEAD_SCAN_PANS must contain safe angles from "
            f"{HEAD_PAN_MIN} through {HEAD_PAN_MAX}"
        )
    return pans


HEAD_SCAN_PANS = _head_scan_pans()
HEAD_SCAN_TILT = int(os.environ.get("BELLHOP_HEAD_SCAN_TILT", str(TILT_DRIVE)))
HEAD_SCAN_DWELL_S = float(os.environ.get("BELLHOP_HEAD_SCAN_DWELL_S", "0.6"))
if not HEAD_TILT_MIN <= HEAD_SCAN_TILT <= HEAD_TILT_MAX or HEAD_SCAN_DWELL_S <= 0:
    raise ValueError(
        f"head scan tilt must be {HEAD_TILT_MIN}..{HEAD_TILT_MAX} and dwell must be positive"
    )
APPROACH_MAX_DUTY = 1500
APPROACH_MIN_DUTY = 800
STEER_GAIN = 1500  # extra duty per unit of horizontal error (-1..1)
CENTER_TOLERANCE = 0.1  # share of half the frame width counted as centred
FACE_TURN_DUTY = 900
FOLLOW_STOP_HEIGHT = 0.7  # person box taller than this share of the frame -> close enough
FORWARD_DUTY = 1200
FORWARD_MAX_S = 2.0
HEARTBEAT_S = 5.0  # PUT /robots/{id}
# A non-idle LED with no /led command this long goes back to idle. The backend only sends idle when
# a call ends, so a dead backend would leave "listening" or "emergency" lit for good. A live visit
# re-sends its LED four times per hold, so it never expires while someone is being looked after.
LED_HOLD_S = float(os.environ.get("LED_HOLD_S", "120"))
LED_KEEPALIVE_S = LED_HOLD_S / 4
POWER_CACHE_S = 2.0  # vcgencmd and iw are subprocesses; /snapshot is polled more often than this
BATTERY_EMPTY_V = 6.4  # two 18650 cells in series
BATTERY_FULL_V = 8.4
LED_COLORS = {
    "idle": (0, 0, 40),
    "listening": (0, 80, 0),
    "nurse_on_way": (90, 50, 0),
    "emergency": (120, 0, 0),
}
MARKER_LOST_S = 1.0  # approach: target marker unseen this long -> search again
APPROACH_SLOW_FROM_M = 2.5  # approach slows from APPROACH_MAX_DUTY below this marker distance

# Claude goal check while driving
PLANNER_MODEL = "claude-haiku-5-5"
PLANNER_PERIOD_S = 10.0
PLANNER_TIMEOUT_S = 5.0
PLANNER_EFFORT = "low"  # a driving check must answer in ~1-2 s
PLANNER_MAX_TOKENS = 1024  # room for any thinking plus one tool call

# Vision -> voice / driving
VISION_HOST = "127.0.0.1"
VISION_PORTS = (5005, 5006)  # 5005 voice, 5006 driving
DRIVE_VISION_PORT = VISION_PORTS[1]
VISION_STALE_S = 2.0
LATEST_JPG = RUNS_DIR / "latest.jpg"
LATEST_JPG_EVERY_S = 1.0
LOOK_MAX_AGE_S = 3.0  # look() refuses an older latest.jpg (vision probably stopped)

# Audio
SAMPLE_RATE = 16000
BLOCK_SAMPLES = 512  # Silero needs 512-sample frames at 16 kHz
PREROLL_S = 0.5
ECHO_TAIL_S = 0.3  # mic stays muted this long after the robot stops talking
MIC_NAME = os.environ.get("MIC_NAME", "")  # part of the device name; empty = default
SPEAKER_NAME = os.environ.get("SPEAKER_NAME", "")
# PortAudio opens ALSA "plughw" (converts rate and channels) instead of raw "hw", so a USB mic
# that only records at 44.1/48 kHz still opens at 16 kHz. Read when sounddevice is imported.
os.environ.setdefault("PA_ALSA_PLUGHW", "1")

# Listen gates
SILERO_THRESHOLD = 0.5
LOUDNESS_MARGIN_DB = 10.0  # speech must be this far above the room's noise floor
FLOOR_WINDOW_S = 10.0
ATTENTION_WINDOW_S = 8.0
ATTENTION_RELIEF_DB = 5.0
FLOOR_START_DB = -60.0  # noise floor used until enough quiet blocks are heard
FLOOR_MIN_BLOCKS = 16  # ~0.5 s of non-speech blocks before the running floor is trusted

# Deepgram Flux
FLUX_MODEL = "flux-general-en"
EOT_THRESHOLD = 0.8
EAGER_EOT_THRESHOLD = 0.5
EOT_TIMEOUT_MS = 3000
FLUX_TURN_LIMIT_S = 5.0  # no final text this long after speech stops -> Moonshine
ROBOT_NAME = os.environ.get("ROBOT_NAME", "Bellhop")  # pick a 3+ syllable name at kickoff
MOONSHINE_ARCH = "small-streaming"  # offline fallback STT; scripts/download_models.py fetches it

# Claude
BRAIN_MODEL = "claude-sonnet-5-5"
TRIAGE_MODEL = "claude-haiku-5-5"
# First reply sentence budget before the fallback line. Measured from a laptop: first sentence in
# 1.3 to 2.0 s; the Pi on venue Wi-Fi was slower than the old 3 s, so allow twice that.
FIRST_TEXT_TIMEOUT_S = 6.0
CLAUDE_KEEPALIVE_S = 60.0  # keep the TLS connection to Claude between turns (SDK default is 5 s)
HISTORY_EXCHANGES = 20
MAX_REPLY_TOKENS = 300
BRAIN_EFFORT = "low"  # chat: low keeps the time to first spoken word short
BRAIN_MAX_TOOL_ROUNDS = 3
BRAIN_STREAM_TIMEOUT_S = 10.0  # longest silence on the reply stream before giving up

# Triage
TRIAGE_TIMEOUT_S = 6.0  # overall budget for Claude and its retry
TRIAGE_ATTEMPT_S = 3.0  # one Claude call; a failure inside the budget gets one retry
TRIAGE_RETRY_MIN_S = 1.0  # no retry unless at least this much budget is left
LOCAL_ONLY_CONFIDENCE = 0.5  # below the backend's 0.6, so it bumps urgency one level
# Local scorer (ONNX embedding + linear head, raise-only). Needs rover/triage/local_head.npz and
# the embedding model in MODELS_DIR/embed (python -m rover.triage.local); without them: no-op.
LOCAL_TRIAGE = os.environ.get("LOCAL_TRIAGE", "0") == "1"  # off by default: see README
LOCAL_HEAD = Path(__file__).parent / "triage" / "local_head.npz"
LOCAL_EMBED_DIR = MODELS_DIR / "embed"
LOCAL_MIN_CONFIDENCE = 0.5  # a local score below this is ignored
SUMMARY_MAX_CHARS = 300
TRIAGE_EFFORT = "low"  # has to answer inside TRIAGE_ATTEMPT_S
TRIAGE_MAX_TOKENS = 1024  # room for any thinking plus the small JSON answer

# Visit
SHUTDOWN_GRACE_S = 3.0  # after SIGTERM and the LED/stop cleanup, force-exit if a worker is stuck
VISIT_QUIET_END_S = 60.0
VISIT_START_FALLBACK_S = 60.0
FACE_START_S = 1.0
TRIAGE_WAIT_BEFORE_RESOLVE_S = 3.0
ECHO_MIN_WORDS = 4  # shorter turns ("tea", "yes please") often repeat the robot's words

# Piper voice (Poppy)
PIPER_VOICE = MODELS_DIR / "en_GB-semaine-medium.onnx"
PIPER_SPEAKER_ID = 3
MIN_LENGTH_SCALE = 0.9
MAX_PITCH = 0.08
# tag: (length_scale, pitch shift, noise_scale)
TONES = {
    "cheerful": (0.95, 0.04, 0.70),
    "excited": (0.90, 0.07, 0.75),
    "calm": (1.05, 0.00, 0.60),
    "gentle": (1.10, -0.04, 0.60),
}
DEFAULT_TONE = "cheerful"
SLOW_LENGTH_BONUS = 0.1  # added to length_scale when speech-settings say rate "slow"

# OLED eyes: a 128x64 I2C screen. SSD1306 (0.96 inch) by default; a 1.3 inch SH1106 needs offset 2
OLED_ADDRESS = int(os.environ.get("OLED_ADDRESS", "0x3C"), 16)
OLED_COLUMN_OFFSET = int(os.environ.get("OLED_COLUMN_OFFSET", "0"))
OLED_FLIP = os.environ.get("OLED_FLIP", "0") == "1"  # screen mounted upside down
EYES_FPS = 10  # each changed 8-row page costs ~12 ms of the I2C bus shared with the motor board
EYES_MOOD_HOLD_S = 3.0  # a reply's tone stays on the face this long after its last sentence
EYES_BLINK_EVERY_S = (3.0, 6.0)  # random gap between blinks
EYES_BLINK_S = 0.15
EYES_SLOW_BLINK_S = 0.4  # calm
EYES_GLANCE_EVERY_S = (3.0, 6.0)  # idle and listening glance aside now and then
EYES_GLANCE_S = 0.8
EYES_GLANCE_PX = 8
LOUD_GAIN = 1.5  # speech-settings volume "loud"; clipped to full scale
