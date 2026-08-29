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

\* completion and transcription backends are phase 2; the endpoints exist and
return honest 501s until then.

## Install

```bash
git clone https://github.com/tristan-mcinnis/local-models.git
cd local-models
make install          # symlinks local-model + local-image onto PATH,
                      # seeds ~/Models/models.json from the example if absent
make install-server   # optional: launchd agent for the daemon (port 8078)
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

```bash
local-model status                    # what's running, what's warm
local-model vision shot.png "What error does this dialog show?"
local-model ask "Summarize: ..."      # text through the same warm model
local-model benchmark                 # race every vision model on one fixture
local-model unload                    # free the RAM

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

| Endpoint | State |
|---|---|
| `POST /v1/vision` | serving (mlx-vlm backend) |
| `POST /v1/ask` | serving |
| `POST /v1/complete` | serving (llama-gguf backend: daemon-managed llama-server, ~57 ms warm first token) |
| `POST /v1/warm`, `/v1/unload` | serving (per-model lifecycle) |
| `GET /v1/models`, `/health` | serving |
| `POST /v1/transcribe` | phase 2 (MLX speech models) |

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

A tiny menu-bar app shows the fleet at a glance: every registered model, a
filled dot on the warm one, click to load, one item to unload and free the
RAM. It talks only to the daemon.

```bash
make install-menubar   # builds dist/Local Models.app, copies to /Applications, launches
```

## Design rules

- **Local socket only.** The daemon binds 127.0.0.1. Nothing listens on the network.
- **Warm beats fast-loading.** RAM spent on one shared warm copy beats every app cold-starting its own.
- **The registry is the contract.** Apps ask for capabilities and aliases, never file paths.
- **Honest 501s.** A capability that is planned but not served refuses loudly instead of pretending.
- **Weights out of git.** `~/Models/` holds the artifacts; this repo holds everything that manages them.

## License

MIT.
