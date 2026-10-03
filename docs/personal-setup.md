# Personal setup notes

These notes describe how Local Models runs on the author's own Mac, next to
the other House apps. None of it is needed to use Local Models. It is kept
here so the setup can be rebuilt.

## The vision server has its own launchd agent

The mlx-vlm server on 127.0.0.1:8080 is started by a separate launchd agent,
`com.tristan.mlx-vlm-server`, not by the daemon. The live registry names it,
so the daemon adopts that server and never spawns a second one:

```json
{
  "server": {
    "base_url": "http://127.0.0.1:8080",
    "api": "mlx-vlm",
    "launch_agent": "com.tristan.mlx-vlm-server"
  }
}
```

See "Server ownership" in [layer-contract.md](layer-contract.md). A fresh
install leaves `launch_agent` out and lets the daemon spawn the server.

## Who calls the daemon on this Mac

- Quick Launch: its local AI provider points at `http://127.0.0.1:8078/v1`
  (the OpenAI passthrough), and it reads the House command manifest to warm
  and unload models from the launcher.
- Screen context collector (memory-screenctx): `/v1/vision` for enrichment.
- Cotype: streams completions from the daemon-managed llama-server.
- RTI: `/v1/vision`.
- Chief of Staff: `/v1/ask` as a fallback.
- launchd jobs and agent skills call the `local-model` and `local-image` CLIs.
  This is why `make install` copies the runtime to `~/.local/lib/local-models`:
  launchd jobs may not read `~/Documents`.

No House app imports `LocalModelClient` yet. Each speaks the wire format
directly.

Local Dictation is not a client by decision. It keeps its models in process
for latency and shares only the `~/Models/` weight store. The House vision
note records this as a named exception to the one serving layer.

## Local TTS

[Local TTS](https://github.com/tristan-mcinnis/local-tts) runs its own
launchd service on 127.0.0.1:8081 and is registered in `~/Models/models.json`
as `pocket-tts` with backend `pocket-tts`. The daemon does not serve that
backend, so the row reads `backend_available: false`. The menu bar's VOICE
row talks to 8081 directly.

## House contracts that live in the private design-system repo

- The House command contract (`design-system/docs/app-commands.md`) defines
  the manifest file and the status document that `server/commands.py` writes.
- The Slate visual rule (`design-system/DESIGN.md`) and `tokens.json` generate
  `HouseDesign.swift`. Refresh it from design-system; do not edit it by hand.
- `.claude/hooks/` run `design-system/bin/design-lint` when this repo sits in
  the House checkout. Outside it they exit quietly.

## Live gates

- `sh tests/compat.sh` checks the deployed CLIs against the live `~/Models`
  registry (read-only). It expects `qwen3-vl` in the registry.
- `python3 tests/roundtrip_pull.py` does a real Hugging Face pull into a temp
  home.

Both need a `python3` with huggingface_hub and PyObjC first on PATH (the
interpreter in the daemon plist has both).
