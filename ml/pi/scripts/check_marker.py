"""Print each marker's id, side length in px and distance, live.

Run (with rover.vision stopped, it owns the camera):
  uv run python scripts/check_marker.py           # live distances with the current focal
  uv run python scripts/check_marker.py --at 1.0  # marker held 1.0 m away -> focal for config
"""

import argparse

from rover import config
from rover.vision.__main__ import parse_source
from rover.vision.camera import open_camera
from rover.vision.markers import MarkerFinder, distance_m


def main() -> None:
    parser = argparse.ArgumentParser(description="ArUco marker size and focal check")
    parser.add_argument("--source", help="webcam index or video path; default = Pi camera")
    parser.add_argument("--at", type=float, help="true camera-to-marker distance in metres")
    args = parser.parse_args()

    camera = open_camera(parse_source(args.source))
    finder = MarkerFinder()
    print(f"check_marker: {camera.backend}, dictionary {config.ARUCO_DICT}, Ctrl+C to stop")
    try:
        while (frame := camera.read()) is not None:
            for marker_id, side in finder.find(frame):
                distance = distance_m(side)
                line = f"marker {marker_id} side {side:.1f} px"
                line += f" distance {distance:.2f} m" if distance is not None else " distance none"
                if args.at:
                    line += f" -> MARKER_FOCAL_PX = {side * args.at / config.MARKER_SIZE_M:.1f}"
                print(line)
    except KeyboardInterrupt:
        print("check_marker: stopped")
    finally:
        camera.close()


if __name__ == "__main__":
    main()
