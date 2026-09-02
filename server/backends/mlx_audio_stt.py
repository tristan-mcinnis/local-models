"""Transcription backend for MLX speech models: planned, not yet served.

Phase 2. The shape is decided: hold the STT model warm, accept PCM chunks or
a file path, return text with timestamps. Until then this backend registers
the capability under the name the live registry already uses
("mlx-audio-stt") and refuses requests with a clear message.
"""

from __future__ import annotations

from typing import Any

from . import Backend, NotSupported, status_dict


class MlxAudioSttBackend(Backend):
    name = "mlx-audio-stt"
    capabilities = ("transcription",)

    def status(self) -> dict[str, Any]:
        return status_dict(False, None, "planned: MLX speech-to-text serving (phase 2)")

    def infer(self, model: dict, payload: dict) -> dict:
        raise NotSupported(
            "transcription serving is not implemented yet; "
            "dictation apps keep their in-process pipeline for now"
        )
