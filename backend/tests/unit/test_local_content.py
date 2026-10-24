from bellhop.adapters.local_content import LocalContentFeed
from bellhop.ports.content import ContentFeed, ContentItem


def test_satisfies_protocol_and_returns_items():
    feed: ContentFeed = LocalContentFeed()
    items = feed.for_era(1940)
    assert items and all(isinstance(i, ContentItem) for i in items)


def test_years_within_age_window():
    for birth in (1930, 1940, 1950):
        for item in LocalContentFeed().for_era(birth, limit=50):
            assert birth + 15 <= item.year <= birth + 25


def test_limit_respected():
    assert len(LocalContentFeed().for_era(1940, limit=2)) == 2
    assert LocalContentFeed().for_era(1940, limit=0) == []


def test_deterministic_ordering():
    assert LocalContentFeed().for_era(1945) == LocalContentFeed().for_era(1945)


def test_unique_ids_and_valid_kinds():
    items = LocalContentFeed().for_era(1925, limit=100) + LocalContentFeed().for_era(
        1950, limit=100
    )
    kinds = {i.kind for i in items}
    assert kinds <= {"song", "film", "news", "event"}


def test_out_of_range_birth_year_is_empty():
    assert LocalContentFeed().for_era(1700) == []
