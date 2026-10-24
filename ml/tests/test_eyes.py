import numpy as np
import pytest

from rover import config
from rover.eyes import EXPRESSIONS, Eyes, H, Screen, W, draw


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
