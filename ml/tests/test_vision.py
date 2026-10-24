import math

import cv2
import numpy as np
import pytest

from rover import config
from rover.vision.faces import SeenCounter, is_facing, to_frame
from rover.vision.markers import MarkerFinder, distance_m, side_px
from rover.vision.people import Target, choose_target


def test_generated_marker_is_found_with_room_and_distance():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
    marker = cv2.aruco.generateImageMarker(dictionary, 201, 200)
    canvas = np.full((480, 640, 3), 255, np.uint8)
    canvas[140:340, 220:420] = marker[:, :, None]

    found = MarkerFinder().detect(canvas)

    assert len(found) == 1
    assert found[0]["id"] == 201
    assert found[0]["room"] == config.MARKER_ROOMS[201]
    expected = config.MARKER_SIZE_M * config.MARKER_FOCAL_PX / 200
    assert found[0]["distance_m"] == pytest.approx(expected, rel=0.05)
    assert found[0]["x"] == pytest.approx(0.0, abs=0.02)


def test_marker_on_the_right_has_positive_x():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
    canvas = np.full((480, 640, 3), 255, np.uint8)
    canvas[140:340, 400:600] = cv2.aruco.generateImageMarker(dictionary, 202, 200)[:, :, None]

    (found,) = MarkerFinder().detect(canvas)

    assert found["x"] == pytest.approx(500 / 320 - 1, abs=0.02)


def test_blank_frame_has_no_markers():
    assert MarkerFinder().detect(np.full((480, 640, 3), 255, np.uint8)) == []


def test_distance_math():
    assert distance_m(100.0) == pytest.approx(config.MARKER_SIZE_M * config.MARKER_FOCAL_PX / 100)
    assert side_px(np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)) == pytest.approx(10)


@pytest.mark.parametrize("side", [0.0, -5.0, math.nan, math.inf])
def test_bad_side_gives_no_distance(side):
    assert distance_m(side) is None


def _face_row(nose_x: float) -> np.ndarray:
    row = np.zeros(15, np.float32)
    row[4:8] = [40, 50, 80, 50]  # right eye, left eye
    row[8:10] = [nose_x, 70]
    return row


def test_is_facing():
    assert is_facing(_face_row(60)) is True
    assert is_facing(_face_row(60 + 40 * config.FACE_SYMMETRY + 2)) is False
    assert is_facing(np.zeros(15, np.float32)) is False  # eyes on top of each other


def test_face_row_maps_back_to_frame_without_touching_size():
    row = np.arange(15, dtype=np.float64)
    shifted = to_frame(row, 100, 50)
    assert list(shifted[0:4]) == [100, 51, 2, 3]
    assert list(shifted[4:14]) == [104, 55, 106, 57, 108, 59, 110, 61, 112, 63]
    assert shifted[14] == 14


def test_seen_counter_three_of_five():
    counter = SeenCounter(3, 5)
    pushes = [counter.push(seen) for seen in [True, False, True, False, True]]
    assert pushes == [False, False, False, False, True]
    assert counter.push(False) is False  # window is now F T F T F


def test_target_keeps_its_id_and_follows_its_box():
    target = choose_target({1: [0, 0, 100, 200], 2: [300, 0, 500, 400]}, None, now=0.0)
    assert target.id == 2  # largest box when nothing is locked
    target = choose_target({1: [0, 0, 100, 200], 2: [310, 0, 510, 400]}, target, now=0.1)
    assert (target.id, target.box) == (2, [310, 0, 510, 400])


def test_target_coasts_then_drops():
    target = Target(5, [100, 100, 200, 300], seen_at=0.0)
    coasting = choose_target({}, target, now=config.COAST_S - 0.1)
    assert (coasting.id, coasting.box) == (5, [100, 100, 200, 300])
    assert choose_target({}, target, now=config.COAST_S + 0.1) is None


def test_target_relocks_only_near_last_box_while_coasting():
    target = Target(5, [100, 100, 200, 300], seen_at=0.0)
    far = {7: [500, 100, 600, 300]}
    assert choose_target(far, target, now=0.5).id == 5  # far box ignored, still coasting
    near = {7: [500, 100, 600, 300], 8: [150, 110, 250, 310]}
    assert choose_target(near, target, now=0.5).id == 8
    assert choose_target(far, target, now=config.COAST_S + 0.1).id == 7  # coast over: take it
