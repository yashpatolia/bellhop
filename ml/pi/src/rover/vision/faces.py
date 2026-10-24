"""YuNet face detection inside the target person's box, with a facing check."""

import math
from collections import deque

import cv2
import numpy as np

from rover import config


def is_facing(row: np.ndarray) -> bool:
    """YuNet row: nose x close to the eye midpoint, as a share of eye distance, means facing us."""
    right_x, right_y, left_x, left_y, nose_x = row[4], row[5], row[6], row[7], row[8]
    eye_distance = math.hypot(left_x - right_x, left_y - right_y)
    if not math.isfinite(eye_distance) or eye_distance <= 0 or not math.isfinite(nose_x):
        return False
    return bool(abs(nose_x - (left_x + right_x) / 2) / eye_distance <= config.FACE_SYMMETRY)


def to_frame(row: np.ndarray, x0: float, y0: float) -> np.ndarray:
    """Shift a YuNet row found in a crop at (x0, y0) back to full-frame coordinates."""
    shifted = row.copy()
    shifted[[0, 4, 6, 8, 10, 12]] += x0  # box x and the five landmark x values; 2-3 are w, h
    shifted[[1, 5, 7, 9, 11, 13]] += y0
    return shifted


class SeenCounter:
    """True once something was seen in `need` of the last `of` frames."""

    def __init__(self, need: int = config.FACE_SEEN_OF[0], of: int = config.FACE_SEEN_OF[1]):
        self.need = need
        self.recent: deque[bool] = deque(maxlen=of)

    def push(self, seen: bool) -> bool:
        self.recent.append(seen)
        return sum(self.recent) >= self.need


class FaceFinder:
    def __init__(self) -> None:
        if not config.YUNET_MODEL.exists():
            raise FileNotFoundError(
                f"vision: {config.YUNET_MODEL} missing, run scripts/download_models.py"
            )
        self.detector = cv2.FaceDetectorYN.create(
            str(config.YUNET_MODEL), "", config.FRAME_SIZE, config.FACE_SCORE, 0.3
        )
        self.seen = SeenCounter()
        self.last_face: dict | None = None

    def _detect(self, frame: np.ndarray, person_box: list[int]) -> dict | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = person_box
        y2 = y1 + (y2 - y1) // 2  # faces sit in the top half of the person box
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        crop_w, crop_h = x2 - x1, y2 - y1
        if crop_w < config.FACE_MIN_WIDTH_PX or crop_h < config.FACE_MIN_WIDTH_PX:
            return None
        self.detector.setInputSize((crop_w, crop_h))
        _, faces = self.detector.detect(np.ascontiguousarray(frame[y1:y2, x1:x2]))
        if faces is None or len(faces) == 0:
            return None
        row = faces[np.argmax(faces[:, 14])].astype(np.float64)
        if not np.all(np.isfinite(row)) or row[2] < config.FACE_MIN_WIDTH_PX:
            return None
        row = to_frame(row, x1, y1)
        return {
            "box": [int(round(v)) for v in row[0:4]],
            "score": round(float(row[14]), 3),
            "facing": is_facing(row),
            "width": round(float(row[2]), 1),
        }

    def update(self, frame: np.ndarray, person_box: list[int] | None) -> dict | None:
        face = self._detect(frame, person_box) if person_box is not None else None
        if face is not None:
            self.last_face = face
        # 3-of-5 debounces both ways: a missed frame keeps the last face, a stray hit is ignored.
        if not self.seen.push(face is not None):
            return None
        return self.last_face
