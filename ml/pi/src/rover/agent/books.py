"""Short stories read aloud: public-domain texts from Project Gutenberg, a few sentences at a time.

Each story is cut out of its Gutenberg book, from its own heading to the next story's, so one
sitting can finish it. A book is downloaded once into runs/books/, and a bookmark per resident
(bookmarks.json there) lets a story go on at the next visit. scripts/check_stories.py checks them.
"""

from __future__ import annotations

import json
import os
import re
import time

import httpx

from rover import config


def _story(title: str, author: str, book: int, start: str, end: str, minutes: int) -> dict:
    return {"title": title, "author": author, "book": book, "start": start, "end": end,
            "minutes": minutes}  # fmt: skip


# start: the story's heading in the book's text; end: the next story's heading (not read)
STORIES = {
    "the_gift_of_the_magi": _story(
        "The Gift of the Magi", "O. Henry", 2776,
        "THE GIFT OF THE MAGI", "A COSMOPOLITE IN A CAFÉ", 14,
    ),
    "after_twenty_years": _story(
        "After Twenty Years", "O. Henry", 2776, "AFTER TWENTY YEARS", "LOST ON DRESS PARADE", 8
    ),
    "the_cop_and_the_anthem": _story(
        "The Cop and the Anthem", "O. Henry", 2776,
        "THE COP AND THE ANTHEM", "AN ADJUSTMENT OF NATURE", 15,
    ),
    "the_ransom_of_red_chief": _story(
        "The Ransom of Red Chief", "O. Henry", 1595,
        "VIII THE RANSOM OF RED CHIEF", "IX THE MARRY MONTH OF MAY", 28,
    ),
    "the_happy_prince": _story(
        "The Happy Prince", "Oscar Wilde", 902,
        "The Happy Prince.", "The Nightingale and the Rose.", 23,
    ),
    "the_selfish_giant": _story(
        "The Selfish Giant", "Oscar Wilde", 902, "The Selfish Giant.", "The Devoted Friend.", 11
    ),
    "the_open_window": _story(
        "The Open Window", "Saki", 269, "THE OPEN WINDOW", "THE TREASURE SHIP", 8
    ),
    "a_scandal_in_bohemia": _story(
        "A Scandal in Bohemia", "Arthur Conan Doyle", 1661,
        "I. A SCANDAL IN BOHEMIA", "II. THE RED-HEADED LEAGUE", 57,
    ),
    "the_red_headed_league": _story(
        "The Red-Headed League", "Arthur Conan Doyle", 1661,
        "II. THE RED-HEADED LEAGUE", "III. A CASE OF IDENTITY", 61,
    ),
    "the_blue_carbuncle": _story(
        "The Adventure of the Blue Carbuncle", "Arthur Conan Doyle", 1661,
        "VII. THE ADVENTURE OF THE BLUE CARBUNCLE", "VIII. THE ADVENTURE OF THE SPECKLED BAND", 52,
    ),
    "rip_van_winkle": _story(
        "Rip Van Winkle", "Washington Irving", 60976, "RIP VAN WINKLE", "NOTE", 41
    ),
    "the_legend_of_sleepy_hollow": _story(
        "The Legend of Sleepy Hollow", "Washington Irving", 41,
        "FOUND AMONG THE PAPERS OF THE LATE DIEDRICH KNICKERBOCKER.", "POSTSCRIPT.", 79,
    ),
}

START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG[^\n]*$", re.M | re.I)
END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", re.M | re.I)
SECTION = re.compile(r"^[IVXLC]+\.$")  # "II.": a story's numbered part, not read out
SHOUTED = re.compile(r"\b[A-Z]{2,}\b")  # "HIGH above the city": capitals said as a word
# a sentence ends at . ! or ? (or one before a closing quote) when a capital comes next, so
# '"Hello!" he said.' stays whole; never after Mr. Mrs. Dr. or St.
SENTENCE_END = re.compile(
    r"(?:(?<!\bMr\.)(?<!\bMrs\.)(?<!\bDr\.)(?<!\bSt\.)(?<=[.!?])|(?<=[.!?][\"”’']))"
    r"\s+(?=[\"“‘'(]?[A-Z])"
)


def paragraphs(text: str) -> list[str]:
    """The book's paragraphs between Gutenberg's start and end markers, unwrapped."""
    text = text.replace("\r\n", "\n")
    start, end = START.search(text), END.search(text)
    body = text[start.end() if start else 0 : end.start() if end else len(text)]
    paras = []
    for block in re.split(r"\n\s*\n", body):
        para = " ".join(block.replace("_", "").replace("--", ", ").split())  # _italics_
        if para and not para.startswith("["):  # [Illustration: ...], [Picture: ...]
            paras.append(para)
    return paras


def story_paragraphs(story: dict, text: str) -> list[str]:
    """The story's own paragraphs, or [] if its headings are not in the text. The heading counts
    only with prose just after it, so a contents list or title page is skipped."""
    paras = paragraphs(text)
    for i, para in enumerate(paras):
        ahead = paras[i + 1 : i + 1 + config.READ_LOOKAHEAD]
        if para == story["start"] and any(len(p.split()) >= config.READ_FIRST_WORDS for p in ahead):
            end = next((j for j in range(i + 1, len(paras)) if paras[j] == story["end"]), None)
            return [] if end is None else [p for p in paras[i + 1 : end] if not SECTION.match(p)]
    return []


def pieces(sentence: str) -> list[str]:
    """A sentence longer than READ_PART_WORDS, cut after its last comma (or ; or :) that fits,
    or at the limit if none does."""
    words, out = sentence.split(), []
    while len(words) > config.READ_PART_WORDS:
        fits = [i for i in range(1, config.READ_PART_WORDS + 1) if words[i - 1][-1] in ",;:"]
        cut = fits[-1] if fits else config.READ_PART_WORDS
        out.append(" ".join(words[:cut]))
        words = words[cut:]
    return [*out, " ".join(words)] if words else out


def chunks(story: dict, text: str) -> list[list[str]]:
    """The parts to read in turn: the title, then whole sentences up to READ_PART_WORDS. A part
    never runs into the next paragraph."""
    paras = story_paragraphs(story, text)
    if not paras:
        return []
    out = [[f"{story['title']}, by {story['author']}."]]
    for para in paras:
        part: list[str] = []
        for sentence in SENTENCE_END.split(SHOUTED.sub(lambda m: m.group().capitalize(), para)):
            for piece in pieces(sentence):
                if part and len(" ".join([*part, piece]).split()) > config.READ_PART_WORDS:
                    out.append(part)
                    part = []
                part.append(piece)
        if part:
            out.append(part)
    return out


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def fetch(book: int, transport: httpx.BaseTransport | None = None) -> str:
    """A Gutenberg book's text, downloaded once."""
    path = config.BOOKS_DIR / f"{book}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        pass
    with httpx.Client(
        transport=transport, timeout=config.BOOK_TIMEOUT_S, follow_redirects=True
    ) as client:
        response = client.get(config.GUTENBERG_TEXT_URL.format(id=book))
        response.raise_for_status()
    _write(path, response.text)
    return response.text


def _bookmarks() -> dict:
    try:
        marks = json.loads((config.BOOKS_DIR / "bookmarks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return marks if isinstance(marks, dict) else {}


class Reader:
    """The story open in this visit. The worker opens, reads and pauses it; the main thread only
    reads `reading` to know when the next few sentences are due."""

    def __init__(self, who: str | None, transport: httpx.BaseTransport | None = None) -> None:
        self.who = who or "anyone"
        self.story: str | None = None  # a STORIES key
        self.parts: list[list[str]] = []
        self.at = 0  # the next part to read
        self.reading = False
        self.asked_at = 0.0  # when read_book was last used; READ_MAX_S after it, it stops
        self._transport = transport

    def name(self) -> str:
        story = STORIES[self.story] if self.story else {}
        return f"{story.get('title')} by {story.get('author')}"

    def through(self) -> str:
        return f"about {round(100 * self.at / max(len(self.parts), 1))}% through"

    def open(self, key: str) -> str:
        """Start (or go on with) a story; the tool's answer for Claude."""
        then = "Say one short sentence: the reading starts when you finish, stops when they speak."
        if key not in STORIES:
            return f"there is no story called {key!r}"
        if key == self.story and self.at < len(self.parts):
            self.reading, self.asked_at = True, time.monotonic()
            return f"going on with {self.name()}, {self.through()}. {then}"
        story = STORIES[key]
        try:
            parts = chunks(story, fetch(story["book"], self._transport))
        except (httpx.HTTPError, OSError) as exc:
            print(f"fallback: the story library could not be reached ({type(exc).__name__})")
            return "the story library could not be reached just now"
        if not parts:
            print(f"fallback: {story['title']!r} is not in Gutenberg book {story['book']}'s text")
            return f"{story['title']} could not be opened just now"
        self.story, self.parts = key, parts
        saved = _bookmarks().get(self._key(), 0)
        self.at = saved if isinstance(saved, int) and 0 < saved < len(parts) else 0
        self.reading, self.asked_at = True, time.monotonic()
        print(f"books: reading {key} from part {self.at} of {len(parts)}")
        where = f"from where you stopped before ({self.through()})" if self.at else "from the start"
        return f"now reading {self.name()} aloud, {where}. {then}"

    def next_part(self) -> list[str]:
        """The next few sentences to read ([] when not reading); done_part() moves past them."""
        if not self.reading or self.at >= len(self.parts):
            self.reading = False
            return []
        if time.monotonic() - self.asked_at >= config.READ_MAX_S:
            print(f"books: {config.READ_MAX_S:g} s with no word from them; stopping")
            self.reading = False
            return [config.READ_STOP_LINE]
        return self.parts[self.at]

    def done_part(self) -> None:
        """The part was read to its end: the bookmark moves past it. A part cut short is read
        again when they want more."""
        if not self.reading:  # the stop line, or they spoke
            return
        self.at += 1
        self.reading = self.at < len(self.parts)
        marks = _bookmarks()
        marks[self._key()] = self.at
        try:
            _write(config.BOOKS_DIR / "bookmarks.json", json.dumps(marks))
        except OSError as exc:  # the story still goes on; only the next visit's place is lost
            print(f"fallback: bookmark not saved ({type(exc).__name__})")

    def pause(self) -> bool:
        """Stop after the part being read; True if it was reading."""
        was, self.reading = self.reading, False
        return was

    def resume(self) -> None:
        self.reading = self.story is not None and self.at < len(self.parts)

    def status(self) -> str | None:
        """For the prompt: which story is open and where, or None."""
        if self.story is None:
            return None
        if self.at >= len(self.parts):
            return f"You read {self.name()} to the end."
        doing = "You are reading it aloud now." if self.reading else "You have stopped reading."
        return f"{self.name()}, stopped {self.through()}. {doing}"

    def _key(self) -> str:
        return f"{self.who}:{self.story}"
