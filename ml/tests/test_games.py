import random
import subprocess
import sys
import threading

import pytest

from rover import config
from rover.games import Games
from rover.games.bingo import NEXT, Bingo, call_label, make_card, winning_line
from rover.games.draw import AGAIN, FINISH
from rover.games.memory import SHAPES, Memory
from rover.games.tictactoe import (
    BOARD_X,
    BOARD_Y,
    CELL,
    TicTacToe,
    _completes,
    _score,
    next_slip,
    robot_move,
    winner,
)
from rover.touch import ABS_X, ABS_Y, BTN_TOUCH, EV_ABS, EV_KEY, EV_SYN, EVENT, SYN_REPORT, Touch


def centre(button):
    return (button.x0 + button.x1) // 2, (button.y0 + button.y1) // 2


def cell_centre(cell):
    return BOARD_X + (cell % 3) * CELL + CELL // 2, BOARD_Y + (cell // 3) * CELL + CELL // 2


# ---- tic-tac-toe


def test_robot_takes_a_win_then_blocks_then_takes_the_centre():
    rng = random.Random(0)
    assert robot_move(["O", "O", "", "X", "X", "", "", "", ""], 0, rng) == 2  # win beats block
    assert robot_move(["X", "X", "", "", "O", "", "", "", ""], 0, rng) == 2
    assert robot_move(["X", "", "", "", "", "", "", "", ""], 0, rng) == 4


def test_a_full_board_with_no_line_is_a_draw_and_taken_squares_are_ignored():
    game = TicTacToe(random.Random(0), 0)
    game.board = ["X", "O", "X", "X", "O", "O", "O", "X", ""]
    assert game.tap(*cell_centre(0), now=0) == []  # taken
    assert game.tap(*cell_centre(8), now=0) == [("note", "It's a draw. We're well matched!")]
    assert game.over and game.result == "draw" and "a draw" in game.status()


def test_the_robot_moves_after_its_delay():
    game = TicTacToe(random.Random(0), 0)
    game.tap(*cell_centre(0), now=10.0)
    assert game.due == 10.0 + config.TICTACTOE_MOVE_DELAY_S and "your move" in game.status()
    assert game.tap(*cell_centre(1), now=10.1) == []  # not the resident's turn yet
    game.tick(game.due)
    assert game.board.count("O") == 1 and game.due is None


def resident_move(board, rng, takes_win, blocks):
    """A resident model playing X: takes_win None is an expert (perfect play)."""
    empty = [i for i, mark in enumerate(board) if not mark]
    if takes_win is None:
        scores = {i: _score(tuple(board[:i] + ["X"] + board[i + 1 :]), "O") for i in empty}
        return min(scores, key=scores.get)
    if rng.random() < takes_win and (cell := _completes(board, "X")) is not None:
        return cell
    if rng.random() < blocks and (cell := _completes(board, "O")) is not None:
        return cell
    return rng.choice([i for i, mark in enumerate(board) if not mark])


def robot_loss_rate(takes_win, blocks, games=2000):
    rng = random.Random(7)
    slip, lost = config.TICTACTOE_SLIP_START, 0
    for _ in range(games):
        game = TicTacToe(rng, slip)
        while not game.over:
            game.tap(*cell_centre(resident_move(game.board, rng, takes_win, blocks)), now=0)
            if not game.over:
                game.tick(1)
        lost += game.result == "won"
        slip = next_slip(slip, robot_lost=game.result == "won")
    return lost / games


@pytest.mark.parametrize("takes_win, blocks", [(None, None), (1.0, 1.0), (0.7, 0.5)])
def test_the_robot_loses_about_60_percent_to_any_resident(takes_win, blocks):
    assert 0.5 <= robot_loss_rate(takes_win, blocks) <= 0.7


def test_without_slip_the_robot_never_loses():
    rng = random.Random(3)
    for _ in range(300):
        board = [""] * 9
        while winner(board) is None and not all(board):
            board[resident_move(board, rng, 1.0, 1.0)] = "X"
            if winner(board) is None and not all(board):
                board[robot_move(board, 0, rng)] = "O"
        assert winner(board) != "X"


# ---- bingo


def test_bingo_card_columns_and_free_centre():
    card = make_card(random.Random(1))
    for col in range(5):
        numbers = [card[row][col] for row in range(5) if (row, col) != (2, 2)]
        assert all(1 + 15 * col <= n <= 15 + 15 * col for n in numbers) and len(
            set(numbers)
        ) == 4 + (col != 2)
    assert card[2][2] == 0 and call_label(34) == "N 34" and call_label(75) == "O 75"


def test_a_line_is_bingo_and_four_in_a_line_is_not():
    marked = [[False] * 5 for _ in range(5)]
    marked[2][2] = True
    for i in range(4):
        marked[i][4 - i] = True
    assert winning_line(marked) is None
    marked[4][0] = True
    assert winning_line(marked) == [(0, 4), (1, 3), (2, 2), (3, 1), (4, 0)]


def test_bingo_calls_each_number_once():
    game = Bingo(random.Random(2))
    assert sorted(game.pool) == list(range(1, 76))
    game.pool = []
    assert game.tap(*centre(NEXT), now=0) == [("say", "That was every number.")]


def test_a_called_number_on_the_card_is_crossed_off_for_the_resident():
    game = Bingo(random.Random(3))
    mine = game.card[0][0]
    other = next(n for n in range(1, 76) if all(n not in row for row in game.card))
    game.pool = [other, mine]  # calls come off the end
    assert game.tap(*centre(NEXT), now=0) == [("say", f"{call_label(mine)}, you've got that one!")]
    assert game.marked[0][0] and game.just == (0, 0)
    assert game.tap(*centre(NEXT), now=0) == [("say", call_label(other))]
    assert (
        game.just is None and game.tap(30 + 58, 20 + 80 + 48, now=0) == []
    )  # card taps do nothing


def test_bingo_on_a_full_row():
    game = Bingo(random.Random(4))
    game.pool = game.card[0][::-1]
    for _ in range(5):
        lines = game.tap(*centre(NEXT), now=0)
    assert lines[-1] == ("note", "Bingo! That's a full line, well done!") and game.over
    assert game.line == [(0, c) for c in range(5)] and "Bingo!" in game.status()


# ---- memory match


def card_centre(card):
    return 26 + (card % 4) * 156 + 70, 22 + (card // 4) * 191 + 87


def test_memory_deck_is_six_pairs():
    game = Memory(random.Random(5))
    assert sorted(game.deck) == sorted(list(SHAPES) * 2)


def test_memory_mismatch_turns_back_and_finding_all_pairs_ends_it():
    game = Memory(random.Random(6))
    first = game.deck.index("star")
    other = next(i for i, shape in enumerate(game.deck) if shape != "star")
    game.tap(*card_centre(first), now=0)
    game.tap(*card_centre(other), now=0)
    assert game.open == [first, other] and game.due == config.MEMORY_PEEK_S
    game.tick(game.due)
    assert game.open == [] and game.tries == 1
    lines = []
    for shape in SHAPES:
        a, b = (i for i, s in enumerate(game.deck) if s == shape)
        lines += game.tap(*card_centre(a), now=5) + game.tap(*card_centre(b), now=5)
    assert lines == [("note", "You found all the pairs in 7 tries, well done!")] and game.over


# ---- the controller


class FakeScreen:
    def __init__(self, size=(1024, 600)):
        self.size, self.lock, self.images = size, threading.Lock(), []

    def show_image(self, img):
        self.images.append(img)


class FakeEyes:
    def __init__(self, screen):
        self.screen, self.paused = screen, False


def make_games(size=(1024, 600)):
    eyes = FakeEyes(FakeScreen(size))
    games = Games(eyes, random.Random(0))
    games.touchable = True
    posted = []
    games.attach(posted.append)
    return games, eyes, posted


def said(posted):
    return [(kind, line) for kind, line, _ in posted if kind != "GameTouch"]


def test_a_short_touch_does_not_start_the_game_but_a_hold_does():
    games, eyes, posted = make_games()
    assert games.start("tic_tac_toe", now=0.0).startswith("tic-tac-toe is on the screen")
    assert eyes.paused and "start screen" in games.status()
    games.step(0.0)
    games.touch("down", 500, 300)
    games.step(0.1)
    games.touch("up", 500, 300)
    games.step(0.1 + config.GAME_HOLD_S / 2)
    games.step(0.2 + config.GAME_HOLD_S)
    assert games.phase == "intro"
    games.touch("down", 500, 300)
    games.step(2.0)
    games.step(2.0 + config.GAME_HOLD_S)
    assert games.phase == "play" and said(posted) == [("GameSay", TicTacToe.start_line)]
    assert "the resident's turn" in games.status()


def test_nobody_touching_the_start_screen_puts_the_game_away():
    games, eyes, posted = make_games()
    games.start("bingo", now=0.0)
    games.step(config.GAME_INTRO_TIMEOUT_S + 0.1)
    assert games.phase is None and not eyes.paused and games.status() is None
    assert said(posted) == [("GameNote", "No problem, I've put the game away.")]


def start_playing(games, name):
    games.start(name, now=0.0)
    games.touch("down", 10, 10)
    games.step(0.0)
    games.step(config.GAME_HOLD_S)
    assert games.phase == "play"


def test_a_game_left_alone_is_not_redrawn():
    games, eyes, _ = make_games()
    start_playing(games, "memory")
    before = games.redraws
    for t in range(10):
        games.step(5.0 + t)
    assert games.redraws == before and games._wait_s(20.0) is None  # sleeps until a touch


def test_finish_closes_the_game_and_gives_the_face_back():
    games, eyes, posted = make_games()
    start_playing(games, "bingo")
    games.touch("down", *centre(FINISH))
    games.step(3.0)
    assert games.phase is None and not eyes.paused
    assert said(posted)[-1] == ("GameNote", "Thanks for playing with me!")


def test_touches_are_scaled_from_the_screen_to_the_canvas():
    games, _, _ = make_games(size=(512, 300))
    start_playing(games, "bingo")
    x, y = centre(NEXT)
    games.touch("down", x // 2, y // 2)
    games.step(3.0)
    assert len(games.game.called) == 1


def test_tic_tac_toe_through_the_controller_and_play_again_adjusts_the_slip():
    games, _, posted = make_games()
    start_playing(games, "tic_tac_toe")
    games.game.board = ["X", "X", "", "O", "O", "", "", "", ""]
    games.game.slip = 1.0  # sure to slip, but X wins with this tap first
    games.touch("down", *cell_centre(2))
    games.step(3.0)
    assert games.game.result == "won" and said(posted)[-1][0] == "GameNote"
    assert games.slip == pytest.approx(config.TICTACTOE_SLIP_START - config.TICTACTOE_SLIP_STEP)
    games.touch("down", *centre(AGAIN))
    games.step(3.1)
    assert games.game.board == [""] * 9 and games.game.slip == games.slip


def test_start_refuses_an_unknown_game_and_a_missing_screen():
    games, _, _ = make_games()
    assert games.start("chess").startswith("there is no game")
    assert Games(None).start("bingo").startswith("the screen is not available")


# ---- the touch panel


def ev(kind, code, value):
    return EVENT.pack(0, 0, kind, code, value)


def test_touch_turns_input_events_into_down_move_up_in_screen_pixels(monkeypatch):
    seen = []
    touch = Touch([(0, 4095), (0, 4095)], (1024, 600), lambda *a: seen.append(a))
    syn = ev(EV_SYN, SYN_REPORT, 0)
    touch.feed(ev(EV_ABS, ABS_X, 4095) + ev(EV_ABS, ABS_Y, 0) + ev(EV_KEY, BTN_TOUCH, 1) + syn)
    touch.feed(ev(EV_ABS, ABS_X, 2048) + syn)
    touch.feed(syn)  # nothing changed: no event
    touch.feed(ev(EV_KEY, BTN_TOUCH, 0) + syn)
    assert seen == [("down", 1023, 0), ("move", 512, 0), ("up", 512, 0)]
    monkeypatch.setattr(config, "EYES_FLIP", True)
    touch.feed(ev(EV_KEY, BTN_TOUCH, 1) + syn)
    assert seen[-1] == ("down", 511, 599)


def test_the_voice_process_loads_opencv_only_when_a_game_is_drawn():
    code = "import sys, rover.speech.__main__; assert 'cv2' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
