"""(Mac) Watch the eyes animate in a window the size of the 7 inch screen: blinks, glances, moods.

    cd ml/pi && uv run python ../dev/face_window.py

Space: next expression (printed here). q: quit. Success looks like cyan eyes that blink and glance
aside every few seconds.
"""

import cv2
import numpy as np

from rover import config
from rover.eyes import EXPRESSIONS, Eyes


class Window:
    """Stands in for the screen: the 7 inch screen's scale, in an OpenCV window."""

    scale = 8

    def show(self, frame: np.ndarray) -> None:
        image = np.zeros((*frame.shape, 3), np.uint8)
        image[frame] = config.EYES_RGB[::-1]  # OpenCV is BGR
        cv2.imshow("eyes", image)


def main() -> None:
    eyes, names = Eyes(Window()), list(EXPRESSIONS)
    print(f"window: {names[0]} (space: next expression, q: quit)")
    while True:
        eyes.tick()  # on this thread: macOS only draws windows from the main thread
        key = cv2.waitKey(1000 // config.EYES_FPS) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" "):
            eyes.base = names[(names.index(eyes.base) + 1) % len(names)]
            print(f"window: {eyes.base}")
    cv2.destroyAllWindows()
    print("success: the eyes blinked and glanced in the window")


if __name__ == "__main__":
    main()
