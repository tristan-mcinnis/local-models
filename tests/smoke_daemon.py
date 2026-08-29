#!/usr/bin/env python3
"""Daemon smoke: boot serve.py as a real subprocess against a temp registry."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "fake-model").mkdir()
        registry = {
            "version": 1,
            "default": "fake",
            "server": {"base_url": "http://127.0.0.1:1", "api": "mlx-vlm"},
            "aliases": {},
            "models": {
                "fake": {
                    "name": "fake-model",
                    "path": str(home / "fake-model"),
                    "backend": "mlx-vlm",
                    "size_bytes": 0,
                    "capabilities": ["vision"],
                }
            },
        }
        (home / "models.json").write_text(json.dumps(registry))

        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "server" / "serve.py"), "--port", str(port), "--registry", str(home / "models.json")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 10
            health = None
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(base + "/health", timeout=2) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(0.2)
            assert health and health["status"] == "ok", f"health failed: {health}"

            with urllib.request.urlopen(base + "/v1/models", timeout=5) as response:
                models = json.load(response)
            assert models["models"][0]["id"] == "fake", models

            request = urllib.request.Request(
                base + "/v1/transcribe", data=b"{}", method="POST", headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(request, timeout=5)
                raise AssertionError("/v1/transcribe should be 501")
            except urllib.error.HTTPError as exc:
                assert exc.code == 501, exc.code

            request = urllib.request.Request(
                base + "/v1/complete", data=b"{}", method="POST", headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(request, timeout=5)
                raise AssertionError("/v1/complete without prompt should be 400")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400, exc.code

            print("DAEMON_SMOKE_OK")
        finally:
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    import urllib.error

    main()
