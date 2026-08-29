#!/usr/bin/env python3
"""local-models daemon — one local endpoint for a fleet of small models.

Routes by capability, resolves models from the registry, delegates to
pluggable backends, and reports which models are warm.

  GET  /health          daemon liveness + per-backend availability
  GET  /v1/models       registry with live warm/loaded state
  POST /v1/vision       {"model"?, "prompt", "image_b64"|"image_path", "max_tokens"?}
  POST /v1/ask          {"model"?, "prompt", "max_tokens"?}
  POST /v1/warm         {"model"?} — load a model and keep it warm
  POST /v1/complete     completion (phase 2 -> 501)
  POST /v1/transcribe   transcription (phase 2 -> 501)
  POST /v1/unload       unload the active model of the default backend

Runs on 127.0.0.1 only. No auth by design: local socket, local user.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backends import BackendError, NotSupported, all_backends, get_backend  # noqa: E402

DEFAULT_PORT = 8078


def models_home() -> Path:
    return Path(os.environ.get("LOCAL_MODELS_HOME", str(Path.home() / "Models"))).expanduser()


def load_registry(path: Path | None = None) -> dict:
    registry_path = path or models_home() / "models.json"
    try:
        return json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read registry {registry_path}: {exc}")


def resolve_model(registry: dict, name: str | None) -> tuple[str, dict]:
    name = name or registry.get("default")
    key = registry.get("aliases", {}).get(name, name)
    model = registry.get("models", {}).get(key)
    if model is None:
        known = ", ".join(sorted(registry.get("models", {})))
        raise KeyError(f"unknown model '{name}'. Registered: {known}")
    return key, model


def image_content(payload: dict, prompt: str) -> list[dict]:
    if payload.get("image_b64"):
        data_url = "data:image/png;base64," + payload["image_b64"]
    elif payload.get("image_path"):
        path = Path(payload["image_path"]).expanduser()
        if not path.is_file():
            raise ValueError(f"image not found: {path}")
        data_url = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    else:
        raise ValueError("provide image_b64 or image_path")
    return [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": prompt},
    ]


class Handler(BaseHTTPRequestHandler):
    registry: dict = {}
    # One backend instance per name for the daemon's lifetime, so backends that
    # own child processes (llama-server) keep them across requests.
    backend_cache: dict = {}

    @classmethod
    def backend(cls, name: str):
        if name not in cls.backend_cache:
            cls.backend_cache[name] = get_backend(name, cls.registry)
        return cls.backend_cache[name]

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):  # quiet by default; launchd captures stderr
        if os.environ.get("LOCAL_MODELS_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}")

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        if self.path == "/health":
            backends = {}
            for name in all_backends():
                try:
                    backends[name] = self.backend(name).status()
                except BackendError as exc:
                    backends[name] = {"available": False, "loaded_model": None, "detail": str(exc)}
            self._send(200, {"status": "ok", "service": "local-models", "backends": backends})
        elif self.path == "/v1/models":
            out = []
            status_cache: dict[str, dict] = {}
            for key, model in self.registry.get("models", {}).items():
                backend_name = model.get("backend", "mlx-vlm")
                if backend_name not in status_cache:
                    try:
                        status_cache[backend_name] = self.backend(backend_name).status()
                    except BackendError as exc:
                        status_cache[backend_name] = {"available": False, "loaded_model": None, "detail": str(exc)}
                status = status_cache[backend_name]
                resolved_path = str(Path(model.get("path", "")).expanduser())
                endpoint = None
                if backend_name == "mlx-vlm":
                    endpoint = self.registry.get("server", {}).get("base_url")
                elif backend_name == "llama-gguf":
                    endpoint = self.registry.get("completion_server", {}).get("base_url", "http://127.0.0.1:8079")
                out.append(
                    {
                        "id": key,
                        "backend": backend_name,
                        "capabilities": model.get("capabilities", []),
                        "path": resolved_path,
                        "warm": status.get("loaded_model") == resolved_path,
                        "backend_available": status.get("available", False),
                        "endpoint": endpoint,
                    }
                )
            self._send(200, {"default": self.registry.get("default"), "models": out})
        else:
            self._send(404, {"error": f"no route {self.path}"})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        try:
            payload = self._payload()
            if self.path == "/v1/vision":
                key, model = resolve_model(self.registry, payload.get("model"))
                prompt = payload.get("prompt") or "Describe this image accurately and concisely."
                messages = [{"role": "user", "content": image_content(payload, prompt)}]
                result = self._infer(model, {**payload, "messages": messages})
                self._send(200, {"model": key, "text": result["text"]})
            elif self.path == "/v1/ask":
                key, model = resolve_model(self.registry, payload.get("model"))
                if not payload.get("prompt"):
                    raise ValueError("prompt is required")
                messages = [{"role": "user", "content": payload["prompt"]}]
                result = self._infer(model, {**payload, "messages": messages})
                self._send(200, {"model": key, "text": result["text"]})
            elif self.path == "/v1/warm":
                key, model = resolve_model(self.registry, payload.get("model"))
                backend = self.backend(model.get("backend", "mlx-vlm"))
                result = backend.warm(model, payload)
                self._send(200, {"model": key, "warmed": True, "text": result["text"]})
            elif self.path == "/v1/complete":
                key, model = resolve_model(self.registry, payload.get("model"))
                if not payload.get("prompt"):
                    raise ValueError("prompt is required")
                system = payload.get(
                    "system",
                    "Continue the user's text naturally and concisely. "
                    "Return only the continuation; do not repeat the input.",
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": payload["prompt"]},
                ]
                result = self._infer(model, {**payload, "messages": messages})
                self._send(200, {"model": key, "text": result["text"]})
            elif self.path == "/v1/transcribe":
                self._send(
                    501,
                    {
                        "error": "transcribe is planned but not served yet (phase 2)",
                        "hint": "see docs/layer-contract.md",
                    },
                )
            elif self.path == "/v1/unload":
                _, model = resolve_model(self.registry, payload.get("model"))
                backend = self.backend(model.get("backend", "mlx-vlm"))
                self._send(200, backend.unload())
            else:
                self._send(404, {"error": f"no route {self.path}"})
        except (ValueError, KeyError) as exc:
            self._send(400, {"error": str(exc)})
        except NotSupported as exc:
            self._send(501, {"error": str(exc)})
        except BackendError as exc:
            self._send(502, {"error": str(exc)})

    def _infer(self, model: dict, payload: dict) -> dict:
        return self.backend(model.get("backend", "mlx-vlm")).infer(model, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="local-models daemon")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_MODELS_PORT", DEFAULT_PORT)))
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--ensure-vision", action="store_true", help="adopt or spawn the mlx-vlm server at startup")
    args = parser.parse_args()

    Handler.registry = load_registry(args.registry)
    if args.ensure_vision:
        backend = get_backend("mlx-vlm", Handler.registry)
        backend.ensure()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"local-models daemon on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
