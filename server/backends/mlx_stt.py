"""Transcription backend for MLX speech models — planned, not yet served.

Phase 2. The shape is decided: hold the STT model warm, accept PCM chunks or
a file path, return text with timestamps. Until then this backend registers
the capability and refuses requests with a clear message.
"""

from __future__ import annotations

from typing import Any

from . import Backend, NotSupported


class MlxSttBackend(Backend):
    name = "mlx-stt"
    capabilities = ("transcription",)

    def status(self) -> dict[str, Any]:
        return {
            "available": False,
            "loaded_model": None,
            "detail": "planned: MLX speech-to-text serving (phase 2)",
        }

    def infer(self, model: dict, payload: dict) -> dict:
        raise NotSupported(
            "transcription serving is not implemented yet; "
            "dictation apps keep their in-process pipeline for now"
        )
