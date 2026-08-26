"""Business logic never calls a model provider's HTTP API directly — it calls
a ModelGateway. Swapping Ollama for another provider means writing one new
class here, not touching app/ai/extraction.py or anything upstream of it."""

from __future__ import annotations

from typing import Protocol


class ModelGateway(Protocol):
    model: str

    def available(self) -> bool:
        """Cheap health check; extraction falls back to all-null fields when False."""
        ...

    def complete_json(self, system: str, user: str) -> str:
        """One text-in, text-out call. The caller parses/validates the result — the
        gateway's only job is talking to the model."""
        ...

    def complete_vision(self, system: str, user: str, images: list[bytes]) -> str:
        """Same, with page images attached. Used only for the OCR fallback."""
        ...
