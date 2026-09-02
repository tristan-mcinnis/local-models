# Consistency audit, 2026-09-02

Goal: one way of doing each thing across the daemon, backends, CLIs, Swift
client, and menu bar, so the client repos (Quick Launch, screenctx, cotype,
local-dictation) build on one contract.

## Found

- **CLIs bypassed the daemon.** `local-model` and `local-image` called the
  mlx-vlm server on port 8080 directly (`/chat/completions`, `/health`,
  `/unload`), so the repo had two request paths, two error styles, and
  `local-model status` reported the vision server, not the daemon.
- **Four copies of the HTTP helper** (`_request` in both backends, `request`
  in local-model, `call_server` in local-image) and three copies each of
  registry loading, `models_home`, and model resolution.
- **Loopback HTTP honoured the macOS system proxy.** urllib picked up the
  proxy at 127.0.0.1:1082, which answered 503 for backend ports that were
  closed. This broke a unit test and would misreport a down backend as an
  HTTP error in production.
- **Backend name drift.** Code registered `mlx-stt`; the live registry names
  the planned transcription backend `mlx-audio-stt`.
- **Unload response shape differed per backend** (mlx-vlm passed the upstream
  body through; llama-gguf returned `{"message"}`).
- **Endpoint mapping hardcoded by backend name in serve.py** instead of the
  backend declaring its data-plane URL. `model.get("backend", "mlx-vlm")`
  repeated five times. 404 handling duplicated across GET and POST.
- **Stale docs.** README said completion was phase 2 and returned 501; the
  example registry called the completion entry a phase-2 backend.
- **No CLAUDE.md / AGENTS.md.** GATES.md and `.unlazy/` are gitignored
  build ledgers from the 2026-08-29 session, not a contract.
- **Repo is PUBLIC** (`public_ok` recorded in code-atlas; GATES G8 verified
  it). The lead's brief said private; the atlas is right.
- No secrets or personal paths in tracked files (`tests/scrub.sh` clean).
  `dist/` and `.build/` are ignored, not committed.

## Fixed

- `server/common.py`: one definition of registry path, registry loading,
  model resolution (`RegistryError`), daemon URL (`LOCAL_MODELS_DAEMON` >
  registry `daemon.base_url` > 8078), and proxy-free `http_json`.
- Daemon, both backends, and both CLIs import it. The CLIs now make every
  model call through the daemon (`/v1/ask`, `/v1/vision`, `/v1/warm`,
  `/v1/unload`, `/health`, `/v1/models`). `local-model unload` takes an
  optional model. `local-model status` shows daemon health plus each backend.
- `serve.py`: table dispatch, one `_error` envelope, `backend.base_url` as
  the endpoint, `/v1/vision` accepts `mime` and infers it from `image_path`,
  `/v1/unload` returns `{model, unloaded, message}` (additive).
- `mlx-stt` renamed `mlx-audio-stt` (file and backend name).
- Tests: closed ports instead of port 1, uniform-envelope test, unload test,
  five CLI-through-daemon tests. `make test` also runs the scrub.
- README route table with request and success shapes, error envelope, and
  daemon-only CLI note. Example registry and layer contract corrected.
- `CLAUDE.md` (54 lines) with build, test, run, boundaries, privacy;
  `AGENTS.md` symlink.

## Route table

| Route | Purpose | Success | Error |
|---|---|---|---|
| GET /health | daemon + per-backend state | `{status, service, backends{name:{available, loaded_model, detail}}}` | `{error}` 404 |
| GET /v1/models | registry with warm state | `{default, models[{id, backend, capabilities, path, warm, backend_available, endpoint}]}` | `{error}` |
| POST /v1/vision | image + prompt | `{model, text}` | `{error, hint?}` 400/501/502 |
| POST /v1/ask | text prompt | `{model, text}` | same |
| POST /v1/complete | continuation | `{model, text}` | same |
| POST /v1/warm | load and keep warm | `{model, warmed, text}` | same |
| POST /v1/unload | free the backend | `{model, unloaded, message}` | same |
| POST /v1/transcribe | planned | | `{error, hint}` 501 |

## Left

- Quick Launch still points its local provider at `http://127.0.0.1:8080`
  (the raw mlx-vlm OpenAI-compatible port), not the daemon. That is a valid
  data-plane use, but it is the one client that names a backend port; the
  lead should decide whether it moves to `/v1/vision`.
- The vision server has two starters: the separate launchd agent
  `com.tristan.mlx-vlm-server` and the daemon's `--ensure-vision` spawn.
  Adopt-or-spawn is documented and works; it stays.
- Live registry carries `pocket-tts` and `mlx-audio-stt` entries the daemon
  cannot serve; they show as `backend_available: false` with an "unknown
  backend" detail for TTS. Honest, left as is.
- `local-image extract` against the UI schema on the synthetic fixture fails
  validation with the 2B model on old and new code alike (model omits an
  empty required array). Not a plumbing issue.
- Transcription serving is still phase 2.
