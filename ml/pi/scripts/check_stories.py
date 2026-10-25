"""Download each short story's Gutenberg book and check the story is found and as long as listed.

Usage (Mac or Pi): uv run python scripts/check_stories.py   # about 3 MB the first time
Success: every story shows its first and last sentence, then STORIES OK. "NOT FOUND": Gutenberg
changed that book's text; fix the story's start or end heading in STORIES (rover/agent/books.py).
"""

from rover.agent import books

WORDS_PER_MINUTE = 150  # Piper's pace with the gaps between parts


def main() -> None:
    ok = True
    for key, story in books.STORIES.items():
        try:
            parts = books.chunks(story, books.fetch(story["book"]))
        except Exception as exc:  # noqa: BLE001 - report it and check the rest
            print(f"{key}: download failed ({type(exc).__name__}: {exc})")
            ok = False
            continue
        if not parts:
            print(f"{key}: NOT FOUND in book {story['book']}")
            ok = False
            continue
        minutes = sum(len(s.split()) for part in parts for s in part) / WORDS_PER_MINUTE
        off = abs(minutes - story["minutes"]) > max(2, story["minutes"] / 5)
        ok = ok and not off
        listed = f" (LISTED {story['minutes']})" if off else ""
        print(f"{key}: about {minutes:.0f} min{listed}")
        print(f"    starts: {parts[1][0][:80]}")
        print(f"    ends:   {parts[-1][-1][:80]}")
    print("STORIES OK" if ok else "STORIES FAILED")


if __name__ == "__main__":
    main()
