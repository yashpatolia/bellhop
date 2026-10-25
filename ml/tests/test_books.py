import httpx
import pytest

from rover import config
from rover.agent import books

BOOK = """The Project Gutenberg eBook of Tales

*** START OF THE PROJECT GUTENBERG EBOOK TALES ***

TALES

CONTENTS

THE FIRST TALE

THE SECOND TALE

THE FIRST TALE

I.

MARLEY met Mr. Brown at noon. It was _very_ cold. "Hello!" he said. They walked. Then they
stopped and sat on a bench by the long grey river for a good while, and neither of them said a
single word to the other.

[Illustration: a bench]

The end of it.

THE SECOND TALE

This tale is never read, because the first tale ends at its heading and only the first one was
asked for by anyone at all today.

*** END OF THE PROJECT GUTENBERG EBOOK TALES ***
"""
TALE = {
    "title": "The First Tale",
    "author": "Some Author",
    "book": 77,
    "start": "THE FIRST TALE",
    "end": "THE SECOND TALE",
    "minutes": 1,
}
FIRST = ["Marley met Mr. Brown at noon.", "It was very cold.", '"Hello!" he said.', "They walked."]


@pytest.fixture(autouse=True)
def stories(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BOOKS_DIR", tmp_path)
    monkeypatch.setattr(books, "STORIES", {"tale": TALE})
    return tmp_path


def library(seen=None, down=False):
    def handle(request):
        if seen is not None:
            seen.append(request.url.path)
        if down:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, text=BOOK)

    return httpx.MockTransport(handle)


def test_a_story_is_cut_from_its_heading_to_the_next_storys():
    parts = books.chunks(TALE, BOOK)
    assert parts[0] == ["The First Tale, by Some Author."]  # not the contents list's copy
    assert parts[1] == FIRST  # "I." and the capitals are not read as letters
    assert parts[2][0].startswith("Then they stopped")  # a part never runs into the next paragraph
    assert parts[3:] == [["The end of it."]]  # no picture caption, no second tale


def test_a_story_whose_headings_moved_is_not_read(capsys):
    assert books.chunks({**TALE, "end": "THE THIRD TALE"}, BOOK) == []
    reader = books.Reader(None, transport=library())
    books.STORIES["moved"] = {**TALE, "start": "THE LOST TALE"}
    assert reader.open("moved") == "The First Tale could not be opened just now"
    assert (
        "fallback: 'The First Tale' is not in Gutenberg book 77's text" in capsys.readouterr().out
    )
    assert reader.open("no_such_story") == "there is no story called 'no_such_story'"


def test_sentences_and_capitals():
    assert books.SENTENCE_END.split('He said "Go!" Then Dr. Who left. "Bah!" said he.') == [
        'He said "Go!"',
        "Then Dr. Who left.",
        '"Bah!" said he.',
    ]
    assert books.SHOUTED.sub(lambda m: m.group().capitalize(), "CASTLE OF INDOLENCE. I") == (
        "Castle Of Indolence. I"
    )


def read(reader):
    """One part as the visit reads it: spoken to its end, then the bookmark moves."""
    part = reader.next_part()
    reader.done_part()
    return part


def test_a_new_reader_goes_on_from_the_bookmark(stories):
    seen = []
    reader = books.Reader("r1", transport=library(seen))
    assert "from the start" in reader.open("tale")
    assert read(reader) == ["The First Tale, by Some Author."]
    assert reader.next_part() == FIRST
    assert reader.next_part() == FIRST  # cut short (they spoke): it is read again
    reader.done_part()
    assert (stories / "77.txt").exists()

    again = books.Reader("r1", transport=library(seen))
    assert "from where you stopped before (about 50% through)" in again.open("tale")
    assert read(again)[0].startswith("Then they stopped")
    assert seen == ["/cache/epub/77/pg77.txt"]  # downloaded once, then kept on disk
    assert "from the start" in books.Reader("someone else", transport=library()).open("tale")


def test_long_sentences_are_cut_to_fit_a_part(monkeypatch):
    monkeypatch.setattr(config, "READ_PART_WORDS", 5)
    sentence = "One two three, four five six seven eight nine, ten eleven."
    cut = books.pieces(sentence)
    assert cut == ["One two three,", "four five six seven eight", "nine, ten eleven."]
    assert " ".join(cut) == sentence
    parts = books.chunks(TALE, BOOK)
    assert all(len(" ".join(part).split()) <= 5 for part in parts[1:])


def test_pause_resume_and_status():
    reader = books.Reader(None, transport=library())
    assert reader.status() is None
    reader.open("tale")
    assert reader.pause() is True and not reader.reading
    assert reader.status() == (
        "The First Tale by Some Author, stopped about 0% through. You have stopped reading."
    )
    assert reader.pause() is False
    assert reader.open("tale").startswith("going on with")  # no new download
    while read(reader):
        pass
    assert reader.status() == "You read The First Tale by Some Author to the end."
    reader.resume()
    assert not reader.reading
    assert "from the start" in reader.open("tale")  # finished: a new reading begins


def test_a_long_stretch_with_no_word_stops_the_reading(monkeypatch):
    reader = books.Reader(None, transport=library())
    reader.open("tale")
    assert read(reader)
    monkeypatch.setattr(config, "READ_MAX_S", 0.0)
    assert read(reader) == [config.READ_STOP_LINE]
    assert not reader.reading and reader.next_part() == []
    monkeypatch.setattr(config, "READ_MAX_S", 900.0)
    reader.open("tale")  # asked again: it goes on where it stopped
    assert read(reader) == FIRST


def test_a_bookmark_that_cannot_be_saved_does_not_stop_the_story(monkeypatch, capsys):
    reader = books.Reader(None, transport=library())
    reader.open("tale")

    def full_disk(path, text):
        raise OSError("no space")

    monkeypatch.setattr(books, "_write", full_disk)
    assert read(reader) and read(reader) == FIRST
    assert "fallback: bookmark not saved (OSError)" in capsys.readouterr().out


def test_the_library_being_down_is_said_plainly(capsys):
    reader = books.Reader(None, transport=library(down=True))
    assert reader.open("tale") == "the story library could not be reached just now"
    assert "fallback: the story library could not be reached (ConnectError)" in (
        capsys.readouterr().out
    )
    assert not reader.reading and reader.status() is None
