"""Draw every OLED expression into runs/face_preview.png; with --oled, also show each on the screen.

Usage (Mac or Pi): uv run python scripts/check_face.py
Usage (Pi):        uv run python scripts/check_face.py --oled   # rover.speech stopped (it owns it)
On the screen: two eyes, happy ones like an upside-down U. A blank screen: check OLED_ADDRESS
(i2cdetect -y 1); eyes shifted 2 px or a noise strip at the edge: OLED_COLUMN_OFFSET=2 (SH1106);
happy eyes look sad: OLED_FLIP=1.
"""

import argparse
import time

import cv2
import numpy as np

from rover import config
from rover.eyes import EXPRESSIONS, Eyes, Oled, draw

SCALE = 3  # preview pixels per OLED pixel
HOLD_S = 3.0  # each expression on the real screen, animated


def main() -> None:
    parser = argparse.ArgumentParser(description="OLED eyes preview")
    parser.add_argument("--oled", action="store_true", help="also cycle the faces on the OLED")
    args = parser.parse_args()

    tiles = []
    for name in EXPRESSIONS:
        tile = np.repeat(np.repeat(draw(name), SCALE, 0), SCALE, 1).astype(np.uint8) * 255
        tile = cv2.copyMakeBorder(tile, 24, 4, 4, 4, cv2.BORDER_CONSTANT, value=60)
        cv2.putText(tile, name, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 1)
        tiles.append(tile)
    tiles.append(np.full_like(tiles[0], 60))  # even grid
    sheet = np.vstack([np.hstack(tiles[i : i + 2]) for i in range(0, len(tiles), 2)])
    out = config.RUNS_DIR / "face_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    print(f"success: {len(EXPRESSIONS)} expressions drawn into {out}")

    if args.oled:
        eyes = Eyes(Oled()).start()
        for name in EXPRESSIONS:
            print(f"oled: {name}")
            eyes.base = name
            time.sleep(HOLD_S)
        eyes.stop()
        print("success: each expression showed on the OLED, then it went dark")


if __name__ == "__main__":
    main()
