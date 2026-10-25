import threading
import time

import numpy as np
import pytest

from rover import config
from rover.eyes import EXPRESSIONS, Eyes, H, Screen, W, WindowScreen, draw


@pytest.mark.parametrize("scale", [1, 8])
def test_every_expression_draws_two_mirrored_eyes(scale):
    half = W * scale // 2
    for name, (_, _, dx, _, _) in EXPRESSIONS.items():
        frame = draw(name, scale=scale)
        assert frame.shape == (H * scale, W * scale)
        assert frame[:, :half].any() and frame[:, half:].any()
        if dx == 0:
            assert (frame == frame[:, ::-1]).all(), name


def test_happy_eyes_are_domes_with_the_bottom_carved_out():
    centre = W // 2 + 24  # right eye's middle column
    round_eye, happy = draw("listening")[:, centre], draw("cheerful")[:, centre]
    lit = np.flatnonzero(happy)
    assert round_eye[H // 2 + 4] and not happy[H // 2 + 4]  # dark below the dome
    assert lit.min() < H // 2 - 8  # the dome is on top


def test_blink_squashes_the_eyes_to_a_line():
    rows = np.flatnonzero(draw("idle", blink=1.0).any(axis=1))
    assert 0 < len(rows) <= 3


def test_flip_turns_the_frame_upside_down(monkeypatch):
    upright = draw("cheerful")
    monkeypatch.setattr(config, "EYES_FLIP", True)
    assert (draw("cheerful") == upright[::-1, ::-1]).all()


@pytest.mark.parametrize("bits, cyan", [(16, 0x07FF), (32, 0x00FFFF)])
def test_screen_draws_the_face_centred_in_cyan(tmp_path, bits, cyan):
    width, height, dtype = 1024, 600, {16: np.uint16, 32: np.uint32}[bits]
    (tmp_path / "virtual_size").write_text(f"{width},{height}\n")
    (tmp_path / "bits_per_pixel").write_text(f"{bits}\n")
    (tmp_path / "stride").write_text(f"{width * bits // 8}\n")
    fb = tmp_path / "fb0"
    fb.write_bytes(bytes(width * height * bits // 8))
    screen = Screen(str(fb), sysfs=tmp_path)
    assert screen.scale == 8  # 1024x512, 44 rows of black above and below
    screen.show(draw("idle", scale=screen.scale))
    pixels = np.fromfile(fb, dtype).reshape(height, width)
    assert pixels[300, 704] == cyan  # middle of the right eye
    assert not pixels[:44].any() and not pixels[-44:].any() and pixels[44:-44, 0].max() == 0
    assert set(np.unique(pixels)) == {0, cyan}
    screen.off()
    assert not np.fromfile(fb, dtype).any()


def test_a_tone_holds_then_the_face_returns_to_its_base(monkeypatch):
    eyes = Eyes()
    eyes.base = "listening"
    eyes.feel("excited")
    now = eyes._mood_until - 0.1
    assert eyes.expression(now) == "excited"
    assert eyes.expression(now + 0.2) == "listening"
    eyes.frame(now)  # draws without a screen
    until = time.monotonic() + 10  # a long sentence: held to its end, not to its start
    eyes.feel("calm", until)
    assert eyes.expression(until + config.EYES_MOOD_HOLD_S - 0.1) == "calm"


def fake_fb(tmp_path, bits):
    width, height = 1024, 600
    (tmp_path / "virtual_size").write_text(f"{width},{height}\n")
    (tmp_path / "bits_per_pixel").write_text(f"{bits}\n")
    (tmp_path / "stride").write_text(f"{width * bits // 8}\n")
    fb = tmp_path / "fb0"
    fb.write_bytes(bytes(width * height * bits // 8))
    return Screen(str(fb), sysfs=tmp_path), fb


@pytest.mark.parametrize("bits, red", [(16, 0xF800), (32, 0xFF0000)])
def test_show_image_packs_a_bgr_picture_for_the_framebuffer(tmp_path, bits, red):
    screen, fb = fake_fb(tmp_path, bits)
    image = np.zeros((600, 1024, 3), np.uint8)
    image[:, :, 2] = 255  # red in BGR
    screen.show_image(image)
    pixels = np.fromfile(fb, {16: np.uint16, 32: np.uint32}[bits]).reshape(600, 1024)
    colour = pixels & (0xFFFFFF if bits == 32 else 0xFFFF)  # 32 bpp also sets the alpha byte
    assert set(np.unique(colour)) == {red}


def test_paused_eyes_leave_the_screen_to_the_game(tmp_path):
    screen, fb = fake_fb(tmp_path, 16)
    eyes = Eyes(screen)
    eyes.paused = True
    eyes.tick()
    assert not np.fromfile(fb, np.uint16).any()
    eyes.paused = False
    eyes.tick()
    assert np.fromfile(fb, np.uint16).any()


def test_the_desktop_window_shows_the_face_and_then_a_game():
    screen = WindowScreen((1024, 600))  # not started: no window, just the pictures it would show
    screen.show(draw("idle", scale=screen.scale))
    lit = screen.picture.any(axis=2)
    assert screen.scale == 8 and lit[:, :512].any() and lit[:, 512:].any()
    assert set(map(tuple, screen.picture[lit])) == {config.EYES_RGB[::-1]}
    screen.show_image(np.full((300, 512, 3), 7, np.uint8))  # resized to the screen
    assert screen.picture.shape == (600, 1024, 3) and (screen.picture == 7).all()
    screen.off()
    assert not screen.picture.any()


def test_only_a_long_swipe_down_from_the_top_edge_closes_the_window(monkeypatch):
    import cv2

    monkeypatch.setattr(config, "EYES_EXIT_EDGE_PX", 60)
    monkeypatch.setattr(config, "EYES_EXIT_SWIPE_PX", 250)
    screen, quits = WindowScreen((1024, 600)), []
    screen.quit = lambda: quits.append(1)

    def swipe(y0, y1):
        screen.on_mouse(cv2.EVENT_LBUTTONDOWN, 500, y0, 0)
        screen.on_mouse(cv2.EVENT_MOUSEMOVE, 500, (y0 + y1) // 2, cv2.EVENT_FLAG_LBUTTON)
        screen.on_mouse(cv2.EVENT_LBUTTONUP, 500, y1, 0)

    swipe(200, 590)  # starts mid-screen: a resident's swipe
    swipe(10, 150)  # from the edge, but short
    swipe(300, 300)  # a tap
    assert quits == []
    swipe(5, 400)
    assert quits == [1]


class CountingScreen:
    scale = 1

    def __init__(self):
        self.lock = threading.Lock()
        self.shown = 0

    def show(self, frame):
        self.shown += 1


def test_a_still_face_is_written_once_and_repainted_after_a_game(monkeypatch):
    screen = CountingScreen()
    eyes = Eyes(screen)
    monkeypatch.setattr(eyes, "pose", lambda now: ("idle", 0.0, (0, 0), 0))
    eyes.tick()
    eyes.tick()
    assert screen.shown == 1
    eyes.paused = True  # a game drew over it
    eyes.tick()
    eyes.paused = False
    eyes.tick()
    assert screen.shown == 2


def test_thinking_eyes_look_up_and_drift_side_to_side():
    eyes = Eyes()
    eyes.base = "thinking"
    looks = {eyes.pose(now)[2] for now in (0.0, 0.75, 1.5, 2.25)}
    assert len(looks) == 3 and {dy for _, dy in looks} == {0}
    assert EXPRESSIONS["thinking"][3] < 0  # up
