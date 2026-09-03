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
make install          # symlinks local-model + local-image onto PATH,
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
| `GET /v1/models` | | `{default, models: [{id, backend, capabilities, path, warm, backend_available, endpoint}]}` | serving |
| `POST /v1/vision` | `{model?, prompt?, image_b64 \| image_path, mime?, max_tokens?, timeout?}` | `{model, text}` | serving (mlx-vlm) |
| `POST /v1/ask` | `{model?, prompt, max_tokens?, timeout?}` | `{model, text}` | serving |
| `POST /v1/complete` | `{model?, prompt, system?, max_tokens?, timeout?}` | `{model, text}` | serving (llama-gguf, ~57 ms warm first token) |
| `POST /v1/warm` | `{model?}` | `{model, warmed, text}` | serving |
| `POST /v1/unload` | `{model?}` | `{model, unloaded, message}` | serving |
| `POST /v1/transcribe` | | | phase 2 (501) |
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

Completion apps stream straight from the managed llama-server (the `endpoint`
field in `/v1/models`); the daemon is the control plane that spawns, warms,
and stops it. Thinking is disabled at spawn (`enable_thinking: false`) so
completion models return raw continuation tokens, never reasoning.

Backends are plugins: subclass `Backend`, declare capabilities, add one line to
the registry. TTS, embeddings, and reranking are the obvious next files. See
[docs/layer-contract.md](docs/layer-contract.md).

A minimal Swift client for native apps ships in
[client/swift/LocalModelClient](client/swift/LocalModelClient).

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
