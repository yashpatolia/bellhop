"""Check the wake word alone: the mic, the gates and Deepgram Flux, no Claude and no voice.

Usage (Mac or Pi): uv run python scripts/check_wake.py   # rover.speech stopped (it owns the mic)
Say "Hey Bellhop, hello". Success: heard: 'hello' (a line per wake word; Ctrl-C to stop).
Other speech prints nothing. Nothing at all: check DEEPGRAM_API_KEY in .env and MIC_NAME.
"""

import queue

from rover.speech.wake import WakeListener


def main() -> None:
    while True:
        words: queue.SimpleQueue[str] = queue.SimpleQueue()
        listener = WakeListener(words.put).start()
        print(f"heard: {words.get()!r}")
        listener.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
