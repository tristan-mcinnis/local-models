# local-models: agent contract

Canonical for every agent runtime. `AGENTS.md` is a symlink to this file.

## Goal

One local daemon for a fleet of small models. Apps make a localhost call;
the daemon owns the weights, the loading, and the memory. Thin clients only.

## Layout

- `server/serve.py`: the daemon (127.0.0.1:8078). `server/common.py`: shared
  registry/HTTP plumbing everything imports. `server/backends/`: one plugin
  per runtime (`mlx-vlm` vision, `llama-gguf` completion, `mlx-audio-stt`
  planned).
- `cli/local-model`, `cli/local-image`: on PATH via `make install`. They call
  the daemon; they never call a backend port.
- `client/swift/LocalModelClient`: Swift client. `menubar/LocalModelsBar`:
  menu-bar app. `registry/models.example.json`: registry shape.
- `~/Models/models.json` (outside git) is the live registry; `~/Models/` holds
  weights.

## Build, test, run

```bash
make test                          # unit tests + daemon smoke + publish scrub
sh tests/compat.sh                 # live gate: deployed CLIs against ~/Models
python3 tests/roundtrip_pull.py    # network: real HF pull into a temp home
cd client/swift/LocalModelClient && swift build
cd menubar/LocalModelsBar && swift build
python3 server/serve.py --ensure-vision   # run the daemon by hand
make install-server / make restart / make logs
```

Run `make test` after any Python change. Run both Swift builds after any
Swift change. Restart the daemon (`make restart`) after a server change and
check `local-model status` before calling it done.

## Rules

- One mechanism each: registry reading, model resolution, daemon URL, and
  HTTP live in `server/common.py`. Do not re-implement them in a CLI or test.
- Wire format is a contract. Success bodies are documented in the README route
  table; every error is `{"error", "hint"?}` with 400/404/501/502. Changes
  must be additive; clients (Quick Launch, screenctx, cotype, local-dictation)
  depend on it.
- Backends report `{"available", "loaded_model", "detail"}` and unload to
  `{"message"}`. Raise `BackendError` (502) or `NotSupported` (501).
- Planned capabilities refuse with 501. Never fake a result.
- The daemon binds 127.0.0.1 only. Loopback HTTP bypasses system proxies.
- Weights, `~/Models/models.json`, `.env`, keys, and `/Users/<name>` paths
  never enter git. `tests/scrub.sh` gates every publish; `.scrub-private`
  holds the private patterns and stays untracked.
- The repo is public. Product name: local-models.
