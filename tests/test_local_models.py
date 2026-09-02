"""Offline unit tests: registry handling, CLI registry verbs, daemon routing."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli" / "local-model"

sys.path.insert(0, str(REPO / "server"))
spec = importlib.util.spec_from_file_location("serve", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


def closed_port() -> int:
    """A port nothing listens on (bound then released), so backend calls fail fast."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_home(tmp: Path, daemon_url: str = "http://127.0.0.1:8078") -> Path:
    """A temp LOCAL_MODELS_HOME with one fake registered model and no live backend."""
    (tmp / "fake-model").mkdir()
    registry = {
        "version": 1,
        "default": "fake",
        "server": {"base_url": f"http://127.0.0.1:{closed_port()}", "api": "mlx-vlm"},
        "daemon": {"base_url": daemon_url},
        "completion_server": {"base_url": f"http://127.0.0.1:{closed_port()}"},
        "aliases": {"default": "fake"},
        "models": {
            "fake": {
                "name": "fake-model",
                "path": str(tmp / "fake-model"),
                "backend": "mlx-vlm",
                "format": "MLX",
                "size_bytes": 0,
                "capabilities": ["text", "vision"],
                "role": "test fixture",
            }
        },
    }
    (tmp / "models.json").write_text(json.dumps(registry))
    return tmp


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "LOCAL_MODELS_HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=60
    )


class RegistryTests(unittest.TestCase):
    def test_resolve_expands_tilde(self):
        registry = {
            "default": "m",
            "aliases": {},
            "models": {"m": {"path": "~", "capabilities": []}},
        }
        key, model = serve.resolve_model(registry, None)
        self.assertEqual(key, "m")

    def test_resolve_unknown_raises(self):
        with self.assertRaises(serve.RegistryError):
            serve.resolve_model({"default": "x", "aliases": {}, "models": {}}, "nope")


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = make_home(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_shows_registered_model(self):
        result = run_cli(self.home, "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fake", result.stdout)

    def test_path_resolves_alias(self):
        result = run_cli(self.home, "path", "default")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fake-model", result.stdout)

    def test_add_and_rm_roundtrip(self):
        extra = self.home / "extra-model"
        extra.mkdir()
        (extra / "config.json").write_text(json.dumps({"model_type": "qwen3_vl", "vision_config": {}}))
        added = run_cli(self.home, "add", str(extra), "--name", "extra", "--alias", "xx")
        self.assertEqual(added.returncode, 0, added.stderr)
        registry = json.loads((self.home / "models.json").read_text())
        self.assertIn("extra", registry["models"])
        self.assertEqual(registry["models"]["extra"]["backend"], "mlx-vlm")
        self.assertEqual(registry["aliases"]["xx"], "extra")
        self.assertTrue((self.home / "models.json.bak").exists())

        removed = run_cli(self.home, "rm", "extra")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        registry = json.loads((self.home / "models.json").read_text())
        self.assertNotIn("extra", registry["models"])
        self.assertNotIn("xx", registry["aliases"])

    def test_add_infers_gguf_backend(self):
        gguf = self.home / "tiny.gguf"
        gguf.write_bytes(b"GGUF")
        added = run_cli(self.home, "add", str(gguf), "--name", "tiny")
        self.assertEqual(added.returncode, 0, added.stderr)
        registry = json.loads((self.home / "models.json").read_text())
        self.assertEqual(registry["models"]["tiny"]["backend"], "llama-gguf")
        self.assertEqual(registry["models"]["tiny"]["capabilities"], ["completion"])

    def test_rm_refuses_purge_outside_home(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "keepme"
            target.mkdir()
            run_cli(self.home, "add", str(target), "--name", "outsider")
            result = run_cli(self.home, "rm", "outsider", "--purge")
            self.assertEqual(result.returncode, 0)
            self.assertIn("NOT purged", result.stderr)
            self.assertTrue(target.exists())


class DaemonRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        home = make_home(Path(cls._tmp.name))
        serve.Handler.registry = json.loads((home / "models.json").read_text())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls._tmp.cleanup()

    def http(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(
            method,
            path,
            body=None if body is None else json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def test_health(self):
        status, data = self.http("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(set(data["backends"]), {"mlx-vlm", "llama-gguf", "mlx-audio-stt"})
        for backend in data["backends"].values():
            self.assertEqual(set(backend), {"available", "loaded_model", "detail"})

    def test_error_envelope_is_uniform(self):
        cases = [
            ("GET", "/nope", None, 404),
            ("POST", "/nope", {}, 404),
            ("POST", "/v1/ask", {}, 400),
            ("POST", "/v1/transcribe", {}, 501),
            ("POST", "/v1/warm", {"model": "fake"}, 502),
        ]
        for method, path, body, expected in cases:
            status, data = self.http(method, path, body)
            self.assertEqual(status, expected, (method, path, data))
            self.assertIsInstance(data["error"], str)
            self.assertTrue(set(data) <= {"error", "hint"}, data)

    def test_unload_unreachable_backend_502(self):
        status, data = self.http("POST", "/v1/unload", {})
        self.assertEqual(status, 502)
        self.assertIn("unload failed", data["error"])

    def test_models_lists_registry_with_warm_state(self):
        status, data = self.http("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(data["models"][0]["id"], "fake")
        self.assertIn("warm", data["models"][0])

    def test_transcribe_still_501(self):
        status, data = self.http("POST", "/v1/transcribe", {})
        self.assertEqual(status, 501)
        self.assertIn("planned", data["error"])

    def test_complete_requires_prompt(self):
        status, data = self.http("POST", "/v1/complete", {})
        self.assertEqual(status, 400)
        self.assertIn("prompt", data["error"])

    def test_complete_unreachable_backend_502(self):
        status, _ = self.http("POST", "/v1/complete", {"model": "fake", "prompt": "hi"})
        self.assertEqual(status, 502)

    def test_llama_backend_reports_endpoint(self):
        status, data = self.http("GET", "/v1/models")
        self.assertEqual(status, 200)
        by_id = {m["id"]: m for m in data["models"]}
        self.assertTrue(by_id["fake"]["endpoint"].startswith("http://127.0.0.1"))

    def test_unknown_route_404(self):
        status, _ = self.http("GET", "/nope")
        self.assertEqual(status, 404)

    def test_vision_without_image_400(self):
        status, data = self.http("POST", "/v1/vision", {"prompt": "hi"})
        self.assertEqual(status, 400)
        self.assertIn("image", data["error"])

    def test_unknown_model_400(self):
        status, _ = self.http("POST", "/v1/ask", {"prompt": "hi", "model": "ghost"})
        self.assertEqual(status, 400)

    def test_warm_unknown_model_400(self):
        status, _ = self.http("POST", "/v1/warm", {"model": "ghost"})
        self.assertEqual(status, 400)

    def test_warm_unreachable_backend_502(self):
        status, data = self.http("POST", "/v1/warm", {"model": "fake"})
        self.assertEqual(status, 502)
        self.assertIn("unavailable", data["error"])


class CliThroughDaemonTests(unittest.TestCase):
    """The CLIs reach models only through the daemon; the daemon's error
    envelope surfaces verbatim in the CLI's exit message."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = cls.server.server_address[1]
        cls.home = make_home(Path(cls._tmp.name), daemon_url=f"http://127.0.0.1:{port}")
        serve.Handler.registry = json.loads((cls.home / "models.json").read_text())
        serve.Handler.backend_cache = {}
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls._tmp.cleanup()

    def test_status_reports_daemon_and_backends(self):
        result = run_cli(self.home, "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("server: ok", result.stdout)
        self.assertIn("backend mlx-vlm: unavailable", result.stdout)
        self.assertIn("default: fake", result.stdout)

    def test_ask_surfaces_daemon_error_envelope(self):
        result = run_cli(self.home, "ask", "hi")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 502", result.stderr)
        self.assertIn("mlx-vlm server unavailable", result.stderr)

    def test_vision_unknown_model_is_400(self):
        fixture = REPO / "tests" / "fixtures" / "vision-test.png"
        result = run_cli(self.home, "vision", str(fixture), "what?", "--model", "ghost")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 400", result.stderr)
        self.assertIn("unknown model 'ghost'", result.stderr)

    def test_local_image_describe_goes_through_daemon(self):
        fixture = REPO / "tests" / "fixtures" / "vision-test.png"
        env = {**os.environ, "LOCAL_MODELS_HOME": str(self.home)}
        result = subprocess.run(
            [sys.executable, str(REPO / "cli" / "local-image"), "describe", str(fixture)],
            capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 502", result.stderr)

    def test_daemon_down_is_a_clear_message(self):
        env = {**os.environ, "LOCAL_MODELS_HOME": str(self.home), "LOCAL_MODELS_DAEMON": f"http://127.0.0.1:{closed_port()}"}
        result = subprocess.run([sys.executable, str(CLI), "status"], capture_output=True, text=True, env=env, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon is unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
