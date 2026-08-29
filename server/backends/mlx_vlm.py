"""Vision/text backend over an mlx-vlm HTTP server.

Adopt-or-spawn: if a server already answers at the registry's base_url (for
example one managed by launchd), adopt it. Otherwise `ensure()` can spawn
`python -m mlx_vlm.server` as a child. Either way the daemon exposes one
uniform surface and the model stays warm between calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import Backend, BackendError


def _request(base_url: str, path: str, payload: dict | None = None, timeout: int = 180):
    url = base_url.rstrip("/") + path
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class MlxVlmBackend(Backend):
    name = "mlx-vlm"
    capabilities = ("vision", "text")

    def __init__(self, registry: dict):
        super().__init__(registry)
        self.base_url = registry.get("server", {}).get("base_url", "http://127.0.0.1:8080")
        self._child: subprocess.Popen | None = None

    # -- lifecycle ---------------------------------------------------------
    def health(self) -> dict | None:
        try:
            return _request(self.base_url, "/health", timeout=5)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def ensure(self, wait_seconds: int = 30) -> None:
        """Adopt a running server, or spawn one child and wait for health."""
        if self.health() is not None:
            return
        port = self.base_url.rsplit(":", 1)[-1].rstrip("/")
        self._child = subprocess.Popen(
            [sys.executable, "-m", "mlx_vlm.server", "--port", port],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.health() is not None:
                return
            time.sleep(0.5)
        raise BackendError(f"mlx-vlm server did not become healthy at {self.base_url}")

    # -- contract ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        health = self.health()
        if health is None:
            return {"available": False, "loaded_model": None, "detail": f"no server at {self.base_url}"}
        return {
            "available": True,
            "loaded_model": health.get("loaded_model"),
            "detail": health.get("status", "unknown"),
        }

    def infer(self, model: dict, payload: dict) -> dict:
        """payload: {"messages": [...], "max_tokens": int, "temperature": float}."""
        body = {
            "model": str(Path(model["path"]).expanduser()),
            "temperature": payload.get("temperature", 0),
            "max_tokens": payload.get("max_tokens", 512),
            "stream": False,
            "messages": payload["messages"],
        }
        try:
            result = _request(self.base_url, "/chat/completions", body, payload.get("timeout", 180))
        except urllib.error.HTTPError as exc:
            raise BackendError(f"mlx-vlm server HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except OSError as exc:
            raise BackendError(f"mlx-vlm server unavailable at {self.base_url}: {exc}")
        try:
            text = result["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise BackendError("unexpected mlx-vlm response shape")
        return {"text": text, "raw": result}

    def unload(self) -> dict:
        try:
            return _request(self.base_url, "/unload", {}, timeout=30)
        except (OSError, urllib.error.URLError) as exc:
            raise BackendError(f"unload failed: {exc}")
