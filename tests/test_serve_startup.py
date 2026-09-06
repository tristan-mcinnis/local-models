"""Startup behaviour of the daemon's vision ensuring (`--ensure-vision`).

A vision-backend ensure that fails (e.g. a launchd-managed server that never
came up) must not kill the daemon: it logs a warning to stderr and the daemon
continues to bind and serve (vision calls degrade to 502) instead of exiting.
Everything is mocked — no real model, no network, no subprocess.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))
spec = importlib.util.spec_from_file_location("serve", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_registry(tmp: Path) -> Path:
    (tmp / "fake-model").mkdir()
    registry = {
        "version": 1,
        "default": "fake",
        "server": {"base_url": f"http://127.0.0.1:{free_port()}", "api": "mlx-vlm"},
        "aliases": {},
        "models": {
            "fake": {
                "name": "fake-model",
                "path": str(tmp / "fake-model"),
                "backend": "mlx-vlm",
                "size_bytes": 0,
                "capabilities": ["vision"],
            }
        },
    }
    path = tmp / "models.json"
    path.write_text(json.dumps(registry))
    return path


class FailingVisionBackend:
    """Stands in for the mlx-vlm backend: ensure() fails, health is down."""

    def __init__(self, *args, **kwargs):
        self.base_url = f"http://127.0.0.1:{free_port()}"

    def ensure(self, wait_seconds: int = 30) -> None:
        raise serve.BackendError("vision backend unavailable (fixture)")

    def status(self):
        return {"available": False, "loaded_model": None, "detail": "no server (fixture)"}


class HealthyVisionBackend:
    """Stands in for the mlx-vlm backend: ensure() succeeds, health is up."""

    def __init__(self, *args, **kwargs):
        self.base_url = f"http://127.0.0.1:{free_port()}"

    def ensure(self, wait_seconds: int = 30) -> None:
        return None

    def status(self):
        return {"available": True, "loaded_model": None, "detail": "ok"}


class StubBackend:
    """Fake for every non-vision backend, so /health never builds a real one
    (which would dial its live data-plane port, e.g. 8079)."""

    def __init__(self, *args, **kwargs):
        self.base_url = "http://127.0.0.1:1"

    def status(self):
        return {"available": False, "loaded_model": None, "detail": "stubbed"}


def args_for(reg_path: Path, ensure_vision: bool = True) -> argparse.Namespace:
    return argparse.Namespace(port=free_port(), registry=reg_path, ensure_vision=ensure_vision)


def get_health(port: int):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/health")
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return response.status, data


class StartupDegradationTests(unittest.TestCase):
    def _boot(self, reg_path, fake_backend):
        """Build and serve a daemon with a faked vision backend.

        The get_backend patch stays active for the whole test (not scoped to a
        `with` block) so the /health request sees the same faked backend.
        Returns (server, stderr_stream); teardown stops the server and the patch.
        """
        def fake_get_backend(name, registry):
            if name == "mlx-vlm":
                return fake_backend()
            # Never build a real non-vision backend: its status() would dial a
            # live data-plane port. Every backend status is stubbed instead.
            return StubBackend()

        # backend_cache is a shared class attribute; reset it so this test sees
        # the faked backend, not one cached by a previous test in the same process.
        serve.Handler.backend_cache = {}

        stderr = io.StringIO()
        self._patch_backend = mock.patch.object(serve, "get_backend", side_effect=fake_get_backend)
        self._patch_backend.start()
        self.addCleanup(self._patch_backend.stop)
        self._redirect = contextlib.redirect_stderr(stderr)
        self._redirect.__enter__()
        self.addCleanup(self._redirect.__exit__, None, None, None)

        server = serve.make_server(args_for(reg_path))
        # LIFO cleanup: server_shutdown() first, then server_close().
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, stderr

    def test_failed_startup_ensure_serves_degraded_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = write_registry(Path(tmp))
            server, captured_stream = self._boot(reg_path, FailingVisionBackend)
            status, data = get_health(server.server_address[1])
            self.assertEqual(status, 200)
            self.assertEqual(data["status"], "ok")
            self.assertIn("mlx-vlm", data["backends"])
            self.assertFalse(data["backends"]["mlx-vlm"]["available"])
            self.assertIn("serving degraded", captured_stream.getvalue())

    def test_successful_startup_ensure_does_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = write_registry(Path(tmp))
            server, captured_stream = self._boot(reg_path, HealthyVisionBackend)
            status, data = get_health(server.server_address[1])
            self.assertEqual(status, 200)
            self.assertTrue(data["backends"]["mlx-vlm"]["available"])
            self.assertNotIn("serving degraded", captured_stream.getvalue())

    def test_ensure_vision_absent_never_calls_get_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = write_registry(Path(tmp))
            args = args_for(reg_path, ensure_vision=False)
            with mock.patch.object(serve, "get_backend") as mock_gb:
                server = serve.make_server(args)
                mock_gb.assert_not_called()
                server.server_close()

    def test_bad_registry_raises_system_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "missing.json"
            args = argparse.Namespace(port=free_port(), registry=bad, ensure_vision=True)
            with self.assertRaises(SystemExit):
                serve.make_server(args)


if __name__ == "__main__":
    unittest.main()
