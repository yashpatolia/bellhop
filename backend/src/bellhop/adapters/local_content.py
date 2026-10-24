"""Curated offline reminiscence items (1940s-1970s) so the demo needs no network."""

from __future__ import annotations

from bellhop.ports.content import ContentItem

_ITEMS: tuple[ContentItem, ...] = (
    ContentItem(
        id="local-01",
        kind="song",
        year=1941,
        title="Chattanooga Choo Choo",
        blurb="Glenn Miller's swinging train song topped the charts.",
    ),
    ContentItem(
        id="local-02",
        kind="film",
        year=1942,
        title="Casablanca",
        blurb="Bogart and Bergman in the wartime romance everyone queued to see.",
    ),
    ContentItem(
        id="local-03",
        kind="song",
        year=1944,
        title="Don't Fence Me In",
        blurb="Bing Crosby and the Andrews Sisters sang it on every radio.",
    ),
    ContentItem(
        id="local-04",
        kind="news",
        year=1945,
        title="Victory in Europe",
        blurb="Crowds filled the streets to celebrate the end of the war.",
    ),
    ContentItem(
        id="local-05",
        kind="film",
        year=1946,
        title="It's a Wonderful Life",
        blurb="Frank Capra's story of George Bailey reached cinemas.",
    ),
    ContentItem(
        id="local-06",
        kind="song",
        year=1947,
        title="Heartaches",
        blurb="A slow dance favourite of the late forties.",
    ),
    ContentItem(
        id="local-07",
        kind="event",
        year=1948,
        title="The Long-Playing Record",
        blurb="Columbia introduced the LP, and music at home changed.",
    ),
    ContentItem(
        id="local-08",
        kind="film",
        year=1950,
        title="Cinderella",
        blurb="Disney's glass-slipper classic delighted families.",
    ),
    ContentItem(
        id="local-09",
        kind="event",
        year=1951,
        title="I Love Lucy Premieres",
        blurb="Lucille Ball began making the whole country laugh.",
    ),
    ContentItem(
        id="local-10",
        kind="song",
        year=1952,
        title="You Belong to Me",
        blurb="Jo Stafford's gentle ballad was a huge hit.",
    ),
    ContentItem(
        id="local-11",
        kind="news",
        year=1953,
        title="Coronation of Queen Elizabeth II",
        blurb="Families gathered around small television sets to watch.",
    ),
    ContentItem(
        id="local-12",
        kind="song",
        year=1954,
        title="Sh-Boom",
        blurb="One of the first records to cross over from rhythm and blues.",
    ),
    ContentItem(
        id="local-13",
        kind="film",
        year=1955,
        title="Rebel Without a Cause",
        blurb="James Dean became the face of a restless generation.",
    ),
    ContentItem(
        id="local-14",
        kind="song",
        year=1956,
        title="Heartbreak Hotel",
        blurb="Elvis Presley's first number one record.",
    ),
    ContentItem(
        id="local-15",
        kind="film",
        year=1958,
        title="South Pacific",
        blurb="The much-loved musical filled picture houses.",
    ),
    ContentItem(
        id="local-16",
        kind="song",
        year=1958,
        title="Volare",
        blurb="Domenico Modugno's song had everyone humming along.",
    ),
    ContentItem(
        id="local-17",
        kind="event",
        year=1959,
        title="Alaska and Hawaii Join the Union",
        blurb="The flag gained its 49th and 50th stars.",
    ),
    ContentItem(
        id="local-18",
        kind="film",
        year=1960,
        title="Psycho",
        blurb="Hitchcock's thriller had audiences gasping.",
    ),
    ContentItem(
        id="local-19",
        kind="song",
        year=1961,
        title="Moon River",
        blurb="Audrey Hepburn sang it in Breakfast at Tiffany's.",
    ),
    ContentItem(
        id="local-20",
        kind="event",
        year=1962,
        title="John Glenn Orbits the Earth",
        blurb="The first American in orbit, followed on every wireless.",
    ),
    ContentItem(
        id="local-21",
        kind="news",
        year=1963,
        title="A Nation Mourns",
        blurb="President Kennedy's death was felt in every household.",
    ),
    ContentItem(
        id="local-22",
        kind="song",
        year=1964,
        title="I Want to Hold Your Hand",
        blurb="The Beatles arrived and the world danced.",
    ),
    ContentItem(
        id="local-23",
        kind="film",
        year=1965,
        title="The Sound of Music",
        blurb="Julie Andrews singing in the Alps won hearts everywhere.",
    ),
    ContentItem(
        id="local-24",
        kind="event",
        year=1966,
        title="England Wins the World Cup",
        blurb="Wembley erupted at the final whistle.",
    ),
    ContentItem(
        id="local-25",
        kind="song",
        year=1967,
        title="Respect",
        blurb="Aretha Franklin's anthem rang out across the dance floors.",
    ),
    ContentItem(
        id="local-26",
        kind="news",
        year=1969,
        title="Man Walks on the Moon",
        blurb="Neil Armstrong's first steps were watched around the world.",
    ),
    ContentItem(
        id="local-27",
        kind="song",
        year=1970,
        title="Bridge Over Troubled Water",
        blurb="Simon and Garfunkel's gentle ballad topped the charts.",
    ),
    ContentItem(
        id="local-28",
        kind="film",
        year=1972,
        title="The Godfather",
        blurb="The film everyone was talking about.",
    ),
    ContentItem(
        id="local-29",
        kind="song",
        year=1975,
        title="Bohemian Rhapsody",
        blurb="Queen's six-minute epic took over the radio.",
    ),
    ContentItem(
        id="local-30",
        kind="film",
        year=1977,
        title="Star Wars",
        blurb="Lines wrapped around the block for a galaxy far away.",
    ),
)


class LocalContentFeed:
    """Deterministic: items from ages 15-25, nearest to age 20 first, ties by id."""

    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        lo, hi, mid = birth_year + 15, birth_year + 25, birth_year + 20
        window = [i for i in _ITEMS if lo <= i.year <= hi]
        window.sort(key=lambda i: (abs(i.year - mid), i.id))
        return window[: max(limit, 0)]
