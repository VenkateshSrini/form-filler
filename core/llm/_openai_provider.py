from __future__ import annotations

import os

from openai import AzureOpenAI, OpenAI

from core.llm._base import CompletionRequest, LLMProvider


class OpenAIProvider(LLMProvider):
    """
    Standard OpenAI API.
    Also works with any OpenAI-compatible endpoint (Ollama, LM Studio, etc.)
    by setting LLM_BASE_URL.

    Required env vars:
        LLM_API_KEY   — OpenAI API key
        LLM_MODEL     — e.g. "gpt-4o-mini"
    Optional:
        LLM_BASE_URL  — override base URL (default: https://api.openai.com/v1)
    """

    def __init__(self) -> None:
        self._model: str = os.environ["LLM_MODEL"]
        self._client: OpenAI = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.getenv("LLM_BASE_URL") or None,  # None → SDK default
        )

    def complete(self, request: CompletionRequest) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=request.max_tokens,
        )
        return response.choices[0].message.content or "{}"


class AzureOpenAIProvider(LLMProvider):
    """
    Azure-hosted OpenAI.

    Required env vars:
        LLM_API_KEY                  — Azure OpenAI key
        LLM_MODEL                    — Azure deployment name
        AZURE_OPENAI_ENDPOINT        — e.g. https://<resource>.openai.azure.com
    Optional:
        AZURE_OPENAI_API_VERSION     — default: 2024-02-01
    """

    def __init__(self) -> None:
        self._model: str = os.environ["LLM_MODEL"]
        self._client: AzureOpenAI = AzureOpenAI(
            api_key=os.environ["LLM_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )

    def complete(self, request: CompletionRequest) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=request.max_tokens,
        )
        return response.choices[0].message.content or "{}"
