"""Read-only HTTP client for the Bellhop API. Failures surface as BellhopApiError."""

from typing import Any

import httpx


class BellhopApiError(Exception):
    """The Bellhop backend could not be reached or returned something unusable."""


class BellhopApi:
    def __init__(
        self,
        base_url: str,
        timeout: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def calls(self) -> list[dict[str, Any]]:
        return self._get("/calls", list)

    def alerts(self) -> list[dict[str, Any]]:
        return self._get("/alerts", list)

    def metrics(self) -> dict[str, Any]:
        return self._get("/metrics", dict)

    def _get(self, path: str, kind: type) -> Any:
        try:
            resp = self._http.get(path)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BellhopApiError(f"GET {path} failed: {exc}") from exc
        if not isinstance(data, kind):
            raise BellhopApiError(f"GET {path} returned unexpected shape")
        return data
