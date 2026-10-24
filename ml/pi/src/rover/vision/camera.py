"""One camera interface for the Pi camera (picamera2) and the Mac (cv2.VideoCapture)."""

import cv2
import numpy as np

from rover import config


def _three_channels(frame: np.ndarray) -> np.ndarray:
    return frame[:, :, :3] if frame.ndim == 3 and frame.shape[2] == 4 else frame


class PiCamera:
    backend = "picamera2"

    def __init__(self) -> None:
        from libcamera import controls
        from picamera2 import Picamera2

        frame_us = int(1_000_000 / config.CAMERA_FPS)
        self.cam = Picamera2()
        # Locked focus, exposure and white balance so the face and marker numbers stay comparable.
        video_config = self.cam.create_video_configuration(
            main={"size": config.FRAME_SIZE, "format": "RGB888"},
            controls={
                "AfMode": controls.AfModeEnum.Manual,
                "LensPosition": config.LENS_POSITION,
                "ExposureTime": config.SHUTTER_US,
                "AnalogueGain": config.ANALOGUE_GAIN,
                "ColourGains": config.AWB_GAINS,
                "FrameDurationLimits": (frame_us, frame_us),
            },
        )
        self.cam.configure(video_config)
        self.cam.start()

    def read(self) -> np.ndarray | None:
        try:
            # picamera2 "RGB888" is already BGR byte order, which is what OpenCV expects.
            return _three_channels(self.cam.capture_array("main"))
        except Exception as error:
            print(f"camera: picamera2 capture failed: {error}")
            return None

    def close(self) -> None:
        self.cam.stop()
        self.cam.close()


class CvCamera:
    backend = "VideoCapture"

    def __init__(self, source: str | int) -> None:
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera: cv2.VideoCapture could not open {source!r}")

    def read(self) -> np.ndarray | None:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            print("camera: VideoCapture returned no frame (end of clip or camera unplugged)")
            return None
        frame = _three_channels(frame)
        if (frame.shape[1], frame.shape[0]) != config.FRAME_SIZE:
            frame = cv2.resize(frame, config.FRAME_SIZE)
        return frame

    def close(self) -> None:
        self.cap.release()


def open_camera(source: str | int | None = None) -> PiCamera | CvCamera:
    """source None = the Pi camera when picamera2 exists, else webcam 0; an int or a clip path."""
    if source is None:
        try:
            import picamera2  # noqa: F401
        except ImportError as error:
            print(f"camera: picamera2 not available ({error}), using cv2.VideoCapture(0)")
        else:
            return PiCamera()
    return CvCamera(0 if source is None else source)
