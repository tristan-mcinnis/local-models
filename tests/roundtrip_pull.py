#!/usr/bin/env python3
"""Real network roundtrip: pull a tiny HF model into a temp home, then rm --purge.

Uses hf-internal-testing/tiny-random-gpt2 (a few MB). Proves download,
backend/capability override, registry write, and purge — without touching
the real ~/Models.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli" / "local-model"
TINY = "hf-internal-testing/tiny-random-gpt2"


def run(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "LOCAL_MODELS_HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=300
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        pulled = run(
            home, "pull", TINY,
            "--name", "tiny-test", "--backend", "mlx-lm", "--capabilities", "text",
            "--role", "roundtrip test model",
        )
        assert pulled.returncode == 0, f"pull failed:\n{pulled.stdout}\n{pulled.stderr}"

        registry = json.loads((home / "models.json").read_text())
        entry = registry["models"]["tiny-test"]
        assert entry["backend"] == "mlx-lm", entry
        assert entry["capabilities"] == ["text"], entry
        assert entry["size_bytes"] > 0, entry
        model_dir = Path(entry["path"])
        assert model_dir.is_dir() and any(model_dir.iterdir()), model_dir

        removed = run(home, "rm", "tiny-test", "--purge")
        assert removed.returncode == 0, removed.stderr
        registry = json.loads((home / "models.json").read_text())
        assert "tiny-test" not in registry["models"]
        assert not model_dir.exists(), f"purge left {model_dir}"

        print("PULL_ROUNDTRIP_OK")


if __name__ == "__main__":
    main()
