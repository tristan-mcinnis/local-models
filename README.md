# local-models

**One local daemon for a fleet of tiny, specialized models.**

The future of local AI on a personal machine does not look like one big model.
It looks like many small ones: a 2B vision model, an OCR pass, a dictation
model, a completion model for ghost text, an extraction model that only ever
returns schema-valid JSON. Each is excellent at one narrow job, cheap enough to
keep warm, and private by construction.

The problem is that every app then embeds its own runtime, loads its own copy,
and burns its own RAM. Five local-AI apps become five model stacks.

`local-models` inverts that: **one registry, one daemon, warm models, thin
clients.** Apps make a localhost call; the daemon owns the weights, the loading,
and the memory. Adding a sixth app costs a client call, not a model integration.

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  launcher   │ │ autocomplete│ │  dictation  │ │ agent/CLI   │   thin clients
└──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
       └───────────────┴───────┬───────┴───────────────┘
                       127.0.0.1:8078  (never the network)
                    ┌───────────┴───────────┐
                    │   local-models daemon │  warm models, one copy
                    │  vision · completion* │
                    │     transcription*    │
                    └───────────┬───────────┘
                        ~/Models/ registry + weights
```

\* transcription is phase 2; its endpoint exists and returns an honest 501
until then. Completion serves (daemon-managed llama-server).

## Install

```bash
git clone https://github.com/tristan-mcinnis/local-models.git
cd local-models
make install          # copies cli/ + server/ to ~/.local/lib/local-models,
                      # links local-model + local-image onto PATH, and
                      # seeds ~/Models/models.json from the example if absent
make install-server   # launchd agent for the daemon (port 8078); the CLIs need it
```

Requirements: macOS on Apple Silicon, Python 3.11+, [mlx-vlm](https://github.com/Blaizzy/mlx-vlm)
for the vision backend, `huggingface_hub` for `pull`, `jsonschema` for
`local-image extract`. Apple Vision OCR is used when pyobjc is present,
falling back to Tesseract.

## Get a model

One command from "saw it on Hugging Face" to "callable by every app":

```bash
local-model pull mlx-community/Qwen3-VL-2B-Instruct-4bit --alias qwen3-vl --default
local-model pull bartowski/gemma-2-2b-it-GGUF --file gemma-2-2b-it-Q4_K_M.gguf
local-model add ~/somewhere/model-dir --backend mlx-vlm --capabilities vision,text
local-model list
local-model rm old-model --purge
```

`pull` downloads into `~/Models/`, infers the backend from the artifact
(MLX snapshot vs GGUF file), sizes it, and writes the registry entry. Weights
never enter git; the registry is the only integration surface.

## Use models

Every call below goes through the daemon; the CLIs never talk to a backend
server directly. `LOCAL_MODELS_DAEMON` (or `daemon.base_url` in the
registry) overrides the default `http://127.0.0.1:8078`.

```bash
local-model status                    # daemon health, warm models, per-backend state
local-model vision shot.png "What error does this dialog show?"
local-model ask "Summarize: ..."      # text through the same warm model
local-model benchmark                 # race every vision model on one fixture
local-model use gemma-completion      # warm a model (spawns llama-server for GGUF)
local-model unload [model]            # free the RAM

local-image ocr receipt.png           # Apple Vision / Tesseract, no model needed
local-image describe photo.png
local-image ui screenshot.png         # structured UI inventory
local-image extract receipt.png --schema schemas/receipt.schema.json
```

`local-image extract` is the "tiny specialist" pattern end to end: OCR evidence
plus the vision model plus JSON Schema validation with retry — repeatable
structured output from an image, entirely on device.

## The daemon

```bash
python3 server/serve.py --ensure-vision
curl -s localhost:8078/v1/models | jq        # every model + warm state
curl -s localhost:8078/health | jq           # per-backend availability
```

| Route | Request | Success body | State |
|---|---|---|---|
| `GET /health` | | `{status, service, backends: {name: {available, loaded_model, detail}}}` | serving |
| `GET /v1/models` | | `{default, idle_unload_seconds, models: [{id, backend, capabilities, path, warm, backend_available, endpoint, idle_seconds, idle_basis, in_flight}]}` | serving |
| `POST /v1/vision` | `{model?, prompt?, image_b64 \| image_path, mime?, max_tokens?, timeout?}` | `{model, text}` | serving (mlx-vlm) |
| `POST /v1/ask` | `{model?, prompt, max_tokens?, timeout?}` | `{model, text}` | serving |
| `POST /v1/complete` | `{model?, prompt, system?, max_tokens?, timeout?}` | `{model, text}` | serving (llama-gguf, ~57 ms warm first token) |
| `POST /v1/warm` | `{model?, wait?}` | `{model, warmed, text}`, or `{model, warmed: false, started: true}` when `wait` is `false` | serving |
| `POST /v1/unload` | `{model?}` | `{model, unloaded, message}` | serving |
| `POST /v1/transcribe` | | | phase 2 (501) |
| `GET /v1/status` | | `{app, ok, busy, warm, detail}` — the house command status document | serving |
| `GET /v1/choices/model` | | `{choices: [{id, title, detail}]}` — what a house command can be pointed at | serving |
| `GET /v1/openai/models` | | OpenAI list: `{object: "list", data: [{id, object: "model", owned_by}]}` (ids + aliases) | serving |
| `POST /v1/chat/completions` | OpenAI chat body; `model` = registry id or alias (omit for default) | the backend's OpenAI reply relayed byte-for-byte, streaming (`text/event-stream`) or JSON; header `X-Local-Models-Model` carries the resolved id | serving (mlx-vlm and llama-gguf) |

The two OpenAI-shaped routes are the passthrough for clients that already
speak OpenAI chat (Quick Launch's local provider, any OpenAI SDK): point them
at `http://127.0.0.1:8078/v1` and name a registry id as the model. The daemon
resolves the id, readies the owning backend (spawning llama-server for a GGUF
model; the mlx-vlm server must already be up), rewrites `model` to the weight
path, and relays the backend's stream. Unknown model answers 404 there, as
OpenAI clients expect; everything else keeps the error envelope below.

Every error is `{"error": "<message>"}` plus an optional `"hint"`:
400 bad request or unknown model, 404 no route, 501 planned but not served,
502 backend unreachable or failed. `model` accepts an id or an alias; omit it
for the registry default.

### Idle unloading

A model warmed once and then forgotten holds its resident memory until someone
remembers to unload it — in practice, for days, and a 2B GGUF is about 9 GB.
The daemon therefore stamps a clock every time a request puts a backend to work
(`/v1/vision`, `/v1/ask`, `/v1/complete`, `/v1/warm`, `/v1/chat/completions`)
and a sweeper thread unloads any backend that has gone unused for longer than
the threshold. Reading state is not use: `/health` and `/v1/models` never keep
a model warm, or the menu bar's own polling would.

A backend can be warm with no use recorded against it: a vision server the
daemon adopted rather than started, or any model still loaded from before the
daemon last restarted, since a restart resets every stamp. That is the case the
whole mechanism exists for, so it is swept too. Each tick asks every candidate
backend whether it is holding a model; the first tick that finds one warm and
unused starts its clock there, and it becomes claimable one threshold later —
not on sight, so a model warmed seconds before a restart keeps its full
threshold. An adopted server is unloaded through its own `/unload`; the server
process is never touched.

```json
{ "daemon": { "base_url": "http://127.0.0.1:8078", "idle_unload_seconds": 1800 } }
```

Default 30 minutes; `0` (or `LOCAL_MODELS_IDLE_UNLOAD_SECONDS=0`) switches it
off and a model stays warm until it is unloaded by hand, as before. The
override is `LOCAL_MODELS_IDLE_UNLOAD_SECONDS`, in seconds.

The unload can never land under a live request: the sweeper takes the same
claim a request holds, and only when nothing is in flight. The next request
after an idle unload readies the backend again and succeeds — it pays the
reload, it does not get an error — so the cost of a too-eager threshold is
latency, never a failure. `GET /v1/models` reports `idle_seconds` per model,
`idle_basis` (`"use"` for work the backend did, `"observed-warm"` for one found
warm with no use behind it, both null when it is cold and unused), and the
threshold in force; `local-model status` prints the age and the threshold.

Completion apps stream straight from the managed llama-server (the `endpoint`
field in `/v1/models`); the daemon is the control plane that spawns, warms,
and stops it. Thinking is disabled at spawn (`enable_thinking: false`) so
completion models return raw continuation tokens, never reasoning.

Backends are plugins: subclass `Backend`, declare capabilities, add one line to
the registry. TTS, embeddings, and reranking are the obvious next files. See
[docs/layer-contract.md](docs/layer-contract.md).

A minimal Swift client for native apps ships in
[client/swift/LocalModelClient](client/swift/LocalModelClient).

## House commands

The daemon publishes what it lets other apps do, so Quick Launch can warm or
unload a model from its launcher without knowing this daemon by name. At
startup it writes

    ~/Library/Application Support/House/commands/models.json

per the house command contract (`design-system/docs/app-commands.md`):
transport `http`, endpoint the address it is actually serving on, and two
commands — **Warm Model** and **Unload Model**, each taking a model id.
Nothing destructive is published. A manifest that cannot be written is logged
and ignored; the daemon serves either way.

The contract fixes the file and the status document but leaves the `http`
transport's own details open, so this daemon settles them the way its routes
already worked:

- A command is `POST {endpoint}{verb}`; `status` and `choicesFrom` are `GET`.
- A command's one argument is posted as `{"argument": "<value>"}`.
  `/v1/warm` and `/v1/unload` accept it as a synonym for `model`, so the
  existing wire format is unchanged.
- Nothing may block the caller for more than a second, and warming a cold
  model takes tens of seconds. So `POST /v1/warm` takes `{"wait": false}`:
  it starts the load, returns `{"warmed": false, "started": true}` at once,
  and the caller polls `/v1/status`. The model reads as busy from the instant
  that reply is sent, not from when the load ends, so the idle sweeper can
  never unload a model mid-load. Omitting `wait` keeps the blocking reply
  every existing client gets.
- The registry changes while the daemon runs, so a choice list frozen into a
  file written at launch would go stale. The manifest names a route to read
  instead, in one field the contract does not define, `choicesFrom`.

`GET /v1/status` is derived from the same per-model state `GET /v1/models`
reports — one source of truth — and, like that route, reading it is not use, so
polling it never keeps a model warm.

## Menu bar

A menu-bar app shows the fleet at a glance on the house design system
([Slate](../design-system/DESIGN.md), the shared "Menu bar panel" component): a
300 px glass panel with the daemon's state and switch in the header, one 36 px
row per registered model with its capabilities and whether it is warm, Return
to load and ⌘Return to unload, then Refresh (⌘R) and Open registry. It talks
only to the daemon and to the daemon's launchd job.

```bash
make menubar           # builds dist/Local Models.app
make install-menubar   # builds, copies to /Applications, launches
```

`LocalModelsBar --render-proof <dir>` writes the panel and settings surfaces to
PNGs offscreen, in both appearances, without showing a window.

## Design rules

- **Local socket only.** The daemon binds 127.0.0.1. Nothing listens on the network.
- **Warm beats fast-loading.** RAM spent on one shared warm copy beats every app cold-starting its own.
- **The registry is the contract.** Apps ask for capabilities and aliases, never file paths.
- **Honest 501s.** A capability that is planned but not served refuses loudly instead of pretending.
- **Weights out of git.** `~/Models/` holds the artifacts; this repo holds everything that manages them.

## License

MIT.
