"""Draw every expression into runs/face_preview.png; with --screen, also show each on the screen.

Usage (Mac or Pi): uv run python scripts/check_face.py  # animated on a Mac: ../dev/face_window.py
Usage (Pi):        uv run python scripts/check_face.py --screen  # rover.speech stopped (it owns it)
On the screen: two cyan eyes, happy ones like an upside-down U. A blank screen: the desktop owns
it (sudo systemctl stop display-manager). Not 1024x600: add video=HDMI-A-1:1024x600@60 to
/boot/firmware/cmdline.txt and reboot. Happy eyes look sad: EYES_FLIP=1.
"""

import argparse
import time

import cv2
import numpy as np

from rover import config
from rover.eyes import EXPRESSIONS, Eyes, Screen, draw

SCALE = 3  # preview pixels per face pixel
HOLD_S = 3.0  # each expression on the real screen, animated
TIMED_FRAMES = 20


def main() -> None:
    parser = argparse.ArgumentParser(description="Eyes preview")
    parser.add_argument("--screen", action="store_true", help="also cycle the faces on the screen")
    args = parser.parse_args()

    tiles = []
    for name in EXPRESSIONS:
        tile = draw(name, scale=SCALE).astype(np.uint8) * 255
        tile = cv2.copyMakeBorder(tile, 24, 4, 4, 4, cv2.BORDER_CONSTANT, value=60)
        cv2.putText(tile, name, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 1)
        tiles.append(tile)
    tiles.append(np.full_like(tiles[0], 60))  # even grid
    sheet = np.vstack([np.hstack(tiles[i : i + 2]) for i in range(0, len(tiles), 2)])
    out = config.RUNS_DIR / "face_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    print(f"success: {len(EXPRESSIONS)} expressions drawn into {out}")

    if args.screen:
        screen = Screen()
        width, height = screen.size
        print(f"screen: {width}x{height}, {screen.bits} bits a pixel, face drawn x{screen.scale}")
        start = time.perf_counter()
        for _ in range(TIMED_FRAMES):
            screen.show(draw("cheerful", scale=screen.scale))
        ms = (time.perf_counter() - start) / TIMED_FRAMES * 1000
        print(f"screen: {ms:.1f} ms a frame = {ms * config.EYES_FPS / 10:.0f}% of a core")
        eyes = Eyes(screen).start()
        for name in EXPRESSIONS:
            print(f"screen: {name}")
            eyes.base = name
            time.sleep(HOLD_S)
        eyes.stop()
        print("success: each expression showed on the screen, then it went dark")


if __name__ == "__main__":
    main()
