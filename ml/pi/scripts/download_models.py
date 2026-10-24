"""Download every model into models/. Safe to re-run: files already there are skipped.

Mac:  uv run python scripts/download_models.py
Pi:   uv run python scripts/download_models.py --skip-yolo   (the NCNN folder comes from the Mac)
"""

import argparse
import shutil
from pathlib import Path

import httpx

from rover import config

YUNET_URLS = [
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx",
]
PIPER_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/semaine/medium/"
LFS_POINTER_MAX_BYTES = 100_000  # a Git LFS pointer is a ~130-byte text file, the real model is not


def fetch(urls: list[str], dest: Path, min_bytes: int) -> None:
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"skip {dest.name}: already there")
        return
    part = dest.with_name(dest.name + ".part")  # never leave a half file under the real name
    for url in urls:
        print(f"get {url}")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=30) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                done, next_report = 0, 0.0
                with part.open("wb") as out:
                    for chunk in response.iter_bytes(1 << 16):
                        out.write(chunk)
                        done += len(chunk)
                        if total and done / total >= next_report:
                            print(f"  {done / 1e6:6.1f} / {total / 1e6:.1f} MB")
                            next_report += 0.25
        except httpx.HTTPError as error:
            print(f"  failed: {error!r}")
            part.unlink(missing_ok=True)
            continue
        if part.stat().st_size < min_bytes:
            print(f"  failed: only {part.stat().st_size} bytes (a Git LFS pointer or error page?)")
            part.unlink()
            continue
        part.rename(dest)
        print(f"  saved {dest}")
        return
    raise RuntimeError(f"every URL failed for {dest.name}")


def get_yolo() -> None:
    if (config.YOLO_MODEL / "model.ncnn.param").exists():
        print(f"skip {config.YOLO_MODEL.name}: already there")
        return
    from ultralytics import YOLO  # pulls in torch, so only when an export is needed

    # A path inside models/ makes ultralytics download the weights there, and the export lands
    # next to them as models/yolo26n_ncnn_model. Default precision is FP32.
    model = YOLO(str(config.MODELS_DIR / "yolo26n.pt"))
    exported = Path(model.export(format="ncnn", imgsz=config.YOLO_IMGSZ))
    if exported.resolve() != config.YOLO_MODEL.resolve():
        shutil.move(exported, config.YOLO_MODEL)
    print(f"  saved {config.YOLO_MODEL} (imgsz {config.YOLO_IMGSZ})")


def get_yunet() -> None:
    fetch(YUNET_URLS, config.YUNET_MODEL, LFS_POINTER_MAX_BYTES)


def get_piper_voice() -> None:
    model = config.PIPER_VOICE
    fetch([PIPER_BASE_URL + model.name], model, 1_000_000)
    config_file = Path(f"{model}.json")  # piper looks for <voice>.onnx.json next to the model
    fetch([PIPER_BASE_URL + config_file.name], config_file, 1_000)


def get_moonshine() -> None:
    from moonshine_voice import get_model_for_language, string_to_model_arch

    # Moonshine keeps its own cache (~/.cache/moonshine_voice on the Pi) and skips cached files.
    path, _ = get_model_for_language("en", string_to_model_arch(config.MOONSHINE_ARCH))
    print(f"  Moonshine {config.MOONSHINE_ARCH} ready in {path}")


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def print_table() -> None:
    print(f"\n{'file':<45} {'size':>10}")
    for path in sorted(config.MODELS_DIR.iterdir()):
        print(f"{path.name:<45} {size_of(path) / 1e6:>8.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-yolo", action="store_true", help="Pi: skip the export, copy the folder from the Mac"
    )
    args = parser.parse_args()
    config.MODELS_DIR.mkdir(exist_ok=True)

    steps = [
        ("YuNet faces", get_yunet),
        ("Piper voice", get_piper_voice),
        ("Moonshine offline STT", get_moonshine),
    ]
    if not args.skip_yolo:
        steps.insert(0, ("YOLO26n NCNN", get_yolo))

    failed = []
    for name, step in steps:
        print(f"\n== {name}")
        try:
            step()
        except Exception as error:  # steps are independent: report and carry on with the rest
            print(f"FAILED {name}: {error!r}")
            failed.append(name)

    print_table()
    if args.skip_yolo and not (config.YOLO_MODEL / "model.ncnn.param").exists():
        print(f"\nmissing {config.YOLO_MODEL.name}: copy it from the Mac:")
        print("  (Mac) scp -r models/yolo26n_ncnn_model pi@<pi>:~/ml/models/")
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nmodels OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
