"""Completion backend: GGUF models served by a managed llama-server child.

The daemon owns the llama-server lifecycle (spawn on warm, terminate on
unload); apps stream straight from llama-server's OpenAI-compatible endpoint
(the data plane) while the daemon stays the control plane. One llama-server,
one loaded GGUF at a time; warming a different GGUF respawns the server.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
from pathlib import Path
from typing import Any

from common import http_json, model_path

from . import Backend, BackendError, status_dict

DEFAULT_BASE_URL = "http://127.0.0.1:8079"


class LlamaGgufBackend(Backend):
    name = "llama-gguf"
    capabilities = ("completion", "text")

    def __init__(self, registry: dict):
        super().__init__(registry)
        self.base_url = registry.get("completion_server", {}).get("base_url", DEFAULT_BASE_URL)
        self._child: subprocess.Popen | None = None
        self._child_model: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def binary(self) -> str | None:
        """llama-server from PATH, else the well-known install locations —
        launchd runs the daemon with a minimal PATH that misses Homebrew."""
        found = shutil.which("llama-server")
        if found:
            return found
        for candidate in ("/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"):
            if Path(candidate).is_file():
                return candidate
        return None

    def health(self) -> bool:
        try:
            http_json(self.base_url, "/health", timeout=3)
            return True
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def served_model_path(self) -> str | None:
        """The GGUF the running server actually has loaded, from /v1/models."""
        try:
            result = http_json(self.base_url, "/v1/models", timeout=3)
            model_id = result["data"][0]["id"]
            return str(Path(model_id).expanduser())
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError):
            return None

    def ensure(self, model: dict, wait_seconds: int = 180) -> None:
        """Make llama-server serve this model, respawning if a different one is up."""
        target = model_path(model)
        if self.health() and self.served_model_path() == target:
            return
        binary = self.binary()
        if binary is None:
            raise BackendError(
                "llama-server not found on PATH. Install it with: brew install llama.cpp"
            )
        self.stop()
        port = self.base_url.rsplit(":", 1)[-1].rstrip("/")
        self._child = subprocess.Popen(
            [
                binary, "-m", target, "--host", "127.0.0.1", "--port", port,
                "-ngl", "99", "--ctx-size", "4096",
                # Completion serving wants raw continuation tokens, never
                # thinking: disable it template-natively where the template
                # supports it, and zero the reasoning budget as the fallback.
                "--chat-template-kwargs", '{"enable_thinking": false}',
                "--reasoning-budget", "0",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._child_model = target
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.health():
                return
            if self._child.poll() is not None:
                raise BackendError(f"llama-server exited with code {self._child.returncode} loading {target}")
            time.sleep(0.5)
        raise BackendError(f"llama-server did not become healthy at {self.base_url}")

    def stop(self) -> None:
        if self._child is not None and self._child.poll() is None:
            self._child.terminate()
            try:
                self._child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._child.kill()
        self._child = None
        self._child_model = None

    # -- contract ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        if not self.health():
            detail = (
                "no llama-server running"
                if self.binary()
                else "llama-server not installed (brew install llama.cpp)"
            )
            return status_dict(self.binary() is not None, None, detail)
        return status_dict(True, self.served_model_path(), "healthy")

    def warm(self, model: dict, payload: dict) -> dict:
        self.ensure(model)
        return self.infer(model, {**payload, "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 8})

    def infer(self, model: dict, payload: dict) -> dict:
        target = model_path(model)
        if not self.health():
            raise BackendError(
                f"llama-server unavailable at {self.base_url}: warm the model first (POST /v1/warm)"
            )
        served = self.served_model_path()
        if served is not None and served != target:
            raise BackendError(
                f"llama-server is serving {Path(served).name}; warm {Path(target).name} first (POST /v1/warm)"
            )
        body = {
            "model": target,
            "temperature": payload.get("temperature", 0),
            "max_tokens": payload.get("max_tokens", 64),
            "stream": False,
            "messages": payload["messages"],
        }
        try:
            result = http_json(self.base_url, "/v1/chat/completions", body, payload.get("timeout", 180))
        except urllib.error.HTTPError as exc:
            raise BackendError(f"llama-server HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except OSError as exc:
            raise BackendError(f"llama-server unavailable at {self.base_url}: {exc}")
        try:
            text = result["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise BackendError("unexpected llama-server response shape")
        return {"text": text, "raw": result}

    def unload(self) -> dict:
        if self._child is not None:
            self.stop()
            return {"message": "llama-server stopped; completion model unloaded"}
        if self.health():
            raise BackendError(
                "a llama-server is running but the daemon did not start it; stop it where it was started"
            )
        return {"message": "no completion model was loaded"}
