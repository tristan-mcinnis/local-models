"""Shared plumbing for the daemon, the backends, and the CLIs.

One definition each of: where the registry lives, how it is read, how a model
name resolves, where the daemon listens, and how JSON travels over HTTP.
Everything in this repo imports these instead of re-deriving them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_DAEMON_URL = "http://127.0.0.1:8078"
DEFAULT_BACKEND = "mlx-vlm"

#: Seconds a warm backend may go unused before the daemon unloads it.
#: 30 minutes. The daemon exists to keep weights warm, so the threshold has to
#: outlast a working session: an app polling every few minutes, a burst of
#: completions, a coffee break, a meeting. It also has to be short enough that a
#: model warmed once at lunchtime is not still holding ~9 GB resident the next
#: morning, which is what actually happens without this. 30 minutes is the
#: longest gap a person leaves inside one task and the shortest gap that means
#: they moved on to another. 0 disables idle unloading entirely.
DEFAULT_IDLE_UNLOAD_SECONDS = 1800.0


class RegistryError(RuntimeError):
    """The registry is missing, unreadable, or names an unknown model."""


def models_home() -> Path:
    """$LOCAL_MODELS_HOME, default ~/Models. Weights and models.json live here."""
    return Path(os.environ.get("LOCAL_MODELS_HOME", str(Path.home() / "Models"))).expanduser()


def registry_path() -> Path:
    return models_home() / "models.json"


def load_registry(path: Path | None = None) -> dict:
    target = path or registry_path()
    try:
        return json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Cannot read registry {target}: {exc}") from exc


def resolve_model(registry: dict, name: str | None) -> tuple[str, dict]:
    """Alias or id -> (id, entry). None (or "default") means the registry default."""
    if not name or name == "default":
        name = registry.get("default")
    key = registry.get("aliases", {}).get(name, name)
    model = registry.get("models", {}).get(key)
    if model is None:
        known = ", ".join(sorted(registry.get("models", {})))
        raise RegistryError(f"unknown model '{name}'. Registered: {known}")
    return key, model


def model_path(model: dict) -> str:
    return str(Path(model.get("path", "")).expanduser())


def backend_name(model: dict) -> str:
    return model.get("backend", DEFAULT_BACKEND)


def idle_unload_seconds(registry: dict | None = None) -> float:
    """How long a backend may sit unused before the daemon unloads it.

    $LOCAL_MODELS_IDLE_UNLOAD_SECONDS, else the registry's
    "daemon.idle_unload_seconds", else DEFAULT_IDLE_UNLOAD_SECONDS. 0 (or a
    negative number) means never unload, which is the off switch.

    An unreadable value falls back to the default rather than refusing to
    start: a typo in the registry must not take the fleet down, and
    `GET /v1/models` reports the threshold actually in force.
    """
    raw = os.environ.get("LOCAL_MODELS_IDLE_UNLOAD_SECONDS")
    if raw is None and registry:
        raw = registry.get("daemon", {}).get("idle_unload_seconds")
    if raw is None or raw == "":
        return DEFAULT_IDLE_UNLOAD_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_UNLOAD_SECONDS
    return max(0.0, value)


def daemon_base_url(registry: dict | None = None) -> str:
    """The daemon's control-plane URL: $LOCAL_MODELS_DAEMON, else registry
    "daemon.base_url", else the default port."""
    env = os.environ.get("LOCAL_MODELS_DAEMON")
    if env:
        return env.rstrip("/")
    if registry:
        return registry.get("daemon", {}).get("base_url", DEFAULT_DAEMON_URL).rstrip("/")
    return DEFAULT_DAEMON_URL


# Loopback traffic never goes through a system or environment proxy: a VPN
# or proxy app on the Mac would otherwise answer for a backend that is down.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(base_url: str, path: str, payload: dict | None = None, timeout: float = 180):
    """GET (payload None) or POST JSON and decode the JSON reply, proxy-free.

    Raises urllib.error.HTTPError on non-2xx (body still readable), OSError /
    URLError when nothing answers, json.JSONDecodeError on a non-JSON body.
    """
    url = base_url.rstrip("/") + path
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with OPENER.open(request, timeout=timeout) as response:
        return json.load(response)


def http_error_detail(exc: urllib.error.HTTPError) -> str:
    """The `error` field of a JSON error envelope, else the raw body."""
    raw = exc.read().decode(errors="replace")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "error" in parsed:
            return str(parsed["error"])
    except json.JSONDecodeError:
        pass
    return raw.strip()
