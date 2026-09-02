"""Backend plugin contract.

A backend serves one or more capabilities (vision, completion, transcription,
tts, embeddings, ...) for models whose registry entry names it via "backend".

Contract: subclass Backend, set `name` and `capabilities`, implement `infer`
and `status`. Register the class in `all_backends()`. The daemon routes a
request to the backend named by the resolved model's registry entry.

Every backend reports the same status shape:
    {"available": bool, "loaded_model": str|None, "detail": str}
and every unload returns {"message": str}. Errors are BackendError (the
daemon answers 502) or NotSupported (the daemon answers 501).
"""

from __future__ import annotations

from typing import Any


class BackendError(RuntimeError):
    """Raised when a backend cannot serve a request."""


class NotSupported(BackendError):
    """Raised when a capability is registered but not yet implemented."""


def status_dict(available: bool, loaded_model: str | None, detail: str) -> dict[str, Any]:
    return {"available": available, "loaded_model": loaded_model, "detail": detail}


class Backend:
    name: str = "abstract"
    capabilities: tuple[str, ...] = ()
    #: Data-plane URL apps may stream from directly (None = daemon only).
    base_url: str | None = None

    def __init__(self, registry: dict):
        self.registry = registry

    def status(self) -> dict[str, Any]:
        return status_dict(False, None, "not implemented")

    def infer(self, model: dict, payload: dict) -> dict:
        """Serve one request for a model this backend owns. Returns {"text": str, "raw": ...}."""
        raise NotSupported(f"backend '{self.name}' cannot serve this request yet")

    def warm(self, model: dict, payload: dict) -> dict:
        """Load the model and leave it warm. Default: run one tiny inference."""
        return self.infer(
            model,
            {**payload, "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 8},
        )

    def unload(self) -> dict:
        raise NotSupported(f"backend '{self.name}' has no unload")


def all_backends() -> dict[str, type[Backend]]:
    from . import llama_gguf, mlx_audio_stt, mlx_vlm

    return {
        cls.name: cls
        for cls in (mlx_vlm.MlxVlmBackend, llama_gguf.LlamaGgufBackend, mlx_audio_stt.MlxAudioSttBackend)
    }


def get_backend(name: str, registry: dict) -> Backend:
    backends = all_backends()
    cls = backends.get(name)
    if cls is None:
        raise BackendError(f"unknown backend '{name}'. Known: {', '.join(sorted(backends))}")
    return cls(registry)
