"""Backend ownership under concurrent first access; no sockets or processes."""

from __future__ import annotations

import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))
spec = importlib.util.spec_from_file_location("serve_cache_tests", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class BackendCacheTests(unittest.TestCase):
    def setUp(self):
        cache = mock.patch.object(serve.Handler, "backend_cache", {})
        cache.start()
        self.addCleanup(cache.stop)

    def test_repeated_access_reuses_owner_and_names_stay_distinct(self):
        owners = {"mlx-vlm": object(), "llama-gguf": object()}
        with mock.patch.object(serve, "get_backend", side_effect=lambda name, registry: owners[name]) as factory:
            for name, owner in owners.items():
                self.assertIs(serve.Handler.backend(name), owner)
                self.assertIs(serve.Handler.backend(name), owner)
            self.assertEqual(factory.call_count, 2)

    def test_concurrent_first_access_constructs_one_owner(self):
        constructing = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        second_returned = threading.Event()
        results = []
        errors = []

        def factory(name, registry):
            constructing.set()
            if not release.wait(5):
                raise AssertionError("constructor never released")
            return object()

        def access(second=False):
            try:
                if second:
                    second_entered.set()
                results.append(serve.Handler.backend("llama-gguf"))
            except BaseException as exc:
                errors.append(exc)
            finally:
                if second:
                    second_returned.set()

        with mock.patch.object(serve, "get_backend", side_effect=factory) as create:
            first = threading.Thread(target=access)
            second = threading.Thread(target=access, args=(True,))
            first.start()
            try:
                self.assertTrue(constructing.wait(5))
                second.start()
                self.assertTrue(second_entered.wait(5))
                self.assertFalse(second_returned.wait(0.1))
                # Only the first constructor may run while its owner is unpublished.
                self.assertEqual(create.call_count, 1)
            finally:
                release.set()
                first.join(5)
                if second.ident is not None:
                    second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertIs(results[0], results[1])
            self.assertIs(serve.Handler.backend_cache["llama-gguf"], results[0])
            self.assertEqual(create.call_count, 1)

    def test_failed_or_interrupted_construction_can_retry(self):
        for failure in (serve.BackendError("not configured"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                serve.Handler.backend_cache = {}
                owner = object()
                with mock.patch.object(serve, "get_backend", side_effect=[failure, owner]) as factory:
                    with self.assertRaises(type(failure)):
                        serve.Handler.backend("llama-gguf")
                    self.assertNotIn("llama-gguf", serve.Handler.backend_cache)
                    self.assertIs(serve.Handler.backend("llama-gguf"), owner)
                    self.assertIs(serve.Handler.backend("llama-gguf"), owner)
                    self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
