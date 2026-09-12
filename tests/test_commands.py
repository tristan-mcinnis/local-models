"""The house command manifest: its shape against the contract, and the promise
that publishing it can never cost the daemon.

`design-system/docs/app-commands.md` is the contract under test. Nothing here
loads a model, spawns a server, or writes outside a temporary directory:
`$HOUSE_COMMANDS_DIR` points every write at a temp dir, so running the suite
never touches the manifest of the daemon a person is using.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import importlib.util
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

import commands  # noqa: E402  (the daemon imports the same module object)

spec = importlib.util.spec_from_file_location("serve", REPO / "server" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)

BASE_URL = "http://127.0.0.1:8078"
#: Every route the manifest is allowed to point a command at. A command that
#: destroys anything must never appear here; the contract keeps deleting,
#: overwriting and clearing inside the app that owns them.
SAFE_VERBS = {"/v1/warm", "/v1/unload"}
#: Whole words, not substrings: "warm" contains "rm".
DESTRUCTIVE_WORDS = {"delete", "remove", "purge", "clear", "erase", "reset", "rm", "drop"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def state(model_id: str, warm: bool = False, in_flight: int = 0) -> dict:
    """One entry shaped like `GET /v1/models` reports it."""
    return {"id": model_id, "warm": warm, "in_flight": in_flight}


def write_registry(tmp: Path) -> Path:
    (tmp / "fake-vision").mkdir()
    (tmp / "fake-completion").mkdir()
    registry = {
        "version": 1,
        "default": "fake-vision",
        "server": {"base_url": f"http://127.0.0.1:{free_port()}", "api": "mlx-vlm"},
        "aliases": {},
        "models": {
            "fake-vision": {
                "name": "fake-vision",
                "path": str(tmp / "fake-vision"),
                "backend": "mlx-vlm",
                "size_bytes": 0,
                "capabilities": ["vision"],
            },
            "fake-completion": {
                "name": "fake-completion",
                "path": str(tmp / "fake-completion"),
                "backend": "llama-gguf",
                "size_bytes": 0,
                "capabilities": ["completion"],
            },
        },
    }
    path = tmp / "models.json"
    path.write_text(json.dumps(registry))
    return path


class ManifestShapeTests(unittest.TestCase):
    """The manifest against the contract's schema, field by field."""

    def setUp(self) -> None:
        self.manifest = commands.build_manifest(BASE_URL)

    def test_top_level_fields(self) -> None:
        self.assertEqual(self.manifest["schema"], 1)
        self.assertEqual(self.manifest["app"], "models")
        self.assertTrue(self.manifest["name"])
        self.assertEqual(self.manifest["transport"], "http")
        self.assertEqual(self.manifest["endpoint"], BASE_URL)
        self.assertTrue(self.manifest["status"].startswith("/"))
        self.assertTrue(self.manifest["commands"])

    def test_manifest_is_json(self) -> None:
        self.assertEqual(json.loads(json.dumps(self.manifest)), self.manifest)

    def test_every_command_has_the_contract_fields(self) -> None:
        for command in self.manifest["commands"]:
            with self.subTest(command["id"]):
                self.assertTrue(command["id"])
                self.assertIn(command["needs"], (None, "text", "choice"))
                self.assertTrue(command["verb"].startswith("/"))
                self.assertIsInstance(command["unavailableWhen"], (str, type(None)))

    def test_titles_are_user_visible_strings(self) -> None:
        """Sentence case, naming the effect: "Warm Model", not "warm_model"."""
        for command in self.manifest["commands"]:
            title = command["title"]
            with self.subTest(title):
                self.assertEqual(title, title.strip())
                self.assertTrue(title[0].isupper())
                self.assertNotIn("_", title)

    def test_command_ids_are_unique(self) -> None:
        ids = [command["id"] for command in self.manifest["commands"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_choice_command_names_a_route_to_read_it_from(self) -> None:
        """The registry changes under a running daemon, so a list frozen at
        launch would be wrong. Every `needs: "choice"` command says where the
        live list comes from."""
        for command in self.manifest["commands"]:
            if command["needs"] == "choice":
                with self.subTest(command["id"]):
                    self.assertTrue(command["choicesFrom"].startswith("/"))

    def test_unavailable_when_names_a_boolean_of_the_status_document(self) -> None:
        status = commands.status_document([state("a", warm=True)])
        for command in self.manifest["commands"]:
            clause = command["unavailableWhen"]
            if clause is None:
                continue
            field = clause[1:] if clause.startswith("!") else clause
            with self.subTest(clause):
                self.assertIn(field, status)
                self.assertIsInstance(status[field], bool)

    def test_no_command_destroys_anything(self) -> None:
        for command in self.manifest["commands"]:
            with self.subTest(command["id"]):
                self.assertIn(command["verb"], SAFE_VERBS)
                words = set(re.findall(r"[a-z]+", f"{command['id']} {command['title']}".lower()))
                self.assertFalse(words & DESTRUCTIVE_WORDS)

    def test_warm_and_unload_are_published(self) -> None:
        by_id = {command["id"]: command for command in self.manifest["commands"]}
        self.assertEqual(by_id["model.warm"]["needs"], "choice")
        self.assertEqual(by_id["model.unload"]["needs"], "choice")
        # Nothing warm, nothing to unload.
        self.assertEqual(by_id["model.unload"]["unavailableWhen"], "!warm")


class StatusDocumentTests(unittest.TestCase):
    """The contract's status document: app, ok, busy, detail, plus the
    booleans the manifest's `unavailableWhen` clauses name."""

    def test_required_fields(self) -> None:
        status = commands.status_document([])
        self.assertEqual(status["app"], "models")
        self.assertIs(status["ok"], True)
        self.assertIsInstance(status["busy"], bool)
        self.assertIsInstance(status["warm"], bool)
        self.assertIsInstance(status["detail"], str)

    def test_nothing_warm_reads_idle(self) -> None:
        status = commands.status_document([state("a"), state("b")])
        self.assertFalse(status["warm"])
        self.assertFalse(status["busy"])
        self.assertEqual(status["detail"], "Idle")

    def test_one_warm_model_is_singular(self) -> None:
        status = commands.status_document([state("a", warm=True), state("b")])
        self.assertTrue(status["warm"])
        self.assertEqual(status["detail"], "1 model warm")

    def test_several_warm_models_are_counted(self) -> None:
        status = commands.status_document([state("a", warm=True), state("b", warm=True)])
        self.assertEqual(status["detail"], "2 models warm")

    def test_a_request_in_flight_is_busy(self) -> None:
        status = commands.status_document([state("a", warm=True, in_flight=1)])
        self.assertTrue(status["busy"])
        self.assertEqual(status["detail"], "Working")

    def test_detail_is_one_short_phrase(self) -> None:
        for states in ([], [state("a", warm=True)], [state("a", in_flight=2)]):
            detail = commands.status_document(states)["detail"]
            with self.subTest(detail):
                self.assertLessEqual(len(detail), 40)
                self.assertNotIn("\n", detail)


class ChoiceTests(unittest.TestCase):
    def test_choices_are_the_registry_ids(self) -> None:
        choices = commands.model_choices([state("vision", warm=True), state("completion")])
        self.assertEqual([choice["id"] for choice in choices], ["vision", "completion"])
        self.assertEqual([choice["title"] for choice in choices], ["vision", "completion"])
        self.assertEqual([choice["detail"] for choice in choices], ["Warm", "Cold"])

    def test_no_models_is_an_empty_list_not_an_error(self) -> None:
        self.assertEqual(commands.model_choices([]), [])


class WriteManifestTests(unittest.TestCase):
    """Publishing the file, and failing to, in a temp directory."""

    @contextlib.contextmanager
    def commands_home(self, directory: Path):
        with mock.patch.dict(os.environ, {"HOUSE_COMMANDS_DIR": str(directory)}):
            yield

    def test_writes_the_manifest_where_readers_look(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "House" / "commands"
            with self.commands_home(home):
                written = commands.write_manifest(BASE_URL)
                self.assertEqual(written, commands.manifest_path())
                self.assertEqual(written.name, "models.json")
                self.assertEqual(json.loads(written.read_text()), commands.build_manifest(BASE_URL))

    def test_write_leaves_no_temporary_file_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "commands"
            with self.commands_home(home):
                commands.write_manifest(BASE_URL)
                self.assertEqual([path.name for path in home.iterdir()], ["models.json"])

    def test_a_rewrite_replaces_the_old_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "commands"
            with self.commands_home(home):
                commands.write_manifest("http://127.0.0.1:1")
                written = commands.write_manifest("http://127.0.0.1:2")
                self.assertEqual(json.loads(written.read_text())["endpoint"], "http://127.0.0.1:2")

    def test_a_failed_write_is_logged_and_swallowed(self) -> None:
        """A manifest is never worth a daemon: an unwritable location returns
        None and logs, and raises nothing at all."""
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not-a-directory"
            blocker.write_text("i am a file")
            captured = io.StringIO()
            with self.commands_home(blocker / "commands"), contextlib.redirect_stderr(captured):
                self.assertIsNone(commands.write_manifest(BASE_URL))
            self.assertIn("could not publish command manifest", captured.getvalue())


class StubBackend:
    """Every backend the daemon builds in these tests: it answers status
    without dialling a live data-plane port, and records what was warmed."""

    def __init__(self, *args, **kwargs) -> None:
        self.base_url = "http://127.0.0.1:1"
        self.warmed: list[str] = []

    def status(self) -> dict:
        return serve.status_dict(True, None, "stubbed")

    def prepare(self, model) -> None:
        pass

    def warm(self, model, payload) -> dict:
        self.warmed.append(serve.model_path(model))
        return {"text": "ok"}

    def unload(self) -> dict:
        return {"message": "unloaded"}


class BlockingStubBackend(StubBackend):
    """A backend whose warm takes as long as the test wants it to, standing in
    for a cold model: tens of seconds of loading, without a model."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.loading = threading.Event()
        self.release = threading.Event()
        self.unloads = 0

    def warm(self, model, payload) -> dict:
        self.loading.set()
        if not self.release.wait(timeout=30):
            raise AssertionError("background warm was never released")
        return super().warm(model, payload)

    def unload(self) -> dict:
        self.unloads += 1
        return super().unload()


class DaemonHarness:
    """Boots a real daemon on a spare port for the test cases below. Not a
    TestCase itself, so its helpers are shared without its tests being run
    twice."""

    def boot(self, tmp: Path, commands_home: Path | None = None, backend=None):
        backend = backend or StubBackend()
        serve.Handler.backend_cache = {}
        self.addCleanup(setattr, serve.Handler, "backend_cache", {})
        patch = mock.patch.object(serve, "get_backend", side_effect=lambda *a, **k: backend)
        patch.start()
        self.addCleanup(patch.stop)

        home = commands_home or (tmp / "commands")
        env = mock.patch.dict(os.environ, {"HOUSE_COMMANDS_DIR": str(home)})
        env.start()
        self.addCleanup(env.stop)

        captured = io.StringIO()
        redirect = contextlib.redirect_stderr(captured)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

        args = argparse.Namespace(port=free_port(), registry=write_registry(tmp), ensure_vision=False)
        server = serve.make_server(args)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, backend, captured

    def request(self, port: int, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        payload = None if body is None else json.dumps(body).encode()
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

class DaemonTests(DaemonHarness, unittest.TestCase):
    """The routes the manifest points at, on a real daemon on a spare port."""

    def test_startup_publishes_the_manifest_for_the_port_it_serves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = self.boot(Path(tmp))
            manifest = json.loads(commands.manifest_path().read_text())
            self.assertEqual(manifest["endpoint"], f"http://127.0.0.1:{server.server_address[1]}")
            self.assertEqual(manifest["app"], "models")

    def test_status_route_answers_the_contract_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = self.boot(Path(tmp))
            manifest = json.loads(commands.manifest_path().read_text())
            status, body = self.request(server.server_address[1], "GET", manifest["status"])
            self.assertEqual(status, 200)
            self.assertEqual(body["app"], "models")
            self.assertIs(body["ok"], True)
            self.assertIs(body["busy"], False)
            self.assertIs(body["warm"], False)
            self.assertEqual(body["detail"], "Idle")

    def test_choices_route_lists_the_current_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = self.boot(Path(tmp))
            manifest = json.loads(commands.manifest_path().read_text())
            route = manifest["commands"][0]["choicesFrom"]
            status, body = self.request(server.server_address[1], "GET", route)
            self.assertEqual(status, 200)
            self.assertEqual(
                sorted(choice["id"] for choice in body["choices"]),
                ["fake-completion", "fake-vision"],
            )

    def test_a_command_argument_names_the_model(self) -> None:
        """The house contract sends one argument; this daemon calls the field
        `model`. Both reach the same place, so Quick Launch needs to know
        nothing about this API's field names."""
        with tempfile.TemporaryDirectory() as tmp:
            server, backend, _ = self.boot(Path(tmp))
            status, body = self.request(
                server.server_address[1], "POST", "/v1/warm", {"argument": "fake-completion"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["model"], "fake-completion")
            self.assertTrue(backend.warmed[0].endswith("fake-completion"))

    def test_a_manifest_that_cannot_be_written_does_not_stop_the_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not-a-directory"
            blocker.write_text("i am a file")
            server, _, captured = self.boot(Path(tmp), commands_home=blocker / "commands")
            status, body = self.request(server.server_address[1], "GET", "/health")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "ok")
            self.assertIn("could not publish command manifest", captured.getvalue())


class NonBlockingWarmTests(DaemonHarness, unittest.TestCase):
    """`{"wait": false}` starts the load and returns, per the contract's rule
    that nothing may block the caller for more than a second."""

    def start_load(self, tmp: Path):
        """Boot a daemon and leave a background warm loading. Returns the
        server, the backend holding the load open, and the reply."""
        backend = BlockingStubBackend()
        self.addCleanup(backend.release.set)
        server, backend, _ = self.boot(tmp, backend=backend)
        began = time.monotonic()
        status, body = self.request(
            server.server_address[1], "POST", "/v1/warm", {"argument": "fake-vision", "wait": False}
        )
        self.elapsed = time.monotonic() - began
        self.assertEqual(status, 200)
        self.assertTrue(backend.loading.wait(timeout=10), "the load never started")
        return server, backend, body

    def drain(self, backend) -> None:
        """Let the load finish and wait for the claim to come back."""
        backend.release.set()
        deadline = time.monotonic() + 10
        while serve.USE.in_flight("mlx-vlm") and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_it_returns_while_the_model_is_still_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, backend, body = self.start_load(Path(tmp))
            self.assertLess(self.elapsed, 1.0)
            self.assertIs(body["warmed"], False)
            self.assertIs(body["started"], True)
            self.assertEqual(body["model"], "fake-vision")
            self.assertFalse(backend.release.is_set())
            self.drain(backend)

    def test_the_status_document_is_busy_while_it_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, backend, _ = self.start_load(Path(tmp))
            _, status = self.request(server.server_address[1], "GET", "/v1/status")
            self.assertIs(status["busy"], True)
            self.assertEqual(status["detail"], "Working")
            self.drain(backend)
            _, after = self.request(server.server_address[1], "GET", "/v1/status")
            self.assertIs(after["busy"], False)

    def test_the_clock_is_stamped_from_the_moment_the_work_starts(self) -> None:
        """Not when it finishes: a model mid-load must never read as idle."""
        with tempfile.TemporaryDirectory() as tmp:
            _, backend, _ = self.start_load(Path(tmp))
            idle, basis = serve.USE.idle_state("mlx-vlm")
            self.assertEqual(idle, 0.0)
            self.assertEqual(basis, "use")
            self.assertEqual(serve.USE.in_flight("mlx-vlm"), 1)
            self.drain(backend)

    def test_the_sweeper_cannot_unload_a_model_mid_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, backend, _ = self.start_load(Path(tmp))
            # The registry's other backend is idle and reclaimable, and the use
            # tracker is the daemon's, shared by every test in this process.
            # Drop its clock so this asserts one thing: the backend that is
            # mid-load survives a sweep it is long past the threshold for.
            serve.USE.forget("llama-gguf")
            sweeper = serve.IdleSweeper(serve.Handler, 0.01, interval=3600)
            self.assertEqual(sweeper.sweep(), [])
            self.assertEqual(backend.unloads, 0)
            self.assertEqual(serve.USE.in_flight("mlx-vlm"), 1)
            self.drain(backend)

    def test_the_claim_is_released_when_the_load_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, backend, _ = self.start_load(Path(tmp))
            self.drain(backend)
            self.assertEqual(serve.USE.in_flight("mlx-vlm"), 0)
            self.assertEqual(backend.warmed, [str(Path(tmp) / "fake-vision")])

    def test_a_failed_background_load_still_gives_the_claim_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = StubBackend()
            backend.warm = mock.Mock(side_effect=serve.BackendError("no weights"))
            server, backend, captured = self.boot(Path(tmp), backend=backend)
            _, body = self.request(server.server_address[1], "POST", "/v1/warm", {"wait": False})
            self.assertIs(body["started"], True)
            deadline = time.monotonic() + 10
            while serve.USE.in_flight("mlx-vlm") and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(serve.USE.in_flight("mlx-vlm"), 0)
            self.assertIn("background warm", captured.getvalue())

    def test_waiting_is_still_the_default(self) -> None:
        """Other apps depend on the reply they already get; this is additive."""
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = self.boot(Path(tmp))
            status, body = self.request(server.server_address[1], "POST", "/v1/warm", {})
            self.assertEqual(status, 200)
            self.assertIs(body["warmed"], True)
            self.assertEqual(body["text"], "ok")
            self.assertNotIn("started", body)

    def test_a_wait_that_is_not_a_boolean_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = self.boot(Path(tmp))
            status, body = self.request(server.server_address[1], "POST", "/v1/warm", {"wait": "no"})
            self.assertEqual(status, 400)
            self.assertIn("wait", body["error"])


if __name__ == "__main__":
    unittest.main()
