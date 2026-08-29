"""Backend plugin contract.

A backend serves one or more capabilities (vision, completion, transcription,
tts, embeddings, ...) for models whose registry entry names it via "backend".

Contract: subclass Backend, set `name` and `capabilities`, implement `infer`.
Register by adding the class to BACKENDS. The daemon routes a request to the
backend named by the resolved model's registry entry; nothing else changes.
"""

from __future__ import annotations

from typing import Any


class BackendError(RuntimeError):
    """Raised when a backend cannot serve a request."""


class NotSupported(BackendError):
    """Raised when a capability is registered but not yet implemented."""


class Backend:
    name: str = "abstract"
    capabilities: tuple[str, ...] = ()

    def __init__(self, registry: dict):
        self.registry = registry

    def status(self) -> dict[str, Any]:
        """Return {"available": bool, "loaded_model": str|None, "detail": str}."""
        return {"available": False, "loaded_model": None, "detail": "not implemented"}

    def infer(self, model: dict, payload: dict) -> dict:
        """Serve one request for a model this backend owns. Returns a JSON-able dict."""
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
    from . import llama_gguf, mlx_stt, mlx_vlm

    return {
        mlx_vlm.MlxVlmBackend.name: mlx_vlm.MlxVlmBackend,
        llama_gguf.LlamaGgufBackend.name: llama_gguf.LlamaGgufBackend,
        mlx_stt.MlxSttBackend.name: mlx_stt.MlxSttBackend,
    }


def get_backend(name: str, registry: dict) -> Backend:
    backends = all_backends()
    cls = backends.get(name)
    if cls is None:
        raise BackendError(f"unknown backend '{name}'. Known: {', '.join(sorted(backends))}")
    return cls(registry)
