#!/usr/bin/env python3
"""local-models daemon: one local endpoint for a fleet of small models.

Routes by capability, resolves models from the registry, delegates to
pluggable backends, and reports which models are warm.

  GET  /health          daemon liveness + per-backend availability
  GET  /v1/models       registry with live warm/loaded state
  GET  /v1/status       house command status document (app, ok, busy, warm, detail)
  GET  /v1/choices/model  the model ids a house command can be pointed at
  POST /v1/vision       {"model"?, "prompt"?, "image_b64"|"image_path", "mime"?, "max_tokens"?, "timeout"?}
  POST /v1/ask          {"model"?, "prompt", "max_tokens"?, "timeout"?}
  POST /v1/complete     {"model"?, "prompt", "system"?, "max_tokens"?, "timeout"?}
  POST /v1/warm         {"model"?}  load a model and keep it warm
  POST /v1/unload       {"model"?}  unload the backend that owns that model
  POST /v1/transcribe   planned (501)

Warm models are the point of the daemon, but a model warmed once and then
forgotten holds its resident memory for days. Every request that puts a backend
to work stamps that backend's clock (reading state through /health or
/v1/models does not), and a sweeper thread unloads any backend that goes
`daemon.idle_unload_seconds` unused — 30 minutes by default, 0 to switch it
off, $LOCAL_MODELS_IDLE_UNLOAD_SECONDS to override. The next request readies
the backend again, so an idle unload costs a reload, never an error.

OpenAI-compatible passthrough (for clients that speak OpenAI chat, e.g.
Quick Launch's local provider), so no app needs a backend port:

  GET  /v1/openai/models          {"object": "list", "data": [{"id", "object": "model", "owned_by"}]}
  POST /v1/chat/completions       OpenAI chat body; "model" is a registry id or
                                  alias (or omitted for the default). The daemon
                                  readies the owning backend and relays the
                                  backend's reply byte-for-byte, streaming
                                  (SSE) or not. Unknown model is 404 here, as
                                  OpenAI clients expect.

Every success body is a JSON object. Every error body is
{"error": "<message>"} with an optional "hint"; status codes are
400 (bad request / unknown model), 404 (no route), 501 (planned, not
served), 502 (backend unreachable or failed).

Runs on 127.0.0.1 only. No auth by design: local socket, local user.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commands  # noqa: E402
from backends import BackendError, NotSupported, all_backends, get_backend, status_dict  # noqa: E402
from common import (  # noqa: E402
    DEFAULT_DAEMON_URL,
    OPENER,
    RegistryError,
    backend_name,
    idle_unload_seconds,
    load_registry,
    model_path,
    resolve_model,
)

DEFAULT_PORT = int(DEFAULT_DAEMON_URL.rsplit(":", 1)[-1])
#: How often the sweeper looks for idle backends. Coarse on purpose: the
#: threshold is minutes, so a minute of slack costs nothing and the sweep stays
#: invisible next to the work.
SWEEP_INTERVAL_SECONDS = 60.0
#: How long an explicit POST /v1/unload waits for in-flight requests to finish
#: before unloading anyway. The user asked for it, so it never refuses; it just
#: does not cut a request off mid-answer if it can help it.
MANUAL_UNLOAD_DRAIN_SECONDS = 30.0


def image_content(payload: dict, prompt: str) -> list[dict]:
    """OpenAI-style multimodal content from image_b64 or image_path."""
    mime = payload.get("mime")
    if payload.get("image_b64"):
        encoded = payload["image_b64"]
    elif payload.get("image_path"):
        path = Path(payload["image_path"]).expanduser()
        if not path.is_file():
            raise ValueError(f"image not found: {path}")
        encoded = base64.b64encode(path.read_bytes()).decode()
        mime = mime or mimetypes.guess_type(path.name)[0]
    else:
        raise ValueError("provide image_b64 or image_path")
    data_url = f"data:{mime or 'image/png'};base64,{encoded}"
    return [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": prompt},
    ]


def command_model(payload: dict) -> str | None:
    """The model a warm/unload call names.

    `model` is this daemon's own field. `argument` is the house command
    contract's: one command, one argument, whatever the app calls it. Accepting
    both keeps Quick Launch free of any knowledge of this API's field names
    without changing the wire format anyone already depends on.
    """
    return payload.get("model") or payload.get("argument")


def require_prompt(payload: dict) -> str:
    prompt = payload.get("prompt")
    if not prompt:
        raise ValueError("prompt is required")
    return prompt


def backend_is_warm(status: dict) -> bool:
    """Is this backend holding a model right now? One definition, shared by the
    model list and the sweeper, so both agree on what counts as warm."""
    return bool(status.get("available")) and status.get("loaded_model") is not None


class BackendUse:
    """When each backend was last used, and who is using it right now.

    The daemon is threaded: every request runs on its own thread and the idle
    sweeper runs on one more. This is the single place that knows both facts,
    and its lock is the one thing that keeps an unload from landing under a
    request that is still being served.

    Use means work a backend actually did: an inference, a warm, a relayed
    OpenAI chat. Reading state does not count — `/health` and `/v1/models` ask
    every backend how it is doing, and if that counted as use nothing would
    ever go idle, because the menu bar polls `/v1/models` on a timer.

    A backend can also be warm without this daemon ever having used it: an
    mlx-vlm server it merely adopted, or any backend still holding weights from
    before the daemon last restarted. That backend has no use stamp, so it also
    needs an age of its own, which is what `observe_warm` records.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        # One condition (and so one lock) guards all four maps below.
        self._cond = threading.Condition()
        self._last_used: dict[str, float] = {}
        # When a backend was first seen warm without having been used. The
        # fallback age, never a substitute for a real use stamp.
        self._warm_since: dict[str, float] = {}
        self._in_flight: dict[str, int] = {}
        self._unloading: set[str] = set()

    @contextlib.contextmanager
    def using(self, name: str):
        """Hold `name` in use for one request: stamp the clock, count it in
        flight, and wait out any unload already running so the request never
        talks to a backend that is being torn down."""
        with self._cond:
            while name in self._unloading:
                self._cond.wait()
            self._in_flight[name] = self._in_flight.get(name, 0) + 1
            self._last_used[name] = self._clock()
        try:
            yield
        finally:
            with self._cond:
                self._in_flight[name] = max(0, self._in_flight.get(name, 0) - 1)
                # Stamp again on the way out: a three-minute vision call is use
                # for its whole length, not just for the instant it started.
                self._last_used[name] = self._clock()
                self._cond.notify_all()

    def observe_warm(self, name: str, warm: bool) -> None:
        """Record whether `name` is holding a model right now.

        The first time a backend is seen warm with no use behind it, the moment
        of that sighting becomes its idle clock, and it ages from there. This is
        the honest reading of "we do not know when this was last wanted": it is
        not stamped as used just now, which would make it immortal, and it is
        not unloaded on sight, which would throw away a model warmed seconds
        before the daemon restarted. Seeing it warm again changes nothing — the
        age keeps running from the first sighting. Seeing it cold drops the
        observation, because there is no longer anything resident to age.

        Observing is not using: this never touches the use stamp, so the menu
        bar's polling still cannot keep a model warm.
        """
        with self._cond:
            if not warm:
                self._warm_since.pop(name, None)
            elif name not in self._warm_since:
                self._warm_since[name] = self._clock()

    def _since(self, name: str) -> float | None:
        """The instant `name`'s idle clock runs from, under the caller's lock:
        its last use, else when it was first seen warm, else nothing."""
        last = self._last_used.get(name)
        if last is not None:
            return last
        return self._warm_since.get(name)

    def idle_state(self, name: str) -> tuple[float | None, str | None]:
        """`(idle_seconds, basis)`: how long `name` has been idle and where that
        number comes from — "use" for work it did, "observed-warm" for a backend
        found warm with no use behind it, and `(None, None)` when it is neither.
        """
        with self._cond:
            if self._in_flight.get(name, 0):
                return 0.0, "use"
            last = self._last_used.get(name)
            if last is not None:
                return max(0.0, self._clock() - last), "use"
            seen = self._warm_since.get(name)
            if seen is not None:
                return max(0.0, self._clock() - seen), "observed-warm"
            return None, None

    def idle_seconds(self, name: str) -> float | None:
        """Seconds since `name` last finished work, 0.0 while it is working,
        falling back to how long it has been seen warm. None when it has done no
        work and has never been seen holding a model."""
        return self.idle_state(name)[0]

    def in_flight(self, name: str) -> int:
        with self._cond:
            return self._in_flight.get(name, 0)

    def forget(self, name: str) -> None:
        """Drop `name`'s idle clock: an unloaded backend has nothing to age."""
        with self._cond:
            self._last_used.pop(name, None)
            self._warm_since.pop(name, None)

    @contextlib.contextmanager
    def unload_claim(self, name: str, min_idle: float | None = None, wait: float = 0.0):
        """Own the unload of `name` for the block; yields True when granted.

        While the claim is held `using()` blocks, so no new request starts
        against a backend that is being torn down, and a request already in
        flight is waited out: the claim is only granted once the in-flight
        count is zero. `min_idle` is the sweeper's extra condition — idle at
        least that long, counted from the backend's last use or, failing that,
        from when it was first seen warm, and never granted to a backend with no
        idle clock at all. `wait` is how long to wait for in-flight requests to
        drain; the
        sweeper passes 0 and simply tries again on its next tick.
        """
        granted = False
        with self._cond:
            deadline = time.monotonic() + wait
            while self._in_flight.get(name, 0) or name in self._unloading:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(timeout=remaining)
            if not self._in_flight.get(name, 0) and name not in self._unloading:
                since = self._since(name)
                idle_enough = min_idle is None or (
                    since is not None and self._clock() - since >= min_idle
                )
                if idle_enough:
                    self._unloading.add(name)
                    granted = True
        try:
            yield granted
        finally:
            if granted:
                with self._cond:
                    self._unloading.discard(name)
                    self._last_used.pop(name, None)
                    self._warm_since.pop(name, None)
                    self._cond.notify_all()


#: The daemon's one use tracker, shared by the request handler and the sweeper.
USE = BackendUse()


class IdleSweeper(threading.Thread):
    """Unloads backends nobody has used for a while.

    Warm weights are the point of this daemon, but a model warmed once and then
    forgotten holds its resident memory until someone remembers to unload it —
    in practice, for days. This walks every backend that could be holding one
    and unloads any whose idle clock is older than the threshold.

    "Could be holding one" is wider than "the daemon built it". A model can be
    warm inside a server the daemon only adopted, and any model stays warm
    across a daemon restart, which resets every use stamp. Both are the same
    case from here: warm, with nothing recorded against it. Each tick asks every
    candidate backend whether it is warm and records the answer, so a backend
    like that ages from the first tick that saw it and becomes claimable one
    threshold later. An adopted server is unloaded through its own `/unload`;
    the server process itself is never touched.

    It can never unload a backend out from under a request: the claim it takes
    is the same one `BackendUse.using()` waits on, and it is granted only when
    nothing is in flight. A backend it cannot claim is simply left for the next
    tick.
    """

    def __init__(self, handler, threshold: float, interval: float = SWEEP_INTERVAL_SECONDS, use: BackendUse | None = None):
        super().__init__(name="idle-sweeper", daemon=True)
        self.handler = handler
        self.threshold = threshold
        self.interval = interval
        self.use = use or USE
        self._stop = threading.Event()

    @property
    def enabled(self) -> bool:
        return self.threshold > 0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            self.sweep()

    def sweep(self) -> list[str]:
        """One pass. Returns the names of the backends it unloaded."""
        if not self.enabled:
            return []
        unloaded = []
        for name in self.handler.sweep_candidates():
            self.use.observe_warm(name, backend_is_warm(self.handler.backend_status(name)))
            if self.use.idle_seconds(name) is None:
                # Cold, and nothing recorded against it: nothing to reclaim.
                continue
            with self.use.unload_claim(name, min_idle=self.threshold) as granted:
                if not granted:
                    continue
                try:
                    self.handler.backend(name).unload()
                except BackendError as exc:
                    # An unload the daemon is not allowed to do (a llama-server
                    # someone else started) is reported once and then left
                    # alone: the claim clears the idle clock on the way out, so
                    # this does not repeat every tick.
                    print(f"idle unload of {name} skipped: {exc}", file=sys.stderr, flush=True)
                    continue
                unloaded.append(name)
                print(
                    f"idle unload: {name} went {self.threshold:.0f}s unused",
                    file=sys.stderr,
                    flush=True,
                )
        return unloaded


class Handler(BaseHTTPRequestHandler):
    registry: dict = {}
    # One backend instance per name for the daemon's lifetime, so backends that
    # own child processes (llama-server) keep them across requests.
    backend_cache: dict = {}

    @classmethod
    def backend(cls, name: str):
        if name not in cls.backend_cache:
            cls.backend_cache[name] = get_backend(name, cls.registry)
        return cls.backend_cache[name]

    @classmethod
    def sweep_candidates(cls) -> list[str]:
        """Every backend that could be holding a model: the ones this daemon has
        built, plus every backend a registered model names. The second half is
        the adopted case — a vision server started by launchd is warm without
        this daemon ever building its backend, so the cache alone would miss it.
        """
        names = list(cls.backend_cache)
        for model in cls.registry.get("models", {}).values():
            name = backend_name(model)
            if name not in names:
                names.append(name)
        return names

    @classmethod
    def backend_status(cls, name: str) -> dict:
        try:
            return cls.backend(name).status()
        except BackendError as exc:
            return status_dict(False, None, str(exc))

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):  # quiet by default; launchd captures stderr
        if os.environ.get("LOCAL_MODELS_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, message: str, hint: str | None = None) -> None:
        body = {"error": message}
        if hint:
            body["hint"] = hint
        self._send(code, body)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}")

    def _dispatch(self, routes: dict) -> None:
        handler = routes.get(self.path)
        if handler is None:
            self._error(404, f"no route {self.path}")
            return
        try:
            handler()
        except (ValueError, RegistryError) as exc:
            self._error(400, str(exc))
        except NotSupported as exc:
            self._error(501, str(exc), hint="see docs/layer-contract.md")
        except BackendError as exc:
            self._error(502, str(exc))

    def _infer(self, model: dict, payload: dict) -> dict:
        name = backend_name(model)
        with USE.using(name):
            backend = self.backend(name)
            # Idle unloading means the backend that served the last call may be
            # cold now, so ready it first: the caller pays a reload, not a 502.
            backend.prepare(model)
            return backend.infer(model, payload)

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        self._dispatch(
            {
                "/health": self.get_health,
                "/v1/models": self.get_models,
                "/v1/status": self.get_status,
                commands.CHOICES_ROUTE: self.get_model_choices,
                "/v1/openai/models": self.get_openai_models,
            }
        )

    def get_health(self) -> None:
        backends = {name: self.backend_status(name) for name in all_backends()}
        self._send(200, {"status": "ok", "service": "local-models", "backends": backends})

    def model_states(self) -> list[dict]:
        """Every registered model with its live warm state and idle clock.

        `idle_seconds` is a property of the backend, not of the model: two
        models on one backend report the same number, because one unload frees
        both. It counts from the backend's last piece of work, or — for a
        backend found warm with no work behind it, such as an adopted server or
        one still warm from before a daemon restart — from when the daemon first
        saw it warm. `idle_basis` says which of the two it is, and both are null
        only for a backend that is cold and unused. Listing is not use, so
        calling this never keeps a model warm.
        """
        out = []
        status_cache: dict[str, dict] = {}
        for key, model in self.registry.get("models", {}).items():
            name = backend_name(model)
            if name not in status_cache:
                status_cache[name] = self.backend_status(name)
                # Seeing a backend warm is not use, but it does start its clock:
                # a backend warm with nothing recorded against it would
                # otherwise report null forever and never age.
                USE.observe_warm(name, backend_is_warm(status_cache[name]))
            status = status_cache[name]
            resolved_path = model_path(model)
            try:
                endpoint = self.backend(name).base_url
            except BackendError:
                endpoint = None
            idle, idle_basis = USE.idle_state(name)
            out.append(
                {
                    "id": key,
                    "backend": name,
                    "capabilities": model.get("capabilities", []),
                    "path": resolved_path,
                    "warm": status.get("loaded_model") == resolved_path,
                    "backend_available": status.get("available", False),
                    "endpoint": endpoint,
                    "idle_seconds": None if idle is None else round(idle, 1),
                    "idle_basis": idle_basis,
                    "in_flight": USE.in_flight(name),
                }
            )
        return out

    def get_models(self) -> None:
        self._send(
            200,
            {
                "default": self.registry.get("default"),
                "idle_unload_seconds": idle_unload_seconds(self.registry),
                "models": self.model_states(),
            },
        )

    def get_status(self) -> None:
        """The house command contract's status document, so Quick Launch can
        keep a command row honest (see `server/commands.py`). Derived from the
        same model state `/v1/models` reports — one source of truth — and, like
        that route, reading it is not use, so polling it never keeps a model
        warm."""
        self._send(200, commands.status_document(self.model_states()))

    def get_model_choices(self) -> None:
        """What a `needs: "choice"` command can be pointed at right now. The
        registry changes under a running daemon, so the manifest names this
        route instead of freezing a list at launch."""
        self._send(200, {"choices": commands.model_choices(self.model_states())})

    def get_openai_models(self) -> None:
        """OpenAI `GET /v1/models` shape: ids plus aliases of every model whose
        backend can answer /v1/chat/completions (TTS / STT entries stay out)."""
        models = {}
        for key, model in self.registry.get("models", {}).items():
            try:
                if self.backend(backend_name(model)).chat_completions_path:
                    models[key] = model
            except BackendError:
                continue
        data = [{"id": key, "object": "model", "owned_by": "local-models"} for key in models]
        for alias, target in self.registry.get("aliases", {}).items():
            if alias not in models and target in models:
                data.append({"id": alias, "object": "model", "owned_by": "local-models"})
        self._send(200, {"object": "list", "data": data})

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        self._dispatch(
            {
                "/v1/chat/completions": self.post_chat_completions,
                "/v1/vision": self.post_vision,
                "/v1/ask": self.post_ask,
                "/v1/complete": self.post_complete,
                "/v1/warm": self.post_warm,
                "/v1/unload": self.post_unload,
                "/v1/transcribe": self.post_transcribe,
            }
        )

    def post_vision(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        prompt = payload.get("prompt") or "Describe this image accurately and concisely."
        messages = [{"role": "user", "content": image_content(payload, prompt)}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_ask(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        messages = [{"role": "user", "content": require_prompt(payload)}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_complete(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, payload.get("model"))
        prompt = require_prompt(payload)
        system = payload.get(
            "system",
            "Continue the user's text naturally and concisely. "
            "Return only the continuation; do not repeat the input.",
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        result = self._infer(model, {**payload, "messages": messages})
        self._send(200, {"model": key, "text": result["text"]})

    def post_warm(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, command_model(payload))
        name = backend_name(model)
        with USE.using(name):
            result = self.backend(name).warm(model, payload)
        self._send(200, {"model": key, "warmed": True, "text": result["text"]})

    def post_unload(self) -> None:
        payload = self._payload()
        key, model = resolve_model(self.registry, command_model(payload))
        name = backend_name(model)
        # An explicit unload is what the user asked for, so it never refuses on
        # a busy backend: it waits a bounded time for in-flight requests to
        # finish, then unloads either way, as it always has.
        with USE.unload_claim(name, wait=MANUAL_UNLOAD_DRAIN_SECONDS):
            result = self.backend(name).unload()
        USE.forget(name)
        self._send(200, {"model": key, "unloaded": True, "message": result.get("message", "unloaded")})

    def post_transcribe(self) -> None:
        self._payload()
        raise NotSupported("transcribe is planned but not served yet (phase 2)")

    # -- OpenAI passthrough ---------------------------------------------------
    def post_chat_completions(self) -> None:
        payload = self._payload()
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise ValueError("messages is required")
        try:
            key, model = resolve_model(self.registry, payload.get("model"))
        except RegistryError as exc:
            self._error(404, str(exc))
            return
        name = backend_name(model)
        backend = self.backend(name)
        if backend.chat_completions_path is None or backend.base_url is None:
            raise NotSupported(f"backend '{backend.name}' has no OpenAI chat endpoint")
        # In use for the whole relay, not just the handshake: an SSE stream can
        # run for minutes and must not be unloaded out from under the client.
        with USE.using(name):
            self._relay_chat_completions(backend, key, model, payload)

    def _relay_chat_completions(self, backend, key: str, model: dict, payload: dict) -> None:
        backend.prepare(model)
        # The backends key on the weight path, not the registry id.
        body = json.dumps({**payload, "model": model_path(model)}).encode()
        request = urllib.request.Request(
            backend.base_url.rstrip("/") + backend.chat_completions_path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": self.headers.get("Accept") or "*/*"},
        )
        timeout = float(payload.get("timeout") or 600)
        try:
            upstream = OPENER.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise BackendError(f"{backend.name} HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except OSError as exc:
            raise BackendError(f"{backend.name} unavailable at {backend.base_url}: {exc}")
        with upstream:
            self.send_response(upstream.status)
            self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Local-Models-Model", key)
            self.send_header("Connection", "close")
            self.end_headers()
            # Relay each chunk as it lands so SSE reaches the client live.
            while True:
                chunk = upstream.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()


def make_server(args) -> ThreadingHTTPServer:
    """Load the registry, run startup readying, and bind the HTTP server.

    A failed vision ensure (e.g. a launchd-managed server that never came up)
    is a warning, not a fatal startup error: the daemon still binds and serves
    degraded — vision calls return 502 until the backend is available — instead
    of killing the whole process. Publishing the house command manifest is the
    same kind of extra: it is written once the port is known, and a write that
    fails is logged and ignored.
    """
    try:
        Handler.registry = load_registry(args.registry)
    except RegistryError as exc:
        raise SystemExit(str(exc))
    if args.ensure_vision:
        try:
            get_backend("mlx-vlm", Handler.registry).ensure()
        except BackendError as exc:
            print(
                f"warning: vision backend not ensured; serving degraded: {exc}",
                file=sys.stderr,
                flush=True,
            )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    # The sweeper is attached to the server so the caller owns its lifetime;
    # it is a daemon thread, so a dead server never keeps the process alive.
    server.idle_sweeper = IdleSweeper(Handler, idle_unload_seconds(Handler.registry))
    if server.idle_sweeper.enabled:
        server.idle_sweeper.start()
        print(
            f"idle unload after {server.idle_sweeper.threshold:.0f}s unused",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("idle unload disabled (threshold 0)", file=sys.stderr, flush=True)
    # After the bind, so the manifest publishes the port actually being served.
    commands.write_manifest(f"http://127.0.0.1:{server.server_address[1]}")
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="local-models daemon")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCAL_MODELS_PORT", DEFAULT_PORT)))
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--ensure-vision", action="store_true", help="adopt, wait for a managed launchd owner, or spawn the mlx-vlm server at startup")
    args = parser.parse_args()

    server = make_server(args)
    print(f"local-models daemon on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
