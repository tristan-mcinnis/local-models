"""Offline unit tests: registry handling, CLI registry verbs, daemon routing."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
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


def make_home(tmp: Path) -> Path:
    """A temp LOCAL_MODELS_HOME with one fake registered model."""
    (tmp / "fake-model").mkdir()
    registry = {
        "version": 1,
        "default": "fake",
        "server": {"base_url": "http://127.0.0.1:1", "api": "mlx-vlm"},
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
        with self.assertRaises(KeyError):
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
        self.assertIn("mlx-vlm", data["backends"])
        self.assertIn("llama-gguf", data["backends"])

    def test_models_lists_registry_with_warm_state(self):
        status, data = self.http("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(data["models"][0]["id"], "fake")
        self.assertIn("warm", data["models"][0])

    def test_phase2_endpoints_501(self):
        for path in ("/v1/complete", "/v1/transcribe"):
            status, data = self.http("POST", path, {})
            self.assertEqual(status, 501, path)
            self.assertIn("planned", data["error"])

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


if __name__ == "__main__":
    unittest.main()
