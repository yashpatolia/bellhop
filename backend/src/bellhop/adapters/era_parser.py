"""Pure parser: a Wikipedia "{year} in music" page -> friendly reminiscence `ContentItem`s.

Input is markdown (or plain text with `*`/`-` bullets), or HTML first run through
`html_to_markdown`. List items under era-friendly sections (events, hit singles, albums, film,
musical theatre, classical/opera) become items. Navigation, references, births, deaths and
anything negative or morbid are dropped: the output feeds friendly chat with elderly residents.
No I/O, no dependencies beyond the standard library.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from itertools import zip_longest

from bellhop.ports.content import ContentItem, ContentKind

BLURB_MAX = 200
_TITLE_MAX = 60

# --- text cleanup -----------------------------------------------------------------------------

_FOOTNOTE_LINK = re.compile(r"\[\\\[[^\]]*?\\\]\]\((?:[^()\s\\]|\\.)*(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"\[((?:[^\]\\]|\\.)*)\]\((?:[^()\s\\]|\\.)*(?:\s+\"[^\"]*\")?\)")
_STRAY_TITLE = re.compile(r"\s\"[^\"]*\"\)")  # leftover `"Page title")` from odd links
_CITATION = re.compile(r"\[\d+\]|\\\[\d+\\\]")
_EMPHASIS = re.compile(r"(?<!\w)_+|_+(?!\w)|\*\*")
_UNESCAPE = re.compile(r"\\(.)")

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_PREFIX = re.compile(rf"^(?:(?:{_MONTHS})(?: \d{{1,2}})?|Christmas|date unknown)\s*[–-]\s*")
_DATE_ONLY = re.compile(rf"^(?:(?:{_MONTHS})(?: \d{{1,2}})?|Christmas|date unknown)$")
_CROSS_LINK = re.compile(r"^\d{4} in .+")

_MORBID = re.compile(
    r"\b(die[sd]?|dying|death|deaths|dead|kill\w*|murder\w*|suicide|funeral|disaster|"
    r"crash\w*|wars?|riots?|bomb\w*|assassinat\w*|drown\w*|shooting|arrest\w*|accident|"
    r"cancer|tragic|tragedy|massacre|victims?|fined|cancel\w*|banned|illness|hospital\w*|"
    r"overdose|lawsuit|sued|sues?|court|trial|judge|litigation|obituary|perished|casualt\w*)\b",
    re.IGNORECASE,
)

# Corporate or procedural news: kept, but ranked after friendlier items of the same section.
_BUSINESS = re.compile(
    r"\b(announces?|marketing|price|prices|merge[rds]?|labels?|signs|signed|contracts?|"
    r"A&R|policy|copyright|royalt\w*|outsell\w*|catalogs?|committee|board|acquire[sd]?|"
    r"nominat\w*|jury|format war|executive|company|corporation)\b",
    re.IGNORECASE,
)
_TRAILING_WORDS = {
    "a", "an", "the", "of", "to", "in", "at", "on", "and", "or", "with", "for", "by",
    "his", "her", "their", "its", "from", "as", "is", "that", "who", "first",
}  # fmt: skip


def _clean(raw: str) -> str:
    text = _FOOTNOTE_LINK.sub("", raw)
    text = _LINK.sub(r"\1", text)
    text = _STRAY_TITLE.sub("", text)
    text = _CITATION.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _UNESCAPE.sub(r"\1", text)
    return " ".join(text.split())


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:–-")
    return cut or text[:limit]


# --- sections ---------------------------------------------------------------------------------

_SKIP = "skip"
_PREAMBLE = "preamble"  # before any heading: shape decides (headings are lost by some crawlers)

_SECTION_RULES: tuple[tuple[str, str], ...] = (
    (r"death|birth|reference|see also|external|notes?$|further reading|bibliograph", _SKIP),
    (r"specific|related|by country|sources|gallery", _SKIP),
    (r"singles|hits|songs|popular music", "song"),
    (r"album", "album"),
    (r"musical film", "musical_film"),
    (r"musical (theat|television)|theat", "stage"),
    (r"^film", "film_score"),
    (r"event|classical|opera|jazz|premiere|composition|award", "event"),
)


def _classify(heading: str) -> str | None:
    """Section style for a heading; None when unknown (caller decides)."""
    name = heading.lower().strip()
    for pattern, style in _SECTION_RULES:
        if re.search(pattern, name):
            return style
    return None


# --- item builders ----------------------------------------------------------------------------

_Built = tuple[ContentKind, str, str] | None  # kind, title, blurb
_ARTIST_ONLY = re.compile(r"^(?:w\.|m\.|w\.m\.)", re.IGNORECASE)
_SEP = re.compile(r"\s[–-]\s")
_SHAPE_SONG = re.compile(r"^\"[^\"]+\"\s*[–-]")


def _title_artist(text: str) -> tuple[str, str | None]:
    quoted = re.match(r"^\"([^\"]+)\"(.*)$", text)
    if quoted:
        title, rest = quoted.group(1).strip(), quoted.group(2).strip()
        rest = re.sub(r"^/\s*\"[^\"]+\"", "", rest).strip()  # "A" / "B" - X
        match = re.match(r"^(?:[–-]|by)\s+(.*)$", rest)
        artist = match.group(1).strip() if match else None
    else:
        parts = _SEP.split(text, maxsplit=1)
        title = parts[0].strip()
        artist = parts[1].strip() if len(parts) == 2 else None
    if artist and _ARTIST_ONLY.match(artist):
        artist = None
    return title, artist


def _song(text: str, year: int) -> _Built:
    title, artist = _title_artist(text)
    if not title:
        return None
    blurb = f"A {year} favourite by {_cap(artist, 80)}." if artist else f"A popular song of {year}."
    return "song", title, blurb


def _album(text: str, year: int) -> _Built:
    title, artist = _title_artist(text)
    if not title or not artist:
        return None
    who = _cap(artist, 80)
    if title.lower() == artist.lower():
        return "song", title, f"{who}'s self-titled album came out in {year}."
    return "song", title, f"{who}'s album {title} came out in {year}."


def _film_score(text: str, year: int) -> _Built:
    parts = _SEP.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    composer, film = parts[0].strip(), parts[1].strip()
    if not composer or not film:
        return None
    return "film", _cap(film, _TITLE_MAX), f"A {year} film with music by {_cap(composer, 80)}."


def _musical_film(text: str, year: int) -> _Built:
    title = re.split(r"\s(?:starring|released)\b|\s[–-]\s", text, maxsplit=1)[0].strip()
    if not title:
        return None
    detail = text if text != title else f"A musical film of {year}."
    return "film", _cap(title, _TITLE_MAX), _cap(detail, BLURB_MAX)


def _natural_title(sentence: str) -> str:
    """A clause or word boundary within the limit, never an ellipsis or a dangling word."""
    window = sentence[: _TITLE_MAX + 1]
    comma = window.rfind(",")
    if comma >= 20:
        return window[:comma]
    words = window.rsplit(" ", 1)[0].split()
    while len(words) > 3 and words[-1].lower().strip(",;:") in _TRAILING_WORDS:
        words.pop()
    return " ".join(words).rstrip(" ,;:–-")


def _event(text: str, year: int) -> _Built:
    body = _DATE_PREFIX.sub("", text).strip()
    if len(body) < 25:
        return None
    first = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0].rstrip(".")
    title = first if len(first) <= _TITLE_MAX else _natural_title(first)
    return "event", title, _cap(body, BLURB_MAX)


def _stage(text: str, year: int) -> _Built:
    parts = _SEP.split(text, maxsplit=1)
    title = re.sub(r"\s*\([^)]*\)\s*$", "", parts[0]).strip()
    if not title:
        return None
    detail = parts[1].strip() if len(parts) == 2 else "stage production"
    return "event", _cap(title, _TITLE_MAX), _cap(f"On stage in {year}: {detail}.", BLURB_MAX)


_BUILDERS = {
    "song": _song,
    "album": _album,
    "film_score": _film_score,
    "musical_film": _musical_film,
    "event": _event,
    "stage": _stage,
}


def _build(style: str, text: str, year: int, italic: bool = False) -> _Built:
    if style == _PREAMBLE:
        if italic or _DATE_PREFIX.match(text):
            style = "album" if italic else "event"
        elif _SHAPE_SONG.match(text):
            style = "song"
        else:
            style = "event" if len(text) >= 40 and text.endswith(".") else _SKIP
        if style == _SKIP:
            return None
    # Rows that lost their heading (crawler output) must keep the shape of the section.
    if style in ("song", "album") and _DATE_PREFIX.match(text):
        return None
    if style in ("song", "album") and not (text.startswith('"') or _SEP.search(text)):
        return None
    return _BUILDERS[style](text, year)


# --- public parser ----------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[*+•]|-(?!-))\s+(.*)$")


def _raw_items(markup: str) -> list[tuple[str, list[str]]]:
    """(section style, raw item lines) in document order, grouped by section."""
    sections: list[tuple[str, list[str]]] = []
    style, current = _PREAMBLE, None
    for line in markup.splitlines():
        heading = _HEADING.match(line)
        if heading and heading.group(2):
            level = len(heading.group(1))
            found = _classify(_clean(heading.group(2)))
            if level == 1:
                style = _PREAMBLE
            elif found is not None:
                style = found
            elif level == 2:
                style = _SKIP
            current = None
            continue
        bullet = _BULLET.match(line)
        if bullet and style != _SKIP:
            if current is None:
                current = []
                sections.append((style, current))
            current.append(bullet.group(1))
        elif line.strip():
            current = None  # a paragraph or table row ends the list
    return sections


def parse_era(markup: str, year: int, id_prefix: str = "era") -> list[ContentItem]:
    """Items for one year, deterministic, interleaving sections so any prefix is varied."""
    per_section: list[list[tuple[ContentKind, str, str]]] = []
    seen: set[str] = set()
    for style, lines in _raw_items(markup):
        built_section: list = []
        for raw in lines:
            text = _clean(raw)
            if not text or _DATE_ONLY.match(text) or _CROSS_LINK.match(text):
                continue
            if _MORBID.search(text):
                continue
            built = _build(style, text, year, raw.lstrip().startswith("_"))
            if built is None:
                continue
            key = re.sub(r"\W+", "", built[1].lower())
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            built_section.append((bool(_BUSINESS.search(text)), built))
        built_section.sort(key=lambda pair: pair[0])  # stable: friendly first, order kept
        built_section = [built for _, built in built_section]
        if built_section:
            per_section.append(built_section)
    ordered = [b for row in zip_longest(*per_section) for b in row if b is not None]
    return [
        ContentItem(
            id=f"{id_prefix}-{year}-{n}",
            kind=kind,
            year=year,
            title=title,
            blurb=_cap(blurb, BLURB_MAX),
        )
        for n, (kind, title, blurb) in enumerate(ordered)
    ]


# --- HTML -> markdown -------------------------------------------------------------------------

_VOID = {"br", "img", "hr", "meta", "link", "input", "wbr"}
_DROP_TAGS = {"style", "script", "table", "sup", "figure", "noscript"}
_DROP_CLASSES = ("reflist", "refbegin", "navbox", "hatnote", "thumb", "mw-editsection", "toc")
_BLOCK = {"p", "div", "ul", "ol", "dl", "dd", "dt", "blockquote"}


class _MarkdownBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._prefix = ""
        self._stack: list[tuple[str, bool]] = []
        self._depth = 0
        self._heading: int | None = None

    def _dropping(self) -> bool:
        return any(drop for _, drop in self._stack)

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.lines.append(f"{self._prefix}{text}" if self._prefix else text)
        self._buf, self._prefix = [], ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        classes = dict(attrs).get("class") or ""
        drop = tag in _DROP_TAGS or any(c in classes.split() for c in _DROP_CLASSES)
        self._stack.append((tag, drop))
        if self._dropping():
            return
        if tag in ("ul", "ol"):
            self._flush()
            self._depth += 1
        elif tag == "li":
            self._flush()
            self._prefix = "  " * (self._depth - 1) + "* "
        elif tag in ("i", "em"):
            self._buf.append("_")
        elif len(tag) == 2 and tag[0] == "h" and tag[1] in "23456":
            self._flush()
            self._heading = int(tag[1])
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                dropped = self._stack[index][1]
                del self._stack[index:]
                break
        else:
            return
        if dropped or self._dropping():
            return
        if tag in ("ul", "ol"):
            self._flush()
            self._depth = max(self._depth - 1, 0)
        elif tag in ("i", "em"):
            self._buf.append("_")
        elif self._heading is not None and tag == f"h{self._heading}":
            text = " ".join("".join(self._buf).split())
            self._buf = []
            if text:
                self.lines.append(f"{'#' * self._heading} {text}")
            self._heading = None
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._dropping():
            self._buf.append(data)


def html_to_markdown(html: str) -> str:
    """Just enough structure (headings, nested bullets, italics) for `parse_era`."""
    builder = _MarkdownBuilder()
    builder.feed(html)
    builder.close()
    builder._flush()
    return "\n".join(builder.lines)
