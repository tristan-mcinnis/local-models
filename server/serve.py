#!/usr/bin/env python3
"""local-models daemon: one local endpoint for a fleet of small models.

Routes by capability, resolves models from the registry, delegates to
pluggable backends, and reports which models are warm.

  GET  /health          daemon liveness + per-backend availability
  GET  /v1/models       registry with live warm/loaded state
  POST /v1/vision       {"model"?, "prompt"?, "image_b64"|"image_path", "mime"?, "max_tokens"?, "timeout"?}
  POST /v1/ask          {"model"?, "prompt", "max_tokens"?, "timeout"?}
  POST /v1/complete     {"model"?, "prompt", "system"?, "max_tokens"?, "timeout"?}
  POST /v1/warm         {"model"?}  load a model and keep it warm
  POST /v1/unload       {"model"?}  unload the backend that owns that model
  POST /v1/transcribe   planned (501)

OpenAI-compatible passthrough (for clients that speak OpenAI chat, e.g.
Quick Launch's local provider), so no app needs a backend port:

  GET  /v1/openai/models          {"object": "list", "data": [{"id", "object": "model", "owned_by"}]}
  POST /v1/chat/completions       OpenAI chat body; "model" is a registry id or
                                  alias (or omitted for the default). The daemon
                                  readies the owning backend and relays the
                                  backend's reply byte-for-byte, streaming
                                  (SSE) or not. Unknown model is 404 here, as
                                  OpenAI clients expect.

Every success body is a JSON object. Every error body is
{"error": "<message>"} with an optional "hint"; status codes are
400 (bad request / unknown model), 404 (no route), 501 (planned, not
served), 502 (backend unreachable or failed).

Runs on 127.0.0.1 only. No auth by design: local socket, local user.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backends import BackendError, NotSupported, all_backends, get_backend, status_dict  # noqa: E402
from common import (  # noqa: E402
    DEFAULT_DAEMON_URL,
    OPENER,
    RegistryError,
    backend_name,
    load_registry,
    model_path,
    resolve_model,
)

DEFAULT_PORT = int(DEFAULT_DAEMON_URL.rsplit(":", 1)[-1])


def image_content(payload: dict, prompt: str) -> list[dict]:
    """OpenAI-style multimodal content from image_b64 or image_path."""
    mime = payload.get("mime")
    if payload.get("image_b64"):
        encoded = payload["image_b64"]
    elif payload.get("image_path"):
        path = Path(payload["image_path"]).expanduser()
        if not path.is_file():
            raise ValueError(f"image not found: {path}")
        encoded = base64.b64encode(path.read_bytes()).decode()
        mime = mime or mimetypes.guess_type(path.name)[0]
    else:
        raise ValueError("provide image_b64 or image_path")
    data_url = f"data:{mime or 'image/png'};base64,{encoded}"
    return [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": prompt},
    ]


def require_prompt(payload: dict) -> str:
    prompt = payload.get("prompt")
    if not prompt:
        raise ValueError("prompt is required")
    return prompt


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

    @classmethod
    def backend_status(cls, name: str) -> dict:
        try:
            return cls.backend(name).status()
        except BackendError as exc:
            return status_dict(False, None, str(exc))

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

    def _error(self, code: int, message: str, hint: str | None = None) -> None:
        body = {"error": message}
        if hint:
            body["hint"] = hint
        self._send(code, body)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}")

    def _dispatch(self, routes: dict) -> None:
        handler = routes.get(self.path)
        if handler is None:
            self._error(404, f"no route {self.path}")
            return
        try:
            handler()
        except (ValueError, RegistryError) as exc:
            self._error(400, str(exc))
        except NotSupported as exc:
            self._error(501, str(exc), hint="see docs/layer-contract.md")
        except BackendError as exc:
            self._error(502, str(exc))

    def _infer(self, model: dict, payload: dict) -> dict:
        return self.backend(backend_name(model)).infer(model, payload)

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        self._dispatch(
            {
                "/health": self.get_health,
                "/v1/models": self.get_models,
                "/v1/openai/models": self.get_openai_models,
            }
        )

    def get_health(self) -> None:
        backends = {name: self.backend_status(name) for name in all_backends()}
        self._send(200, {"status": "ok", "service": "local-models", "backends": backends})

    def get_models(self) -> None:
        out = []
        status_cache: dict[str, dict] = {}
        for key, model in self.registry.get("models", {}).items():
            name = backend_name(model)
            if name not in status_cache:
                status_cache[name] = self.backend_status(name)
            status = status_cache[name]
            resolved_path = model_path(model)
            try:
                endpoint = self.backend(name).base_url
            except BackendError:
                endpoint = None
            out.append(
                {
                    "id": key,
                    "backend": name,
                    "capabilities": model.get("capabilities", []),
                    "path": resolved_path,
                    "warm": status.get("loaded_model") == resolved_path,
                    "backend_available": status.get("available", False),
                    "endpoint": endpoint,
                }
            )
        self._send(200, {"default": self.registry.get("default"), "models": out})

    def get_openai_models(self) -> None:
        """OpenAI `GET /v1/models` shape: ids plus aliases of every model whose
        backend can answer /v1/chat/completions (TTS / STT entries stay out)."""
        models = {}
        for key, model in self.registry.get("models", {}).items():
            try:
                if self.backend(backend_name(model)).chat_completions_path:
                    models[key] = model
            except BackendError:
                continue
        data = [{"id": key, "object": "model", "owned_by": "local-models"} for key in models]
        for alias, target in self.registry.get("aliases", {}).items():
            if alias not in models and target in models:
                data.append({"id": alias, "object": "model", "owned_by": "local-models"})
        self._send(200, {"object": "list", "data": data})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        self._dispatch(
            {
                "/v1/chat/completions": self.post_chat_completions,
                "/v1/vision": self.post_vision,
                "/v1/ask": self.post_ask,
                "/v1/complete": self.post_complete,
                "/v1/warm": self.post_warm,
                "/v1/unload": self.post_unload,
                "/v1/transcribe": self.post_transcribe,
            }
        )

    def post_vision(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        prompt = payload.get("prompt") or "Describe this image accurately and concisely."
        messages = [{"role": "user", "content": image_content(payload, prompt)}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_ask(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        messages = [{"role": "user", "content": require_prompt(payload)}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_complete(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        prompt = require_prompt(payload)
        system = payload.get(
            "system",
            "Continue the user's text naturally and concisely. "
            "Return only the continuation; do not repeat the input.",
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_warm(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        result = self.backend(backend_name(model)).warm(model, payload)
        self._send(200, {"model": key, "warmed": True, "text": result["text"]})

    def post_unload(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        result = self.backend(backend_name(model)).unload()
        self._send(200, {"model": key, "unloaded": True, "message": result.get("message", "unloaded")})

    def post_transcribe(self) -> None:
        self._payload()
        raise NotSupported("transcribe is planned but not served yet (phase 2)")

    # -- OpenAI passthrough ---------------------------------------------------
    def post_chat_completions(self) -> None:
        payload = self._payload()
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise ValueError("messages is required")
        try:
            key, model = resolve_model(self.registry, payload.get("model"))
        except RegistryError as exc:
            self._error(404, str(exc))
            return
        backend = self.backend(backend_name(model))
        if backend.chat_completions_path is None or backend.base_url is None:
            raise NotSupported(f"backend '{backend.name}' has no OpenAI chat endpoint")
        backend.prepare(model)
        # The backends key on the weight path, not the registry id.
        body = json.dumps({**payload, "model": model_path(model)}).encode()
        request = urllib.request.Request(
            backend.base_url.rstrip("/") + backend.chat_completions_path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": self.headers.get("Accept") or "*/*"},
        )
        timeout = float(payload.get("timeout") or 600)
        try:
            upstream = OPENER.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise BackendError(f"{backend.name} HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except OSError as exc:
            raise BackendError(f"{backend.name} unavailable at {backend.base_url}: {exc}")
        with upstream:
            self.send_response(upstream.status)
            self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Local-Models-Model", key)
            self.send_header("Connection", "close")
            self.end_headers()
            # Relay each chunk as it lands so SSE reaches the client live.
            while True:
                chunk = upstream.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="local-models daemon")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_MODELS_PORT", DEFAULT_PORT)))
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--ensure-vision", action="store_true", help="adopt or spawn the mlx-vlm server at startup")
    args = parser.parse_args()

    try:
        Handler.registry = load_registry(args.registry)
    except RegistryError as exc:
        raise SystemExit(str(exc))
    if args.ensure_vision:
        get_backend("mlx-vlm", Handler.registry).ensure()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"local-models daemon on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
