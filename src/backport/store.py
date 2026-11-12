"""A small client for the store API."""

from __future__ import annotations

import httpx


class Store:
    def __init__(self, url: str, token: str, timeout: float = 120):
        self.http = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                 timeout=timeout)

    def _check(self, r: httpx.Response) -> dict | list | None:
        if r.status_code >= 400:
            raise SystemExit(f"store refused {r.request.method} {r.request.url.path}: {r.status_code} {r.text}")
        return r.json() if r.content else None

    def post(self, path: str, body: dict) -> dict:
        return self._check(self.http.post(path, json=body))

    def get(self, path: str, **params) -> dict | list:
        return self._check(self.http.get(path, params=params))
