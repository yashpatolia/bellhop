"""Import everything the robot runs in one process and check versions and model files.

Mac or Pi:  uv run python scripts/smoke.py   -> prints "SMOKE OK", or the failures and exits 1
"""

import importlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

from rover import config

ON_LINUX = sys.platform == "linux"
ON_PI = ON_LINUX and platform.machine() == "aarch64"

IMPORTS = {  # import name -> distribution name (for the version)
    "numpy": "numpy",
    "cv2": "opencv-python",
    "ultralytics": "ultralytics",
    "torch": "torch",
    "ncnn": "ncnn",
    "pysilero_vad": "pysilero-vad",
    "deepgram": "deepgram-sdk",
    "moonshine_voice": "moonshine-voice",
    "piper": "piper-tts",
    "sounddevice": "sounddevice",
    "anthropic": "anthropic",
    "httpx": "httpx",
}
CAR_IMPORTS = {"smbus": "smbus", "gpiozero": "gpiozero", "spidev": "spidev"}  # apt, on the Pi
FREENOVE_FILES = ("motor.py", "servo.py", "pca9685.py", "ultrasonic.py", "spi_ledpixel.py")
KEYS = ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY")

failures: list[str] = []


def fail(reason: str) -> None:
    failures.append(reason)
    print(f"  FAIL {reason}")


def version_of(dist: str, module: object) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return str(getattr(module, "__version__", "?"))


def check_imports() -> dict[str, object]:
    print("== imports (one process, like the robot)")
    names = dict(IMPORTS)
    if ON_PI:
        names["picamera2"] = "picamera2"
    else:
        print("  skip picamera2: only needed on the Pi (Linux aarch64)")
    if ON_LINUX:
        names.update(CAR_IMPORTS)
    else:
        print(f"  skip {', '.join(CAR_IMPORTS)}: car I/O, Pi only (rover.drive fakes the car)")
    modules = {}
    for name, dist in names.items():
        try:
            modules[name] = importlib.import_module(name)
        except Exception as error:  # an apt/ABI clash shows up as any exception type
            fail(f"import {name}: {error!r}")
            continue
        print(f"  {name:<16} {version_of(dist, modules[name])}")
    return modules


def check_versions(modules: dict) -> None:
    print("== versions")
    if numpy := modules.get("numpy"):
        # numpy 2 breaks Bookworm's apt picamera2 (Python 3.11); Trixie's (3.13) is built for it
        if sys.version_info < (3, 12) and int(numpy.__version__.split(".")[0]) >= 2:
            fail(f"numpy {numpy.__version__} >= 2 breaks apt's picamera2 (simplejpeg)")
    if cv2 := modules.get("cv2"):
        major, minor = (int(part) for part in cv2.__version__.split(".")[:2])
        if (major, minor) < (4, 8):
            fail(f"OpenCV {cv2.__version__} < 4.8: YuNet 2023mar needs 4.8+")
        if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "ArucoDetector"):
            fail("cv2.aruco.ArucoDetector missing")
        if not hasattr(cv2, "FaceDetectorYN"):
            fail("cv2.FaceDetectorYN missing")
    if (torch := modules.get("torch")) and ON_LINUX and torch.version.cuda is not None:
        fail(f"torch is a CUDA build ({torch.version.cuda}); the Pi needs the CPU wheel")


def check_models() -> None:
    print("== model files")
    needed = [
        config.YOLO_MODEL / "model.ncnn.param",
        config.YOLO_MODEL / "model.ncnn.bin",
        config.YUNET_MODEL,
        config.PIPER_VOICE,
        Path(f"{config.PIPER_VOICE}.json"),
    ]
    for path in needed:
        if path.exists():
            print(f"  ok   {path.relative_to(config.ML_DIR)}")
        else:
            fail(f"missing {path.relative_to(config.ML_DIR)} (run scripts/download_models.py)")
    if config.YUNET_MODEL.exists() and config.YUNET_MODEL.stat().st_size < 100_000:
        fail(f"{config.YUNET_MODEL.name} is tiny: a Git LFS pointer, delete it and re-download")
    metadata = config.YOLO_MODEL / "metadata.yaml"
    if metadata.exists():
        imgsz = yaml.safe_load(metadata.read_text()).get("imgsz")
        if imgsz != [config.YOLO_IMGSZ, config.YOLO_IMGSZ]:
            fail(f"NCNN exported at {imgsz}, config.YOLO_IMGSZ is {config.YOLO_IMGSZ}: re-export")
    from moonshine_voice.download_file import get_cache_dir

    cache = get_cache_dir()
    if cache.is_dir() and any(cache.iterdir()):
        print(f"  ok   Moonshine cache {cache}")
    else:
        fail(f"Moonshine cache {cache} is empty (run scripts/download_models.py)")


def check_freenove() -> None:
    print("== Freenove car drivers (imported from their repo by rover.drive)")
    if not ON_LINUX:
        print(f"  skip {config.FREENOVE_DIR}: Pi only")
        return
    for name in FREENOVE_FILES:
        path = config.FREENOVE_DIR / name
        if path.exists():
            print(f"  ok   {path}")
        else:
            fail(f"missing {path} (scripts/setup_pi.sh clones it; or set FREENOVE_DIR in .env)")


def print_machine() -> None:
    print("== machine (info only)")
    print(f"  python {platform.python_version()} on {sys.platform} {platform.machine()}")
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        fields = {
            line.split(":")[0]: int(line.split()[1]) // 1024
            for line in meminfo.read_text().splitlines()
        }
        swap_used = fields["SwapTotal"] - fields["SwapFree"]
        print(
            f"  memory available {fields['MemAvailable']} of {fields['MemTotal']} MB,"
            f" swap used {swap_used} MB"
        )
    if shutil.which("vcgencmd"):
        result = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5
        )
        throttled = result.stdout.strip() or result.stderr.strip()
        hint = "" if throttled == "throttled=0x0" else "  <- not 0x0: weak power supply or too hot"
        print(f"  {throttled}{hint}")
    missing = [key for key in KEYS if not os.environ.get(key)]
    print(f"  .env keys missing: {', '.join(missing) or 'none'} (code falls back and says so)")
    try:
        response = httpx.get(f"{config.BELLHOP_API}/health", timeout=config.BACKEND_HTTP_TIMEOUT_S)
        print(f"  backend {config.BELLHOP_API}/health -> {response.status_code}")
    except httpx.HTTPError as error:
        print(f"  backend {config.BELLHOP_API} unreachable: {error!r} (check BELLHOP_API in .env)")


def main() -> int:
    modules = check_imports()
    check_versions(modules)
    check_models()
    check_freenove()
    print_machine()
    if failures:
        print(f"\nSMOKE FAILED ({len(failures)}):")
        for reason in failures:
            print(f"  - {reason}")
        return 1
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
