"""Pure text helpers for the training pipeline: cleaning, chunking, dedupe, leak checks."""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
HANDLE = re.compile(r"(?<!\w)(?:/?u/|/?r/|@)[\w-]+")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
TOKEN = re.compile(r"[a-z0-9']+")


def clean_text(raw: str) -> str:
    """Strip anything that could identify a person or a page, and markdown noise."""
    text = html.unescape(raw)
    text = MD_LINK.sub(r"\1", text)
    text = URL.sub(" ", text)
    text = EMAIL.sub(" ", text)
    text = PHONE.sub(" ", text)
    text = HANDLE.sub(" ", text)
    text = re.sub(r"^\s*>.*$", " ", text, flags=re.M)  # quoted text from another poster
    text = re.sub(r"[*_`~#>|]+", " ", text)
    text = re.sub(r"\s*[\u2013\u2014]\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.!?])", r"\1", text)


def to_chunks(text: str, min_words: int = 3, max_chars: int = 240) -> list[str]:
    """One sentence per chunk, the way a resident says one thing to the robot."""
    chunks = []
    for sentence in SENTENCE_END.split(clean_text(text)):
        sentence = sentence.strip()
        if len(sentence.split()) >= min_words and len(sentence) <= max_chars:
            chunks.append(sentence)
    return chunks


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower().replace("’", "'"))


def norm_key(text: str) -> str:
    return " ".join(tokens(text))


def dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for row in rows:
        key = norm_key(row["text"])
        if key and key not in seen:
            seen.add(key)
            kept.append(row)
    return kept


def near_duplicate(a: str, b: str, threshold: float) -> bool:
    left, right = set(tokens(a)), set(tokens(b))
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= threshold


def drop_leaks(rows: list[dict], eval_texts: list[str], threshold: float = 0.7) -> list[dict]:
    """Remove training rows that equal or nearly equal any held-out eval text."""
    eval_sets = [set(tokens(t)) for t in eval_texts]
    kept = []
    for row in rows:
        mine = set(tokens(row["text"]))
        leaked = any(
            mine and other and len(mine & other) / len(mine | other) >= threshold
            for other in eval_sets
        )
        if not leaked:
            kept.append(row)
    return kept


def stable_bucket(text: str, buckets: int) -> int:
    digest = hashlib.md5(norm_key(text).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]
