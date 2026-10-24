"""ArUco door markers: id, room and distance from the marker's size in pixels."""

import math

import cv2
import numpy as np

from rover import config


def side_px(corners: np.ndarray) -> float:
    """Mean length of the 4 sides of one marker's (4, 2) corner array."""
    return float(np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1).mean())


def distance_m(side: float) -> float | None:
    """Pinhole distance; None for a side that is NaN, inf or not positive."""
    if not math.isfinite(side) or side <= 0:
        return None
    distance = config.MARKER_SIZE_M * config.MARKER_FOCAL_PX / side
    return distance if math.isfinite(distance) and distance > 0 else None


class MarkerFinder:
    def __init__(self) -> None:
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, config.ARUCO_DICT))
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(dictionary, params)

    def corners(self, frame: np.ndarray) -> list[tuple[int, np.ndarray]]:
        """(marker id, (4, 2) corner array) for every marker in the frame."""
        corners, ids, _ = self.detector.detectMarkers(frame)
        if ids is None:
            return []
        return [
            (int(marker_id), marker_corners.reshape(4, 2))
            for marker_id, marker_corners in zip(ids.flatten(), corners, strict=True)
        ]

    def find(self, frame: np.ndarray) -> list[tuple[int, float]]:
        """(marker id, side length in px) for every marker in the frame."""
        return [(marker_id, side_px(c)) for marker_id, c in self.corners(frame)]

    def detect(self, frame: np.ndarray) -> list[dict]:
        """x is the marker centre from -1 (left edge) to 1 (right edge), 0 = frame centre."""
        half_width = frame.shape[1] / 2
        markers = []
        for marker_id, marker_corners in self.corners(frame):
            side = side_px(marker_corners)
            distance = distance_m(side)
            if distance is None:
                print(f"vision: marker {marker_id} dropped, side {side} px gives no distance")
                continue
            markers.append(
                {
                    "id": marker_id,
                    "room": config.MARKER_ROOMS.get(marker_id),
                    "distance_m": round(distance, 3),
                    "x": round(float(marker_corners[:, 0].mean()) / half_width - 1, 3),
                }
            )
        return markers
