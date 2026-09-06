"""Ownership regression tests for the mlx-vlm backend's server lifecycle.

These exercise the adopt / wait-for-owner / spawn-one-child decision in
`MlxVlmBackend.ensure` without touching a live server, a network socket, or a
real subprocess. Everything that reaches out (health), waits (`monotonic`,
`sleep`), or launches (`subprocess.Popen`) is replaced with a fast fake.

Key guarantees under test:
  * A launchd-managed server (registry `server.launch_agent`) is waited for
    and is never spawned, even on a delayed or unavailable owner.
  * Without a managed owner, at most one loopback-only uvicorn child is
    spawned (no reload worker, no wildcard bind), and only that owned child is
    cleaned up on failure.
  * base_url is validated rather than string-split, refusing non-loopback
    hosts and malformed ports.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

from backends import BackendError, mlx_vlm  # noqa: E402

HEALTHY = {"status": "healthy", "loaded_model": None}
UNHEALTHY = [None]


def make_backend(base_url="http://127.0.0.1:8080", launch_agent=None):
    """A backend over a base_url, optionally naming a launchd owner."""
    registry = {"server": {"base_url": base_url, "api": "mlx-vlm"}}
    if launch_agent is not None:
        registry["server"]["launch_agent"] = launch_agent
    return mlx_vlm.MlxVlmBackend(registry)


def health_sequence(values):
    """Return a callable that yields each value in order, then repeats the last.

    `values` describes health over consecutive polls. Use `[None, None,
    HEALTHY]` to model a server that comes up on the third poll.
    """
    seq = iter(values)
    last = values[-1]

    def _health(*args, **kwargs):
        try:
            return next(seq)
        except StopIteration:
            return last

    return _health


class FakeChild:
    """Stand-in for subprocess.Popen. Records argv and lifecycle calls."""

    def __init__(self, argv, *, alive=True):
        self.argv = list(argv)
        self._alive = alive
        self.exitcode = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return None if self._alive else self.exitcode

    def terminate(self):
        self.terminate_calls += 1
        self._alive = False
        self.exitcode = -15

    def kill(self):
        self.kill_calls += 1
        self._alive = False
        self.exitcode = -9

    def wait(self, timeout=None):
        self.wait_calls += 1
        self._alive = False
        return self.exitcode


class FakeStubbornChild(FakeChild):
    """A child that ignores SIGTERM, forcing the cleanup path to force-kill it."""

    def __init__(self, argv):
        super().__init__(argv)
        self.wait_raises = 1

    def terminate(self):
        self.terminate_calls += 1
        self.exitcode = -15  # SIGTERM ignored: process stays alive

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_raises > 0:
            self.wait_raises -= 1
            raise subprocess.TimeoutExpired("child", timeout)
        self._alive = False
        return self.exitcode

    def kill(self):
        self.kill_calls += 1
        self._alive = False
        self.exitcode = -9


class FakeClock:
    """Incrementing monotonic clock paired with a no-op sleep, for fast waits."""

    def __init__(self):
        self.now = 0
        self.sleeps = 0

    def monotonic(self):
        self.now += 1
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1


class EnsureTestBase(unittest.TestCase):
    """Patches health, the clock, and Popen for the duration of one test.

    self.popen is the patched subprocess.Popen mock; set self.popen.return_value
    to control the child returned. self.clock tracks how long the wait loops ran.
    """

    def _start(self, backend, health_values):
        self.clock = FakeClock()
        self._health_p = mock.patch.object(backend, "health", side_effect=health_sequence(health_values))
        self._mono_p = mock.patch.object(mlx_vlm.time, "monotonic", side_effect=self.clock.monotonic)
        self._sleep_p = mock.patch.object(mlx_vlm.time, "sleep", side_effect=self.clock.sleep)
        self._popen_p = mock.patch.object(mlx_vlm.subprocess, "Popen", autospec=True)
        self.popen = self._popen_p.start()
        self._health_p.start()
        self._mono_p.start()
        self._sleep_p.start()
        for p in (self._health_p, self._mono_p, self._sleep_p, self._popen_p):
            self.addCleanup(p.stop)


class EnsureTests(EnsureTestBase):
    def test_adopts_healthy_server_without_spawning(self):
        backend = make_backend()
        self._start(backend, [HEALTHY])
        backend.ensure()
        self.popen.assert_not_called()

    def test_delayed_managed_owner_waits_without_spawning(self):
        # Health drops twice (launchd still bringing it up), then is healthy.
        # ensure() must wait and return, never spawning a child.
        backend = make_backend(launch_agent="com.example.mlx-vlm-server")
        self._start(backend, [None, None, HEALTHY])
        backend.ensure()
        self.popen.assert_not_called()

    def test_unavailable_managed_owner_times_out_actionably_without_spawn(self):
        # Owner never comes up: ensure() must raise an actionable message naming
        # the launchd agent, and must not spawn a competing child.
        backend = make_backend(launch_agent="com.example.mlx-vlm-server")
        self._start(backend, UNHEALTHY)
        with self.assertRaises(BackendError) as ctx:
            backend.ensure(wait_seconds=5)
        self.assertIn("com.example.mlx-vlm-server", str(ctx.exception))
        self.assertIn("launchd agent", str(ctx.exception))
        self.popen.assert_not_called()

    def test_never_spawns_a_second_child_while_one_is_alive(self):
        # A child we already own is alive but not yet healthy: a repeated
        # ensure() must wait on it, not spawn a competing server.
        backend = make_backend()
        backend._child = FakeChild(["python", "-m", "uvicorn", "mlx_vlm.server:app"])
        self._start(backend, UNHEALTHY)
        with self.assertRaises(BackendError):
            backend.ensure(wait_seconds=3)
        # The pre-existing child is the only spawn; no second Popen.
        self.popen.assert_not_called()

    def test_unmanaged_spawn_uses_loopback_uvicorn_no_reload(self):
        # No managed owner: spawn a loopback-only uvicorn child, not the
        # `-m mlx_vlm.server` entrypoint (which enables a reload worker), and
        # not the module default wildcard host.
        backend = make_backend()
        child = FakeChild(["placeholder"])
        self._start(backend, [None, HEALTHY])
        self.popen.return_value = child
        backend.ensure()
        argv = self.popen.call_args[0][0]
        self.assertIn("mlx_vlm.server:app", argv)
        self.assertEqual(argv[argv.index("--host") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--port") + 1], "8080")
        self.assertNotIn("0.0.0.0", argv)
        # uvicorn entrypoint, not `-m mlx_vlm.server`: no reload worker.
        self.assertEqual(argv[argv.index("-m") + 1], "uvicorn")

    def test_failed_owned_child_is_cleaned_up_only_on_timeout(self):
        # A spawned child never becomes healthy: ensure() must terminate that
        # owned child (and only that one), then raise.
        backend = make_backend()
        child = FakeChild(["python", "-m", "uvicorn", "mlx_vlm.server:app"])
        self._start(backend, UNHEALTHY)
        self.popen.return_value = child
        with self.assertRaises(BackendError):
            backend.ensure(wait_seconds=3)
        self.popen.assert_called_once()
        self.assertGreaterEqual(child.terminate_calls, 1)
        self.assertIsNone(backend._child)

    def test_base_url_parsing_rejects_nonloopback_host(self):
        backend = make_backend(base_url="http://0.0.0.0:8080")
        with self.assertRaises(BackendError):
            backend._spawn_target()

    def test_base_url_parsing_rejects_invalid_port(self):
        backend = make_backend(base_url="http://127.0.0.1:notaport")
        with self.assertRaises(BackendError):
            backend._spawn_target()

    def test_base_url_parsing_rejects_missing_port(self):
        backend = make_backend(base_url="http://127.0.0.1")
        with self.assertRaises(BackendError):
            backend._spawn_target()

    def test_spawn_target_keeps_loopback_bind_for_localhost(self):
        backend = make_backend(base_url="http://localhost:8081")
        host, port = backend._spawn_target()
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 8081)

    def test_base_url_parsing_rejects_https(self):
        backend = make_backend(base_url="https://127.0.0.1:8080")
        with self.assertRaises(BackendError):
            backend._spawn_target()

    def test_cleanup_force_kills_child_that_ignores_terminate(self):
        # A child that ignores SIGTERM (wait times out) must be force-killed,
        # and only that owned child is touched.
        backend = make_backend()
        child = FakeStubbornChild(["python", "-m", "uvicorn", "mlx_vlm.server:app"])
        backend._child = child
        backend._cleanup_owned_child()
        self.assertEqual(child.terminate_calls, 1)
        self.assertEqual(child.kill_calls, 1)
        self.assertGreaterEqual(child.wait_calls, 2)
        self.assertIsNone(backend._child)

    def test_respawns_a_child_that_has_already_died(self):
        # A dead owned child (poll() returns a code) is not waited on; a fresh
        # child is spawned instead.
        backend = make_backend()
        dead = FakeChild(["old"], alive=False)
        dead.exitcode = -9  # so poll() returns a code, i.e. a dead child
        backend._child = dead
        new_child = FakeChild(["python", "-m", "uvicorn", "mlx_vlm.server:app"])
        self._start(backend, [None, HEALTHY])
        self.popen.return_value = new_child
        backend.ensure()
        self.popen.assert_called_once()  # one fresh spawn, no wait-on-death
        self.assertIs(backend._child, new_child)

    def test_prepare_raises_without_spawning(self):
        # prepare() only readies the data plane; it must never spawn a child.
        backend = make_backend()
        self._start(backend, [None])
        with self.assertRaises(BackendError):
            backend.prepare({"path": "x"})
        self.popen.assert_not_called()


class SpawnArgvTests(unittest.TestCase):
    def test_argv_is_loopback_uvicorn_entrypoint(self):
        argv = mlx_vlm.MlxVlmBackend._spawn_argv("127.0.0.1", 8080)
        self.assertEqual(argv[argv.index("--host") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--port") + 1], "8080")
        # uvicorn entrypoint with the app import string (no reload worker).
        self.assertEqual(argv[argv.index("-m") + 1], "uvicorn")
        self.assertIn("mlx_vlm.server:app", argv)


if __name__ == "__main__":
    unittest.main()
