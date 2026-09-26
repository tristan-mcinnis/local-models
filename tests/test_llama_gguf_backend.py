"""Lifecycle tests for the llama-gguf backend's managed llama-server child.

No real llama-server, socket, or subprocess: health, the served-model probe,
and `subprocess.Popen` are fakes, so a load that takes "a while" costs a few
milliseconds.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

from backends import llama_gguf  # noqa: E402

MODEL = {"path": "/models/completion.gguf", "backend": "llama-gguf"}


class FakeServer:
    """One port, like the real thing: a child is healthy a short while after it
    starts, and only while it has not been terminated."""

    def __init__(self, load_seconds: float = 0.2) -> None:
        self.load_seconds = load_seconds
        self.spawned: list[FakeChild] = []
        self.lock = threading.Lock()

    def popen(self, argv, **_kwargs):
        child = FakeChild(argv[argv.index("-m") + 1], self.load_seconds)
        with self.lock:
            self.spawned.append(child)
        return child

    def live(self):
        with self.lock:
            return [c for c in self.spawned if c.poll() is None and c.ready()]

    def health(self) -> bool:
        return bool(self.live())

    def served_model_path(self):
        live = self.live()
        return live[-1].model if live else None


class FakeChild:
    def __init__(self, model: str, load_seconds: float) -> None:
        self.model = model
        self.started = time.monotonic()
        self.load_seconds = load_seconds
        self.returncode = None

    def ready(self) -> bool:
        return time.monotonic() - self.started >= self.load_seconds

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class ConcurrentEnsureTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.backend = llama_gguf.LlamaGgufBackend({"completion_server": {"base_url": "http://127.0.0.1:8079"}})
        self.backend.health = self.server.health
        self.backend.served_model_path = self.server.served_model_path
        self.backend.binary = lambda: "/usr/bin/llama-server"
        patch = mock.patch.object(llama_gguf.subprocess, "Popen", side_effect=self.server.popen)
        patch.start()
        self.addCleanup(patch.stop)
        real_sleep = time.sleep
        sleep = mock.patch.object(llama_gguf.time, "sleep", lambda _s: real_sleep(0.01))
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_two_cold_requests_spawn_one_server(self):
        """Two requests arriving while the model is cold (Quick Launch's chat
        and a warm from the menu bar) each saw no server and each spawned one;
        the second stop() killed the first child mid-load. One spawn serves
        both."""
        errors: list[Exception] = []

        def ensure():
            try:
                self.backend.ensure(MODEL, wait_seconds=5)
            except Exception as exc:  # noqa: BLE001 - collected for the assert
                errors.append(exc)

        threads = [threading.Thread(target=ensure) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.server.spawned), 1)
        self.assertIsNone(self.server.spawned[0].poll())

    def test_an_unload_waits_for_a_load_in_progress(self):
        """An unload landing mid-load used to clear the child under the loading
        thread, which then crashed on `None.poll()`."""
        errors: list[Exception] = []

        def ensure():
            try:
                self.backend.ensure(MODEL, wait_seconds=5)
            except Exception as exc:  # noqa: BLE001 - collected for the assert
                errors.append(exc)

        loading = threading.Thread(target=ensure)
        loading.start()
        while not self.server.spawned:
            time.sleep(0.005)
        self.backend.unload()
        loading.join(timeout=10)
        self.assertEqual(errors, [])
        # The unload ran after the load finished, so nothing is left running.
        self.assertIsNotNone(self.server.spawned[0].poll())
        self.assertIsNone(self.backend._child)


if __name__ == "__main__":
    unittest.main()
