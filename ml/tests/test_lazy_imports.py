"""The audio modules must import on a machine with no PortAudio library (CI, a dev laptop)."""

import subprocess
import sys
import textwrap

import pytest

MODULES = ["rover.speech.mic", "rover.speech.tts", "rover.speech.__main__"]


def run_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=120
    )


@pytest.mark.parametrize("module", MODULES)
def test_import_does_not_load_sounddevice(module):
    result = run_python(
        f"""
        import importlib, sys
        importlib.import_module({module!r})
        assert "sounddevice" not in sys.modules, "sounddevice imported at module load"
        """
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", MODULES)
def test_import_works_when_sounddevice_cannot_load(module):
    result = run_python(
        f"""
        import sys
        sys.modules["sounddevice"] = None  # makes `import sounddevice` raise ImportError
        import importlib
        importlib.import_module({module!r})
        """
    )
    assert result.returncode == 0, result.stderr
