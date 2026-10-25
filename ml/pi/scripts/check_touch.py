"""Print where the touchscreen is touched, in screen pixels: checks the panel is found and lines up.

Usage (Pi): uv run python scripts/check_touch.py   # Ctrl+C to stop
Touch the top-left corner, then the bottom-right: about (0, 0) and (1023, 599) is success.
"no touch panel": plug in the screen's touch USB cable (the second one). Corners swapped: the
panel is turned against the screen; EYES_FLIP=1 turns both the face and the touches.
"""

from rover.eyes import Screen
from rover.touch import Touch


def show(kind: str, x: int, y: int) -> None:
    if kind != "move":  # a finger sliding would fill the terminal
        print(f"touch: {kind:4s} at ({x}, {y})")


def main() -> None:
    try:
        size = Screen().size
    except Exception as exc:  # noqa: BLE001 - the touch panel can be checked without the screen
        print(f"fallback: no framebuffer ({type(exc).__name__}: {exc}); assuming 1024x600")
        size = (1024, 600)
    panel = Touch.open(size, show)
    print(
        f"success looks like: top-left about (0, 0), bottom-right about {size[0] - 1, size[1] - 1}"
    )
    panel.run()


if __name__ == "__main__":
    main()
