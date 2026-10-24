"""ASGI entry point: `uv run uvicorn bellhop.api.main:app`."""

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

app = create_app(build_container(Settings.from_env()))
