"""Idle unloading: the use clock, the sweeper, and the reload that follows.

Nothing here loads a model, spawns a server, or touches the network: the
backend is a fake that records what was asked of it, and the clock is a dial
this file turns by hand, so a 30-minute threshold is tested in milliseconds.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "server"))
spec = importlib.util.spec_from_file_location("serve", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class FakeClock:
    """A monotonic clock the test advances, so idle time costs no wall time."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeBackend:
    """A backend that loads, unloads, and refuses to infer while cold — the
    llama-gguf shape, without a child process."""

    name = "mlx-vlm"
    capabilities = ("text", "vision")
    chat_completions_path = "/chat/completions"

    def __init__(self, path: str = "") -> None:
        self.base_url = "http://127.0.0.1:9"
        self.loaded_path = ""
        self.model_path = path
        self.unload_calls = 0
        self.prepare_calls = 0
        self.infer_calls = 0
        self.unload_error: str | None = None
        #: Raised while an infer is running, so a test can hold a request open.
        self.infer_started = threading.Event()
        self.release_infer = threading.Event()
        self.release_infer.set()

    def status(self):
        return serve.status_dict(True, self.loaded_path or None, "fake")

    def prepare(self, model):
        self.prepare_calls += 1
        self.loaded_path = serve.model_path(model)

    def warm(self, model, payload):
        self.prepare(model)
        return {"text": "OK"}

    def infer(self, model, payload):
        self.infer_calls += 1
        self.infer_started.set()
        self.release_infer.wait(timeout=10)
        if not self.loaded_path:
            raise serve.BackendError("fake backend is cold")
        return {"text": "hello"}

    def unload(self):
        self.unload_calls += 1
        if self.unload_error:
            raise serve.BackendError(self.unload_error)
        self.loaded_path = ""
        return {"message": "fake unloaded"}


class FakeHandler:
    """The slice of the request handler the sweeper uses."""

    def __init__(self, backends: dict) -> None:
        self.backend_cache = backends

    def backend(self, name):
        return self.backend_cache[name]


def sweeper(backends: dict, threshold: float, use: serve.BackendUse) -> serve.IdleSweeper:
    return serve.IdleSweeper(FakeHandler(backends), threshold, interval=3600, use=use)


class UseClockTests(unittest.TestCase):
    """What counts as use, and what the clock says afterwards."""

    def setUp(self):
        self.clock = FakeClock()
        self.use = serve.BackendUse(clock=self.clock)

    def test_unused_backend_has_no_idle_clock(self):
        self.assertIsNone(self.use.idle_seconds("mlx-vlm"))

    def test_use_stamps_the_clock(self):
        with self.use.using("mlx-vlm"):
            self.assertEqual(self.use.idle_seconds("mlx-vlm"), 0.0)
        self.clock.advance(90)
        self.assertEqual(self.use.idle_seconds("mlx-vlm"), 90.0)

    def test_a_long_call_counts_as_use_for_its_whole_length(self):
        with self.use.using("mlx-vlm"):
            self.clock.advance(600)
            # In flight is never idle, however long the call runs.
            self.assertEqual(self.use.idle_seconds("mlx-vlm"), 0.0)
        self.assertEqual(self.use.idle_seconds("mlx-vlm"), 0.0)

    def test_claim_clears_the_idle_clock(self):
        with self.use.using("mlx-vlm"):
            pass
        self.clock.advance(100)
        with self.use.unload_claim("mlx-vlm", min_idle=60) as granted:
            self.assertTrue(granted)
        self.assertIsNone(self.use.idle_seconds("mlx-vlm"))

    def test_claim_refused_under_the_threshold(self):
        with self.use.using("mlx-vlm"):
            pass
        self.clock.advance(59)
        with self.use.unload_claim("mlx-vlm", min_idle=60) as granted:
            self.assertFalse(granted)

    def test_claim_refused_for_a_backend_that_was_never_used(self):
        self.clock.advance(10_000)
        with self.use.unload_claim("mlx-vlm", min_idle=60) as granted:
            self.assertFalse(granted)

    def test_claim_refused_while_a_request_is_in_flight(self):
        with self.use.using("mlx-vlm"):
            self.clock.advance(10_000)
            with self.use.unload_claim("mlx-vlm", min_idle=60) as granted:
                self.assertFalse(granted)

    def test_a_request_waits_for_a_claim_to_finish(self):
        """A request that arrives during an unload never reaches the backend
        until the unload is done."""
        started = threading.Event()
        entered = threading.Event()

        def request():
            started.set()
            with self.use.using("mlx-vlm"):
                entered.set()

        with self.use.unload_claim("mlx-vlm") as granted:
            self.assertTrue(granted)
            thread = threading.Thread(target=request, daemon=True)
            thread.start()
            self.assertTrue(started.wait(timeout=5))
            # Still blocked: the claim is held.
            self.assertFalse(entered.wait(timeout=0.2))
        self.assertTrue(entered.wait(timeout=5))
        thread.join(timeout=5)


class SweeperTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.use = serve.BackendUse(clock=self.clock)
        self.backend = FakeBackend()
        self.backends = {"mlx-vlm": self.backend}

    def use_once(self):
        with self.use.using("mlx-vlm"):
            self.backend.loaded_path = "/fake/model"

    def test_backend_past_the_threshold_is_unloaded(self):
        self.use_once()
        self.clock.advance(1801)
        self.assertEqual(sweeper(self.backends, 1800, self.use).sweep(), ["mlx-vlm"])
        self.assertEqual(self.backend.unload_calls, 1)

    def test_backend_under_the_threshold_is_left_warm(self):
        self.use_once()
        self.clock.advance(1799)
        self.assertEqual(sweeper(self.backends, 1800, self.use).sweep(), [])
        self.assertEqual(self.backend.unload_calls, 0)

    def test_threshold_zero_disables_the_sweeper(self):
        self.use_once()
        self.clock.advance(100_000)
        sweep = sweeper(self.backends, 0, self.use)
        self.assertFalse(sweep.enabled)
        self.assertEqual(sweep.sweep(), [])
        self.assertEqual(self.backend.unload_calls, 0)

    def test_an_in_flight_request_is_never_unloaded_from_under(self):
        self.use_once()
        self.clock.advance(100_000)
        self.backend.release_infer.clear()
        held = threading.Thread(
            target=lambda: self._infer_under_use(), daemon=True
        )
        held.start()
        self.assertTrue(self.backend.infer_started.wait(timeout=5))
        try:
            self.assertEqual(sweeper(self.backends, 1800, self.use).sweep(), [])
            self.assertEqual(self.backend.unload_calls, 0)
        finally:
            self.backend.release_infer.set()
            held.join(timeout=5)
        # Once it finishes, the clock restarts from the end of the request.
        self.assertEqual(self.use.idle_seconds("mlx-vlm"), 0.0)

    def _infer_under_use(self):
        with self.use.using("mlx-vlm"):
            self.backend.infer({"path": "/fake/model"}, {})

    def test_an_unload_the_daemon_may_not_do_is_reported_once(self):
        self.backend.unload_error = "someone else started it"
        self.use_once()
        self.clock.advance(100_000)
        sweep = sweeper(self.backends, 1800, self.use)
        self.assertEqual(sweep.sweep(), [])
        self.assertEqual(self.backend.unload_calls, 1)
        # The clock was cleared, so the next tick does not retry (or re-log).
        self.assertEqual(sweep.sweep(), [])
        self.assertEqual(self.backend.unload_calls, 1)

    def test_sweeping_a_never_used_backend_does_nothing(self):
        self.clock.advance(100_000)
        self.assertEqual(sweeper(self.backends, 1800, self.use).sweep(), [])
        self.assertEqual(self.backend.unload_calls, 0)


class ThresholdConfigTests(unittest.TestCase):
    """The threshold comes from the registry the repo already has, with an env
    override. There is no second config system."""

    def test_default_is_thirty_minutes(self):
        with self.env(None):
            self.assertEqual(serve.idle_unload_seconds({}), 1800.0)

    def test_registry_sets_it(self):
        with self.env(None):
            self.assertEqual(
                serve.idle_unload_seconds({"daemon": {"idle_unload_seconds": 120}}), 120.0
            )

    def test_zero_in_the_registry_means_never(self):
        with self.env(None):
            self.assertEqual(
                serve.idle_unload_seconds({"daemon": {"idle_unload_seconds": 0}}), 0.0
            )

    def test_env_overrides_the_registry(self):
        with self.env("5"):
            self.assertEqual(
                serve.idle_unload_seconds({"daemon": {"idle_unload_seconds": 900}}), 5.0
            )

    def test_env_zero_disables_even_when_the_registry_asks_for_it(self):
        with self.env("0"):
            self.assertEqual(
                serve.idle_unload_seconds({"daemon": {"idle_unload_seconds": 900}}), 0.0
            )

    def test_unreadable_value_falls_back_to_the_default(self):
        with self.env("soon"):
            self.assertEqual(serve.idle_unload_seconds({}), 1800.0)

    def test_a_negative_value_is_read_as_off(self):
        with self.env("-1"):
            self.assertEqual(serve.idle_unload_seconds({}), 0.0)

    @staticmethod
    def env(value: str | None):
        """The env override set to `value`, or removed when it is None, for the
        length of the block — whatever this Mac happens to have exported."""
        import os

        patch = mock.patch.dict(os.environ)
        if value is None:
            return _EnvUnset(patch)
        return mock.patch.dict(os.environ, {"LOCAL_MODELS_IDLE_UNLOAD_SECONDS": value})


class _EnvUnset:
    """`mock.patch.dict(os.environ)` with the override removed inside."""

    def __init__(self, patch):
        self.patch = patch

    def __enter__(self):
        import os

        self.patch.start()
        os.environ.pop("LOCAL_MODELS_IDLE_UNLOAD_SECONDS", None)
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        return False


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class DaemonIdleTests(unittest.TestCase):
    """The same behaviour through the wire: what stamps the clock, what the
    model list reports, and that the request after an unload still succeeds."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        home = Path(cls._tmp.name)
        (home / "fake-model").mkdir()
        cls.model_path = str(home / "fake-model")
        serve.Handler.registry = {
            "version": 1,
            "default": "fake",
            "server": {"base_url": f"http://127.0.0.1:{free_port()}"},
            "daemon": {"base_url": f"http://127.0.0.1:{free_port()}"},
            "aliases": {"default": "fake"},
            "models": {
                "fake": {
                    "name": "fake-model",
                    "path": cls.model_path,
                    "backend": "mlx-vlm",
                    "size_bytes": 0,
                    "capabilities": ["text", "vision"],
                }
            },
        }
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._tmp.cleanup()
        serve.Handler.backend_cache = {}

    def setUp(self):
        self.clock = FakeClock()
        self.use = serve.BackendUse(clock=self.clock)
        self.backend = FakeBackend(self.model_path)
        # The handler and the sweeper both read the module-level tracker; swap
        # it for one whose clock this test owns.
        self._real_use = serve.USE
        serve.USE = self.use
        serve.Handler.backend_cache = {"mlx-vlm": self.backend}
        self.addCleanup(self._restore)

    def _restore(self):
        serve.USE = self._real_use
        serve.Handler.backend_cache = {}

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

    def test_listing_and_health_are_not_use(self):
        for _ in range(3):
            self.assertEqual(self.http("GET", "/v1/models")[0], 200)
            self.assertEqual(self.http("GET", "/health")[0], 200)
        # Nothing has put the backend to work, so it has no idle clock at all
        # and the sweeper will never claim it.
        self.assertIsNone(self.use.idle_seconds("mlx-vlm"))
        _, data = self.http("GET", "/v1/models")
        self.assertIsNone(data["models"][0]["idle_seconds"])

    def test_ask_is_use(self):
        status, _ = self.http("POST", "/v1/ask", {"prompt": "hi"})
        self.assertEqual(status, 200)
        self.clock.advance(300)
        _, data = self.http("GET", "/v1/models")
        self.assertEqual(data["models"][0]["idle_seconds"], 300.0)

    def test_warm_is_use(self):
        self.assertEqual(self.http("POST", "/v1/warm", {})[0], 200)
        self.assertEqual(self.use.idle_seconds("mlx-vlm"), 0.0)

    def test_models_keeps_the_shape_clients_parse(self):
        _, data = self.http("GET", "/v1/models")
        row = data["models"][0]
        # Cotype parses id, warm and endpoint; those may never move.
        self.assertEqual(row["id"], "fake")
        self.assertIn("warm", row)
        self.assertTrue(row["endpoint"].startswith("http://127.0.0.1"))
        self.assertIn("backend_available", row)
        self.assertIn("idle_seconds", row)
        self.assertIn("idle_unload_seconds", data)

    def test_explicit_unload_clears_the_idle_clock(self):
        self.assertEqual(self.http("POST", "/v1/warm", {})[0], 200)
        self.assertEqual(self.http("POST", "/v1/unload", {})[0], 200)
        self.assertIsNone(self.use.idle_seconds("mlx-vlm"))

    def test_the_request_after_an_idle_unload_reloads_and_succeeds(self):
        status, _ = self.http("POST", "/v1/warm", {})
        self.assertEqual(status, 200)
        self.assertTrue(self.backend.loaded_path)

        self.clock.advance(1801)
        swept = serve.IdleSweeper(serve.Handler, 1800, interval=3600, use=self.use).sweep()
        self.assertEqual(swept, ["mlx-vlm"])
        self.assertFalse(self.backend.loaded_path)
        _, data = self.http("GET", "/v1/models")
        self.assertFalse(data["models"][0]["warm"])

        # The next call pays a reload rather than failing: prepare() runs
        # before infer(), and the backend refuses to infer while cold.
        status, body = self.http("POST", "/v1/ask", {"prompt": "hi"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["text"], "hello")
        self.assertTrue(self.backend.loaded_path)
        _, data = self.http("GET", "/v1/models")
        self.assertTrue(data["models"][0]["warm"])

    def test_a_request_in_flight_is_never_unloaded_from_under(self):
        self.assertEqual(self.http("POST", "/v1/warm", {})[0], 200)
        self.clock.advance(100_000)
        self.backend.release_infer.clear()

        result: dict = {}

        def call():
            result["status"], result["body"] = self.http("POST", "/v1/ask", {"prompt": "hi"})

        caller = threading.Thread(target=call, daemon=True)
        caller.start()
        self.assertTrue(self.backend.infer_started.wait(timeout=5))
        try:
            sweep = serve.IdleSweeper(serve.Handler, 1800, interval=3600, use=self.use)
            self.assertEqual(sweep.sweep(), [])
            self.assertEqual(self.backend.unload_calls, 0)
        finally:
            self.backend.release_infer.set()
            caller.join(timeout=10)
        self.assertEqual(result["status"], 200, result)


class SweeperStartupTests(unittest.TestCase):
    """make_server attaches the sweeper and honours the off switch."""

    def _args(self, tmp: Path, threshold):
        import argparse

        registry = {
            "version": 1,
            "default": "fake",
            "server": {"base_url": f"http://127.0.0.1:{free_port()}"},
            "daemon": {"idle_unload_seconds": threshold},
            "aliases": {},
            "models": {
                "fake": {
                    "name": "fake-model",
                    "path": str(tmp),
                    "backend": "mlx-vlm",
                    "size_bytes": 0,
                    "capabilities": ["vision"],
                }
            },
        }
        path = tmp / "models.json"
        path.write_text(json.dumps(registry))
        return argparse.Namespace(port=free_port(), registry=path, ensure_vision=False)

    def test_threshold_zero_never_starts_the_thread(self):
        with tempfile.TemporaryDirectory() as tmp, ThresholdConfigTests.env(None):
            server = serve.make_server(self._args(Path(tmp), 0))
            self.addCleanup(server.server_close)
            self.assertFalse(server.idle_sweeper.enabled)
            self.assertFalse(server.idle_sweeper.is_alive())

    def test_a_threshold_starts_the_thread(self):
        with tempfile.TemporaryDirectory() as tmp, ThresholdConfigTests.env(None):
            server = serve.make_server(self._args(Path(tmp), 900))
            self.addCleanup(server.server_close)
            self.addCleanup(server.idle_sweeper.stop)
            self.assertEqual(server.idle_sweeper.threshold, 900.0)
            self.assertTrue(server.idle_sweeper.is_alive())


if __name__ == "__main__":
    unittest.main()
