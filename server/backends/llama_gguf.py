"""Completion backend for GGUF models via llama.cpp — planned, not yet served.

Phase 2. The shape is decided: hold one llama.cpp context warm per registered
GGUF model, serve /v1/complete with prefix + suffix context, target
keystroke-latency budgets. Until then this backend registers the capability
and refuses requests with a clear message instead of pretending.
"""

from __future__ import annotations

from typing import Any

from . import Backend, NotSupported


class LlamaGgufBackend(Backend):
    name = "llama-gguf"
    capabilities = ("completion",)

    def status(self) -> dict[str, Any]:
        return {
            "available": False,
            "loaded_model": None,
            "detail": "planned: llama.cpp completion serving (phase 2)",
        }

    def infer(self, model: dict, payload: dict) -> dict:
        raise NotSupported(
            "completion serving is not implemented yet; "
            "apps using GGUF models load them in-process for now"
        )
