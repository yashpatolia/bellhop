"""Grab one frame from the default camera and save runs/check_camera.png.

Run (Mac or Pi, with rover.vision stopped): uv run python scripts/check_camera.py
"""

import cv2

from rover import config
from rover.vision.camera import open_camera


def main() -> None:
    camera = open_camera(None)
    try:
        frame = camera.read()
    finally:
        camera.close()
    if frame is None:
        raise SystemExit(f"check_camera: FAILED, {camera.backend} gave no frame")
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RUNS_DIR / "check_camera.png"
    cv2.imwrite(str(path), frame)
    print(f"backend: {camera.backend}")
    print(f"shape: {frame.shape}, dtype: {frame.dtype}, mean brightness: {frame.mean():.1f}")
    print(f"check_camera: OK, saved {path} (expect (480, 640, 3) uint8, brightness 40-200)")


if __name__ == "__main__":
    main()
