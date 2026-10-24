"""Track one person with YOLO26n + ByteTrack and keep them as the target."""

import math
from dataclasses import dataclass

import numpy as np

from rover import config

Box = list[int]  # [x1, y1, x2, y2]


@dataclass
class Target:
    id: int
    box: Box
    seen_at: float


def _centre_distance(a: Box, b: Box) -> float:
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def _area(box: Box) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


def choose_target(tracks: dict[int, Box], target: Target | None, now: float) -> Target | None:
    """Keep the same id; coast on the last box; re-lock near it, or on the largest box later."""
    if target is not None and target.id in tracks:
        return Target(target.id, tracks[target.id], now)
    if target is not None and now - target.seen_at <= config.COAST_S:
        width = target.box[2] - target.box[0]
        near = [tid for tid, box in tracks.items() if _centre_distance(box, target.box) <= width]
        if near:
            track_id = min(near, key=lambda tid: _centre_distance(tracks[tid], target.box))
            return Target(track_id, tracks[track_id], now)
        return target
    if tracks:
        track_id = max(tracks, key=lambda tid: _area(tracks[tid]))
        return Target(track_id, tracks[track_id], now)
    return None


class PersonTracker:
    def __init__(self) -> None:
        model_path = config.YOLO_MODEL
        if not model_path.exists():
            # Passing a missing path to Ultralytics starts an implicit network download. A
            # canceled download can also leave a partial .pt file, so only accept the prepared
            # NCNN export from the explicit setup step.
            print("vision: no local NCNN person model; person and face detection disabled")
            self.model = None
            self.target = None
            return
        from ultralytics import YOLO

        self.model = YOLO(str(model_path), task="detect")
        self.target: Target | None = None

    def update(self, frame: np.ndarray, now: float) -> dict | None:
        if self.model is None:
            return None
        results = self.model.track(
            frame,
            persist=True,
            classes=[0],
            imgsz=config.YOLO_IMGSZ,
            conf=config.YOLO_CONF,
            tracker=config.TRACKER,
            verbose=False,
        )
        boxes = results[0].boxes.numpy()
        tracks: dict[int, Box] = {}
        if boxes.id is not None:
            for track_id, xyxy in zip(boxes.id, boxes.xyxy, strict=True):
                if np.all(np.isfinite(xyxy)):
                    tracks[int(track_id)] = [int(round(v)) for v in xyxy]
        self.target = choose_target(tracks, self.target, now)
        if self.target is None:
            return None
        return {"id": self.target.id, "box": self.target.box}
