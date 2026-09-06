"""Vision/text backend over an mlx-vlm HTTP server.

Adopt, wait, or spawn: if a server already answers at the registry's base_url,
adopt it. If the registry names a managed owner (`server.launch_agent`, e.g. a
launchd agent), wait a bounded time for it and never spawn a competing child.
Otherwise `ensure()` spawns one loopback-only uvicorn child (no reload worker)
and cleans up only that child on failure. Either way the daemon exposes one
uniform surface and the model stays warm between calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
from typing import Any
from urllib.parse import urlsplit

from common import http_json, model_path

from . import Backend, BackendError, status_dict

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
#: Loopback hosts an unmanaged child may bind. Restricted to hosts that resolve
#: to IPv4 loopback so the child binds the same family the daemon dials
#: (`127.0.0.1`). A launchd-managed server binds whatever its plist says; this is
#: only the spawn-side guard so a child is never started on a remote or wildcard
#: interface.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
#: Seconds between health polls while waiting for a server.
_POLL_INTERVAL = 0.5
#: Seconds to wait for a spawned child to exit during cleanup before force-kill.
_CLEANUP_GRACE = 5.0


class MlxVlmBackend(Backend):
    name = "mlx-vlm"
    capabilities = ("vision", "text")
    chat_completions_path = "/chat/completions"

    def __init__(self, registry: dict):
        super().__init__(registry)
        self.base_url = registry.get("server", {}).get("base_url", DEFAULT_BASE_URL)
        self._child: subprocess.Popen | None = None

    # -- lifecycle ---------------------------------------------------------
    def health(self) -> dict | None:
        try:
            return http_json(self.base_url, "/health", timeout=5)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def _managed_owner(self) -> str | None:
        """The launchd agent that owns this server, if the registry names one."""
        return self.registry.get("server", {}).get("launch_agent")

    def ensure(self, wait_seconds: int = 30) -> None:
        """Adopt a running server, wait for its launchd owner, or spawn one child.

        Ownership: if the registry names `server.launch_agent`, launchd owns
        the process — we wait a bounded time for it to come up and never spawn
        a competing child. Without a managed owner we spawn a loopback-only
        uvicorn child (no reload worker) and wait for health on it.
        """
        if self.health() is not None:
            return
        launch_agent = self._managed_owner()
        if launch_agent:
            self._wait_for_managed(launch_agent, wait_seconds)
            return
        self._ensure_unmanaged(wait_seconds)

    def _wait_for_managed(self, launch_agent: str, wait_seconds: int) -> None:
        """Wait for the launchd-managed server. Never spawns or touches it."""
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.health() is not None:
                return
            time.sleep(_POLL_INTERVAL)
        # launchd owns this server; we never spawned it and must not terminate it.
        raise BackendError(
            f"mlx-vlm server did not become healthy at {self.base_url}; it is managed by "
            f"launchd agent '{launch_agent}', which did not bring it up within "
            f"{wait_seconds}s. Check the agent (launchctl list | grep {launch_agent}) or its log."
        )

    def _ensure_unmanaged(self, wait_seconds: int) -> None:
        """Spawn at most one loopback-only child and wait for health on it."""
        host, port = self._spawn_target()
        # One owned child at a time: if we already own a live child, wait for it
        # instead of spawning a competing server.
        if self._child is not None and self._child.poll() is None:
            try:
                self._wait_child_health(wait_seconds)
            except BackendError:
                self._cleanup_owned_child()
                raise
            return
        argv = self._spawn_argv(host, port)
        self._child = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            self._wait_child_health(wait_seconds)
        except BackendError:
            self._cleanup_owned_child()
            raise

    def _wait_child_health(self, wait_seconds: int) -> None:
        """Poll health on an owned child; stop early if the child itself dies."""
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.health() is not None:
                return
            # Our own child exited; nothing will come up on it, stop waiting.
            if self._child is not None and self._child.poll() is not None:
                break
            time.sleep(_POLL_INTERVAL)
        raise BackendError(
            f"mlx-vlm server did not become healthy at {self.base_url} within {wait_seconds}s"
        )

    def _cleanup_owned_child(self) -> None:
        """Terminate only a child this backend spawned and only if still alive.

        Never touches a launchd-managed or adopted process (those are never
        assigned to `self._child`).
        """
        if self._child is None or self._child.poll() is not None:
            self._child = None
            return
        self._child.terminate()
        try:
            self._child.wait(timeout=_CLEANUP_GRACE)
        except subprocess.TimeoutExpired:
            self._child.kill()
            self._child.wait(timeout=_CLEANUP_GRACE)
        self._child = None

    def _spawn_target(self) -> tuple[str, int]:
        """Validate base_url and return the loopback bind target (host, port).

        Refuses a non-loopback base_url so an unmanaged child is never spawned
        on a remote or wildcard interface.
        """
        parts = urlsplit(self.base_url)
        if parts.scheme != "http":
            raise BackendError(f"mlx-vlm base_url must be http, got {self.base_url!r}")
        try:
            port = parts.port
        except ValueError as exc:
            raise BackendError(f"mlx-vlm base_url has an invalid port: {self.base_url!r}") from exc
        if port is None:
            raise BackendError(f"mlx-vlm base_url has no port: {self.base_url!r}")
        host = parts.hostname
        if host not in _LOOPBACK_HOSTS:
            raise BackendError(
                f"mlx-vlm base_url {self.base_url!r} is not loopback; refusing to "
                f"spawn a server on {host!r}"
            )
        return "127.0.0.1", port

    @staticmethod
    def _spawn_argv(host: str, port: int) -> list[str]:
        """argv for a loopback-only, no-reload mlx-vlm child.

        Uses the uvicorn entrypoint (not `python -m mlx_vlm.server`) so no reload
        worker is spawned and the child owns no grandchild, and binds loopback
        explicitly instead of the module default wildcard (0.0.0.0).
        """
        return [
            sys.executable, "-m", "uvicorn", "mlx_vlm.server:app",
            "--host", host, "--port", str(port),
        ]

    # -- contract ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        health = self.health()
        if health is None:
            return status_dict(False, None, f"no server at {self.base_url}")
        return status_dict(True, health.get("loaded_model"), health.get("status", "unknown"))

    def prepare(self, model: dict) -> None:
        # The mlx-vlm server loads whichever model path a request names, so
        # being up is enough. Spawning belongs to launchd / --ensure-vision,
        # not to a request that a client is waiting on.
        if self.health() is None:
            raise BackendError(
                f"mlx-vlm server unavailable at {self.base_url}: start it (launchd agent or --ensure-vision)"
            )

    def infer(self, model: dict, payload: dict) -> dict:
        """payload: {"messages": [...], "max_tokens": int, "temperature": float, "timeout": float}."""
        body = {
            "model": model_path(model),
            "temperature": payload.get("temperature", 0),
            "max_tokens": payload.get("max_tokens", 512),
            "stream": False,
            "messages": payload["messages"],
        }
        try:
            result = http_json(self.base_url, "/chat/completions", body, payload.get("timeout", 180))
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
            result = http_json(self.base_url, "/unload", {}, timeout=30)
        except (OSError, urllib.error.URLError) as exc:
            raise BackendError(f"unload failed: {exc}")
        message = result.get("message") if isinstance(result, dict) else None
        return {"message": message or "vision model unloaded"}
