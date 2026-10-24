from pathlib import Path

from bellhop.adapters.era_parser import html_to_markdown, parse_era

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL = (FIXTURES / "1955_in_music.md").read_text()


def titles(items):
    return [i.title for i in items]


def test_real_1955_page_gives_sensible_items():
    items = parse_era(REAL, 1955)
    assert len(items) >= 5
    assert all(i.year == 1955 for i in items)
    assert {"song", "event"} <= {i.kind for i in items}


def test_no_wikipedia_navigation_junk():
    for i in parse_era(REAL, 1955):
        assert "Wikipedia" not in i.title + i.blurb
        assert "http" not in i.title + i.blurb
        assert "](" not in i.title + i.blurb
        assert "1955 in British music" not in i.title


def test_deaths_riots_and_citations_are_excluded():
    text = " ".join(i.title + " " + i.blurb for i in parse_era(REAL, 1955))
    for name in ("Carmen Miranda", "Arthur Honegger", "Ruth Vincent", "soprano, 78"):
        assert name not in text
    assert "riot" not in text.lower()
    assert "\\[" not in text


def test_songs_and_albums_are_titled_without_markup():
    items = parse_era(REAL, 1955)
    assert "Earth Angel" in titles(items)
    assert "The Waltz Queen" in titles(items)
    song = next(i for i in items if i.title == "Earth Angel")
    assert song.kind == "song" and "The Penguins" in song.blurb


def test_blurbs_capped_and_ids_unique_and_prefixed():
    items = parse_era(REAL, 1955, id_prefix="wiki")
    assert all(0 < len(i.blurb) <= 200 for i in items)
    assert len({i.id for i in items}) == len(items)
    assert all(i.id.startswith("wiki-1955-") for i in items)


def test_duplicate_titles_are_removed():
    titles_seen = [i.title.lower() for i in parse_era(REAL, 1955)]
    assert len(titles_seen) == len(set(titles_seen))


def test_deterministic_and_varied_leading_items():
    assert parse_era(REAL, 1955) == parse_era(REAL, 1955)
    assert len({i.kind for i in parse_era(REAL, 1955)[:3]}) >= 2


def test_headings_choose_kind_and_skip_unfriendly_sections():
    md = """# 1960 in music

## Events

*   [March 3](https://x/y "y") – Elvis returns home to a [warm welcome](https://x/z) from fans.

## Top hits on record

*   "[Cathy's Clown](https://x/c)" – The Everly Brothers

## Film

*   Henry Mancini - Breakfast at Tiffany's

## Deaths

*   [May 1](https://x/a) – Someone Famous, singer, 70

## Births

*   [May 2](https://x/a) – Baby Star, singer

## References

*   "Cited Work" – Some Journal
"""
    items = parse_era(md, 1960)
    by_title = {i.title: i for i in items}
    assert by_title["Cathy's Clown"].kind == "song"
    assert by_title["Breakfast at Tiffany's"].kind == "film"
    event = next(i for i in items if i.kind == "event")
    assert "warm welcome" in event.blurb and "](" not in event.blurb
    assert not any("Someone Famous" in i.blurb or "Baby Star" in i.blurb for i in items)
    assert not any("Cited Work" in i.title for i in items)


def test_empty_or_garbage_input_gives_no_items():
    assert parse_era("", 1955) == []
    assert parse_era("just some prose\nwithout lists", 1955) == []


def test_html_to_markdown_keeps_headings_lists_and_drops_noise():
    html = (
        '<div class="mw-heading"><h2 id="Events">Events</h2></div>'
        '<ul><li><a href="/wiki/J">January 1</a> – Big <i>news</i> arrives.<sup>[1]</sup></li>'
        "<li>June<ul><li>A nested thing happens.</li></ul></li></ul>"
        "<table><tr><td>cell junk</td></tr></table>"
        '<div class="reflist"><ol><li>cite junk</li></ol></div>'
    )
    md = html_to_markdown(html)
    assert "## Events" in md
    assert "* January 1 – Big _news_ arrives." in md
    assert "  * A nested thing happens." in md
    assert "junk" not in md and "[1]" not in md


def test_real_html_excerpt_parses_with_real_headings():
    import json

    html = json.loads((FIXTURES / "1955_in_music_api.json").read_text())["parse"]["text"]
    items = parse_era(html_to_markdown(html), 1955)
    kinds = {i.kind for i in items}
    assert len(items) >= 8 and {"song", "film", "event"} <= kinds
    blob = " ".join(i.title + i.blurb for i in items)
    assert "Wikipedia" not in blob and "Carmen Miranda" not in blob


def test_event_titles_end_naturally_without_ellipsis():
    items = parse_era(REAL, 1955)
    events = [i for i in items if i.kind == "event"]
    assert events
    for e in events:
        assert "…" not in e.title and not e.title.endswith(("...", " the", " of", " to", " a"))
        assert len(e.title) <= 60
    long = next(e for e in events if "Marian Anderson" in e.blurb)
    assert long.blurb.endswith("New York City.")  # the full sentence stays in the blurb


def test_album_rows_are_album_then_artist_and_blurb_reads_naturally():
    md = (
        "## Albums released\n\n"
        "*   _Come Fly with Me_ – Frank Sinatra\n"
        "*   _Andy Williams_ – Andy Williams\n"
    )
    by_title = {i.title: i for i in parse_era(md, 1958)}
    assert (
        by_title["Come Fly with Me"].blurb
        == "Frank Sinatra's album Come Fly with Me came out in 1958."
    )
    assert by_title["Andy Williams"].blurb == "Andy Williams's self-titled album came out in 1958."
    real = {i.title: i for i in parse_era(REAL, 1955)}
    assert real["The Waltz Queen"].blurb == "Patti Page's album The Waltz Queen came out in 1955."


def test_top_items_are_friendly_not_business_announcements():
    business = ("marketing", "price", "announces", "label", "contract", "signs ", "A&R", "policy")
    for item in parse_era(REAL, 1955)[:5]:
        text = item.title + " " + item.blurb
        assert not any(w.lower() in text.lower() for w in business), text
    md = "## Events\n\n*   [May 1](x) – Court hears a lawsuit over song royalties, judge decides.\n"
    assert parse_era(md, 1955) == []
