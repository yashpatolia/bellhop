import numpy as np

from rover import config
from rover.eyes import EXPRESSIONS, Eyes, H, Oled, W, draw


class FakeBus:
    def __init__(self):
        self.writes = []

    def write_i2c_block_data(self, address, control, data):
        self.writes.append((control, list(data)))

    def data_bytes(self):
        return sum(len(data) for control, data in self.writes if control == 0x40)


def test_every_expression_draws_two_mirrored_eyes():
    for name, (_, _, dx, _, _) in EXPRESSIONS.items():
        frame = draw(name)
        assert frame.shape == (H, W) and frame[:, : W // 2].any() and frame[:, W // 2 :].any()
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
    monkeypatch.setattr(config, "OLED_FLIP", True)
    assert (draw("cheerful") == upright[::-1, ::-1]).all()


def test_oled_packs_pages_and_only_resends_what_changed(monkeypatch):
    monkeypatch.setattr(config, "OLED_COLUMN_OFFSET", 2)
    bus = FakeBus()
    oled = Oled(bus)
    bus.writes.clear()
    frame = np.zeros((H, W), bool)
    frame[9, 5] = True  # page 1, bit 1
    oled.show(frame)
    assert bus.data_bytes() == W * H // 8
    page1 = [data for control, data in bus.writes if control == 0x40][4:8]
    assert sum(page1, [])[5] == 0b10
    assert (0x00, [0xB1, 0x02, 0x10]) in bus.writes  # page 1, column offset 2
    bus.writes.clear()
    oled.show(frame)
    assert bus.writes == []
    frame[60, 0] = True
    oled.show(frame)
    assert bus.data_bytes() == W and bus.writes[0] == (0x00, [0xB7, 0x02, 0x10])


def test_a_tone_holds_then_the_face_returns_to_its_base(monkeypatch):
    eyes = Eyes()
    eyes.base = "listening"
    eyes.feel("excited")
    now = eyes._mood_until - 0.1
    assert eyes.expression(now) == "excited"
    assert eyes.expression(now + 0.2) == "listening"
    eyes.frame(now)  # draws without an OLED
