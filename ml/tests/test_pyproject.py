"""The project supports Python 3.11 (Bookworm Pi, laptop) and 3.13 (Trixie Pi)."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pi" / "pyproject.toml"
PROJECT = tomllib.loads(PYPROJECT.read_text())["project"]


def numpy_spec(python_version: str) -> SpecifierSet:
    """The numpy specifier that applies on the given Python (e.g. '3.13')."""
    env = {"python_version": python_version}
    specs = [
        r.specifier
        for r in map(Requirement, PROJECT["dependencies"])
        if r.name == "numpy" and (r.marker is None or r.marker.evaluate(env))
    ]
    assert len(specs) == 1, f"exactly one numpy requirement must apply on {python_version}"
    return specs[0]


def test_requires_python_covers_311_to_313():
    spec = SpecifierSet(PROJECT["requires-python"])
    assert spec == SpecifierSet(">=3.11,<3.14")
    for ok in ("3.11.9", "3.12.0", "3.13.5"):
        assert Version(ok) in spec
    for bad in ("3.10.12", "3.14.0"):
        assert Version(bad) not in spec


def test_numpy_1x_on_python_311():
    spec = numpy_spec("3.11")
    assert Version("1.26.4") in spec
    assert Version("2.0.0") not in spec


def test_numpy_2x_on_python_313():
    spec = numpy_spec("3.13")
    assert Version("2.1.0") in spec
    assert Version("2.5.4") in spec
    assert Version("1.26.4") not in spec


def test_numpy_markers_split_at_python_312():
    assert Version("1.26.4") in numpy_spec("3.11")
    assert Version("2.1.0") in numpy_spec("3.12")
