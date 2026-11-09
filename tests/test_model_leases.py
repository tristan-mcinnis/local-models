"""A model switch must wait for complete inference/stream lifetimes."""
from __future__ import annotations

import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))
spec = importlib.util.spec_from_file_location("serve_model_tests", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)
A = {"path": "/models/a", "backend": "llama-gguf"}
B = {"path": "/models/b", "backend": "llama-gguf"}


class ModelLeaseTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(serve.Handler)
        self.errors = []
        self.threads = []
        self.releases = []
        self.addCleanup(self.finish)

    def finish(self):
        for release in self.releases:
            release.set()
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive(), "work never released its model lease")
        self.assertEqual(self.errors, [])

    def event(self):
        event = threading.Event()
        self.releases.append(event)
        return event

    def start(self, action):
        def run():
            try:
                action()
            except BaseException as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=run)
        self.threads.append(thread)
        thread.start()
        return thread

    def test_model_switch_waits_for_active_inference(self):
        started, release, switched = threading.Event(), self.event(), threading.Event()
        backend = mock.Mock()
        loaded = []

        def prepare(model):
            loaded[:] = [model["path"]]
            if model is B:
                switched.set()

        def infer(model, payload):
            if model is A:
                started.set()
                if not release.wait(5):
                    raise AssertionError("generation never released")
                self.assertEqual(loaded, [A["path"]], "model changed during generation")
            return {"text": "ok"}

        backend.prepare.side_effect = prepare
        backend.infer.side_effect = infer
        with mock.patch.object(serve.Handler, "backend", return_value=backend):
            first = self.start(lambda: self.handler._infer(A, {}))
            self.assertTrue(started.wait(5))
            second = self.start(lambda: self.handler._infer(B, {}))
            try:
                self.assertFalse(switched.wait(0.1), "switch interrupted active generation")
            finally:
                release.set()
                first.join(5)
                second.join(5)
            self.assertTrue(switched.is_set())

    def test_same_model_requests_can_overlap(self):
        started, joined, release = threading.Event(), threading.Event(), self.event()
        backend = mock.Mock()
        count = []
        lock = threading.Lock()

        def infer(model, payload):
            with lock:
                count.append(1)
                if len(count) == 1:
                    started.set()
                else:
                    joined.set()
            if not release.wait(5):
                raise AssertionError("generation never released")
            return {"text": "ok"}

        backend.infer.side_effect = infer
        with mock.patch.object(serve.Handler, "backend", return_value=backend):
            first = self.start(lambda: self.handler._infer(A, {}))
            self.assertTrue(started.wait(5))
            second = self.start(lambda: self.handler._infer(dict(A), {}))
            try:
                self.assertTrue(joined.wait(2), "same-model requests were serialized")
            finally:
                release.set()
                first.join(5)
                second.join(5)

    def test_model_switch_waits_until_stream_relay_finishes(self):
        started, release, switched = threading.Event(), self.event(), threading.Event()
        backend = mock.Mock(chat_completions_path="/v1/chat/completions", base_url="http://127.0.0.1:1")
        self.handler._payload = lambda: {"model": "a", "messages": [{"role": "user", "content": "hi"}]}

        def relay(*args):
            started.set()
            if not release.wait(5):
                raise AssertionError("stream never released")
            # A disconnected downstream still has to release its model.
            raise BrokenPipeError("client disconnected")

        def stream():
            with self.assertRaises(BrokenPipeError):
                self.handler.post_chat_completions()

        self.handler._relay_chat_completions = relay
        backend.prepare.side_effect = lambda model: switched.set()
        backend.infer.return_value = {"text": "ok"}
        with mock.patch.object(serve.Handler, "registry", {"models": {"a": A}}), mock.patch.object(serve.Handler, "backend", return_value=backend):
            first = self.start(stream)
            self.assertTrue(started.wait(5))
            second = self.start(lambda: self.handler._infer(B, {}))
            try:
                self.assertFalse(switched.wait(0.1), "switch interrupted active stream")
            finally:
                release.set()
                first.join(5)
                second.join(5)
            self.assertTrue(switched.is_set())
            self.assertEqual(serve.USE.in_flight("llama-gguf"), 0)

    def test_failed_prepare_releases_model_for_retry(self):
        backend = mock.Mock()
        backend.prepare.side_effect = [serve.BackendError("cannot load"), None]
        backend.infer.return_value = {"text": "recovered"}
        with mock.patch.object(serve.Handler, "backend", return_value=backend):
            with self.assertRaises(serve.BackendError):
                self.handler._infer(A, {})
            thread = self.start(lambda: self.assertEqual(self.handler._infer(B, {})["text"], "recovered"))
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(serve.USE.in_flight("llama-gguf"), 0)

    def test_interrupted_waiter_does_not_block_later_requests(self):
        leases = serve.ModelLeases()
        with leases.using("llama-gguf", A["path"]):
            with mock.patch.object(leases._cond, "wait", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    with leases.using("llama-gguf", "/models/interrupted"):
                        self.fail("interrupted request was admitted")
        finished = threading.Event()

        def later():
            with leases.using("llama-gguf", B["path"]):
                finished.set()

        thread = self.start(later)
        self.assertTrue(finished.wait(2), "interrupted waiter poisoned the queue")
        thread.join(2)

    def test_other_backend_can_run_during_active_model_lease(self):
        leases = serve.ModelLeases()
        finished = threading.Event()
        with leases.using("llama-gguf", A["path"]):
            def other():
                with leases.using("mlx-vlm", B["path"]):
                    finished.set()
            thread = self.start(other)
            self.assertTrue(finished.wait(2), "unrelated backends were serialized")
            thread.join(2)
