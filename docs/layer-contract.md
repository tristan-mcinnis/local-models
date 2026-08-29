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
  extraction). Scriptable from anything: shell, launchd, agent skills.
- **Clients (`client/`)** — thin per-language wrappers. Apps never load
  weights, never shell out to model runtimes, never hardcode paths.

## Capability lifecycle

1. **Planned** — backend file exists, `status()` says unavailable, requests
   get a 501 with the reason. Honest refusal beats silent fallback.
2. **Serving** — backend loads/warms the model, endpoint returns results.
3. **Adopted** — apps that embedded their own runtime switch to the daemon,
   behind a flag first, in-process as fallback until trust is earned.

Vision is at 3 (the mlx-vlm server predates this repo and was adopted).
Completion and transcription are at 1 by design: the apps that own those
models are under active development, and porting them waits until they
stabilize.

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
