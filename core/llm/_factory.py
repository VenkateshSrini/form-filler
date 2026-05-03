from __future__ import annotations

import os

from core.llm._anthropic_provider import AnthropicBedrockProvider, AnthropicProvider
from core.llm._base import LLMProvider
from core.llm._openai_provider import AzureOpenAIProvider, OpenAIProvider

# Registry: LLM_PROVIDER value → provider class
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "azure_openai": AzureOpenAIProvider,
    "anthropic": AnthropicProvider,
    "aws_bedrock": AnthropicBedrockProvider,
}


def get_provider() -> LLMProvider | None:
    """
    Return the configured LLM provider, or None for heuristic-only mode.

    Returns None when:
    - LLM_PROVIDER env var is absent or empty, OR
    - LLM_API_KEY is absent/empty AND provider is not aws_bedrock
      (Bedrock uses the AWS credential chain — no API key needed)

    Raises ValueError for an unrecognised LLM_PROVIDER value so
    misconfiguration is caught early at form-load time, not silently ignored.
    """
    provider_name: str = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider_name:
        return None

    # Bedrock authenticates via AWS credential chain — LLM_API_KEY is not required.
    needs_api_key: bool = provider_name != "aws_bedrock"
    if needs_api_key and not os.getenv("LLM_API_KEY", "").strip():
        return None

    cls = _PROVIDERS.get(provider_name)
    if cls is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. "
            f"Supported values: {sorted(_PROVIDERS)}"
        )
    return cls()
