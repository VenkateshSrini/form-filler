from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class CompletionRequest:
    """Provider-agnostic completion request."""
    system: str
    user: str
    max_tokens: int = 4096


class LLMProvider(ABC):
    """
    Abstract base for all LLM providers.

    Implementations live in _openai_provider.py and _anthropic_provider.py.
    Nothing outside core/llm/ should import from this module directly;
    callers use enrich_fields_with_llm() from __init__.py.
    """

    @abstractmethod
    def complete(self, request: CompletionRequest) -> str:
        """
        Send a completion and return the raw response text.
        Must raise on unrecoverable errors — caller handles fallback.
        The returned string must be parseable as JSON.
        """
