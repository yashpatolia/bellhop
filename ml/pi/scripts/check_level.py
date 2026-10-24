"""Record 5 s from the mic and print its level, to set the USB mic gain.

Usage (Mac or Pi): uv run python scripts/check_level.py [device name part]
Saves runs/check_level.wav.
"""

import math
import sys
import wave

import numpy as np

from rover import config
from rover.speech.gates import block_dbfs
from rover.speech.mic import Mic

RECORD_S = 5.0
FRAME_S = 0.02


def main() -> None:
    mic = Mic(sys.argv[1] if len(sys.argv) > 1 else config.MIC_NAME)
    mic.start()
    print(f"recording {RECORD_S:.0f} s: speak normally at 30 cm from the mic")
    blocks = []
    try:
        for _ in range(round(RECORD_S * config.SAMPLE_RATE / config.BLOCK_SAMPLES)):
            block = mic.read()
            if block is None:
                break
            blocks.append(block)
    finally:
        mic.stop()
    if not blocks:
        sys.exit("no audio recorded")
    audio = np.concatenate(blocks)

    peak = float(np.max(np.abs(audio.astype(np.int32)))) / 32768
    peak_db = 20 * math.log10(peak) if peak > 0 else -math.inf
    frame = round(FRAME_S * config.SAMPLE_RATE)
    frames = [audio[i : i + frame] for i in range(0, len(audio) - frame + 1, frame)]
    median_db = float(np.median([block_dbfs(f) for f in frames]))
    print(f"peak {peak:.3f} ({peak_db:.1f} dBFS), median 20 ms level {median_db:.1f} dBFS")
    print("target: speech at 30 cm should peak around -12 to -6 dBFS (0.25-0.5)")

    path = config.RUNS_DIR / "check_level.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.SAMPLE_RATE)
        wav.writeframes(audio.astype("<i2").tobytes())
    print(f"saved {path}")


if __name__ == "__main__":
    main()
