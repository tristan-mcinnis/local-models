# The layer contract

One machine, many tiny models, one owner of their lifecycle.

## Roles

- **`~/Models/` (outside this repo)** — weights + the live `models.json`
  registry. The only mutable state. Never in git.
- **The daemon (`server/serve.py`, port 8078)** — resolves models from the
  registry, delegates to backends, keeps models warm, reports state.
- **Backends (`server/backends/`)** — one plugin per runtime. Each declares
  `name`, `capabilities`, and implements `infer`/`status`/`unload`. The
  registry entry's `backend` field is the router.
- **CLIs (`cli/`)** — `local-model` (registry, lifecycle, pull, text/vision
  calls) and `local-image` (OCR, describe, UI inventory, schema-validated
  extraction). Scriptable from anything: shell, launchd, agent skills. Model
  calls go through the daemon, never to a backend port.
- **Shared plumbing (`server/common.py`)** — the one definition of the
  registry location, model resolution, the daemon URL, and proxy-free JSON
  over HTTP. Daemon, backends, and CLIs all import it.
- **Clients (`client/`)** — thin per-language wrappers. Apps never load
  weights, never shell out to model runtimes, never hardcode paths.

## Capability lifecycle

1. **Planned** — backend file exists, `status()` says unavailable, requests
   get a 501 with the reason. Honest refusal beats silent fallback.
2. **Serving** — backend loads/warms the model, endpoint returns results.
3. **Adopted** — apps that embedded their own runtime switch to the daemon,
   behind a flag first, in-process as fallback until trust is earned.

Vision is at 3 (the mlx-vlm server predates this repo and was adopted).
Completion reached 3 on 2026-08-29: the daemon manages a llama-server
(spawn on warm, stop on unload, thinking disabled), and the first client
app routes to it behind a user toggle with its in-process engine as the
off-switch fallback. Transcription stays at 1 until the dictation app
stabilizes.

## Server ownership

The vision backend (`mlx-vlm`) decides who owns its server in one of three
ways, so exactly one process ever answers a given `server.base_url`:

1. **Adopt** — if a server already answers at the registry `base_url`, the
   backend uses it as-is and never starts another.
2. **Wait for a managed owner** — if the registry names a `server.launch_agent`
   (a launchd agent), that agent owns the process. `ensure()` waits a bounded
   time for it to come up and never spawns a competing child; on timeout it
   raises an actionable error naming the agent.
3. **Spawn one child** — with no managed owner, `ensure()` spawns exactly one
   loopback-only, no-reload `uvicorn` child and waits for health on it. A child
   that fails to become healthy is terminated, and only a child the backend
   itself spawned is ever cleaned up, never a managed or adopted process.

`server.launch_agent` is an optional registry key. When set, it names a
launchd agent and makes that agent the single owner: the daemon waits for it
and never spawns a duplicate. When absent, the backend is unmanaged — the
daemon spawns one loopback-only child itself.

```json
{
  "server": {
    "base_url": "http://127.0.0.1:8080",
    "api": "mlx-vlm",
    "launch_agent": "com.example.mlx-vlm-server"
  }
}
```

Set `launch_agent` only when a launchd agent for that server is genuinely
installed under exactly that label. The label in the example is a placeholder;
use the label of the agent you actually loaded (`launchctl list`). If no agent
exists, omit the key — the default unmanaged behavior spawns its own
loopback-only child. The shipped example registry stays unmanaged by design.

An unmanaged child always binds `127.0.0.1` (explicit `--host`, via the uvicorn
entrypoint rather than the module that turns on a reload worker) and never
binds a wildcard interface.

This removes the historical race where two starters (a launchd agent and the
daemon's `--ensure-vision`) could both bring the same port up, leaving a
duplicate process listening next to the managed one. A duplicate costs a
second copy of the model's resident memory and exposes the server on a
non-loopback interface, so the ownership rule keeps the fleet to one warm,
loopback-only server per port.

## Latency budgets (what "serving" must mean)

| Capability | Budget | Why |
|---|---|---|
| completion | first token < 150 ms warm | ghost text at the cursor |
| vision | < 2 s for a screenshot | interactive Q&A |
| transcription | streaming, < 500 ms behind speech | dictation |

A backend that cannot meet its budget warm does not graduate to "serving".

## Extending

New capability = one backend file + registry entries + (optionally) a client
method. Candidates in order of pull: TTS, embeddings, reranking, structured
extraction as a first-class endpoint. The test for adding one: an app wants it
through the daemon, not a benchmark wants it to exist.
