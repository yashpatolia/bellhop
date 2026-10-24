"""Vision process: camera -> person -> face -> markers -> one UDP JSON per frame + runs/latest.jpg.

Run: uv run python -m rover.vision [--source 0|clip.mp4] [--show]
This is the only program that opens the camera.
"""

import argparse
import json
import os
import socket
import sys
import time

import cv2
import numpy as np

from rover import config
from rover.vision.camera import open_camera
from rover.vision.faces import FaceFinder
from rover.vision.markers import MarkerFinder
from rover.vision.people import PersonTracker

FPS_PRINT_EVERY_S = 5.0


def parse_source(text: str | None) -> str | int | None:
    if text is None:
        return None
    return int(text) if text.isdigit() else text


def write_latest_jpg(frame: np.ndarray) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    temp = config.LATEST_JPG.with_name("latest.tmp.jpg")  # .jpg suffix tells imwrite the format
    if not cv2.imwrite(str(temp), frame):
        print(f"vision: could not write {temp}")
        return
    os.replace(temp, config.LATEST_JPG)  # atomic, so readers never see half a JPEG


def draw(frame: np.ndarray, message: dict) -> np.ndarray:
    view = frame.copy()
    if message["person"]:
        x1, y1, x2, y2 = message["person"]["box"]
        cv2.rectangle(view, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(view, f"id {message['person']['id']}", (x1, y1 - 6), 0, 0.6, (0, 255, 0), 2)
    if message["face"]:
        x, y, w, h = message["face"]["box"]
        colour = (0, 200, 255) if message["face"]["facing"] else (0, 0, 255)
        cv2.rectangle(view, (x, y), (x + w, y + h), colour, 2)
    for row, marker in enumerate(message["markers"]):
        text = (
            f"marker {marker['id']} room {marker['room']} {marker['distance_m']:.2f} m"
            f" x {marker['x']:+.2f}"
        )
        cv2.putText(view, text, (10, 24 + 22 * row), 0, 0.6, (255, 0, 0), 2)
    cv2.putText(
        view, f"{message['fps']:.1f} fps", (10, view.shape[0] - 10), 0, 0.6, (255, 255, 255), 2
    )
    return view


def main() -> None:
    parser = argparse.ArgumentParser(description="Bellhop vision process")
    parser.add_argument("--source", help="webcam index or video path; default = Pi camera")
    parser.add_argument("--show", action="store_true", help="show a window with boxes (Mac only)")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # logs piped to a file survive a kill
    print(f"vision: OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}")

    camera = open_camera(parse_source(args.source))
    print(f"vision: camera backend {camera.backend}")
    tracker = PersonTracker()
    faces = FaceFinder()
    markers = MarkerFinder()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    failed_ports: set[int] = set()

    frames, window_start, fps = 0, time.monotonic(), 0.0
    last_jpg = 0.0
    try:
        while True:
            frame = camera.read()
            if frame is None:
                print("vision: stopping, camera gave no frame")
                break
            now = time.monotonic()
            person = tracker.update(frame, now)
            message = {
                "t": time.time(),
                "fps": round(fps, 1),
                "person": person,
                "face": faces.update(frame, person["box"] if person else None),
                "markers": markers.detect(frame),
            }
            payload = json.dumps(message).encode()
            for port in config.VISION_PORTS:
                try:
                    sock.sendto(payload, (config.VISION_HOST, port))
                except OSError as error:
                    if port not in failed_ports:  # print once, not 15 times a second
                        print(f"vision: UDP send to port {port} failed: {error}")
                        failed_ports.add(port)

            if now - last_jpg >= config.LATEST_JPG_EVERY_S:
                write_latest_jpg(frame)
                last_jpg = now

            frames += 1
            if now - window_start >= FPS_PRINT_EVERY_S:
                fps = frames / (now - window_start)
                print(
                    f"vision: {fps:.1f} fps, person {person is not None}, "
                    f"face {message['face'] is not None}, markers {len(message['markers'])}"
                )
                frames, window_start = 0, now

            if args.show:
                cv2.imshow("bellhop vision", draw(frame, message))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("vision: stopped by Ctrl+C")
    finally:
        camera.close()
        sock.close()
        if args.show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
