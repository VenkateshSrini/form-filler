from __future__ import annotations

import os
import re

import anthropic

from core.llm._base import CompletionRequest, LLMProvider

# Anthropic has no native json_object response mode — we enforce JSON via the
# system prompt suffix and strip any markdown fences the model may add anyway.
_JSON_ENFORCEMENT_SUFFIX: str = (
    "\n\nCRITICAL: Your entire response must be a single valid JSON object. "
    "No markdown code fences, no preamble, no explanation. Start with { and end with }."
)

_JSON_FENCE_RE: re.Pattern[str] = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Strip markdown code fences if the model added them despite instructions."""
    match = _JSON_FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


class AnthropicProvider(LLMProvider):
    """
    Anthropic API (claude.ai).

    Required env vars:
        LLM_API_KEY  — Anthropic API key (sk-ant-...)
        LLM_MODEL    — e.g. "claude-3-5-haiku-20241022"
    """

    def __init__(self) -> None:
        self._model: str = os.environ["LLM_MODEL"]
        self._client: anthropic.Anthropic = anthropic.Anthropic(
            api_key=os.environ["LLM_API_KEY"],
        )

    def complete(self, request: CompletionRequest) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=request.max_tokens,
            system=request.system + _JSON_ENFORCEMENT_SUFFIX,
            messages=[{"role": "user", "content": request.user}],
            temperature=0,
        )
        raw: str = response.content[0].text if response.content else "{}"
        return _extract_json(raw)


class AnthropicBedrockProvider(LLMProvider):
    """
    Anthropic Claude via AWS Bedrock.

    Required env vars:
        LLM_MODEL    — Bedrock model ID, e.g. "anthropic.claude-3-5-haiku-20241022-v1:0"
        AWS_REGION   — AWS region (default: us-east-1)

    Authentication (standard AWS credential chain — pick one):
        Option A — Explicit keys:
            AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN for STS)
        Option B — IAM role / EC2 instance profile / ECS task role:
            No env vars needed; boto3 discovers credentials automatically.
        Option C — AWS profile:
            AWS_PROFILE env var or ~/.aws/credentials

    Note: LLM_API_KEY is NOT required for Bedrock — authentication uses AWS credentials.
    """

    def __init__(self) -> None:
        self._model: str = os.environ["LLM_MODEL"]
        kwargs: dict[str, str] = {
            "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        }
        # Only pass explicit keys when present — otherwise boto3 uses its credential chain.
        if os.getenv("AWS_ACCESS_KEY_ID"):
            kwargs["aws_access_key"] = os.environ["AWS_ACCESS_KEY_ID"]
            kwargs["aws_secret_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
            if os.getenv("AWS_SESSION_TOKEN"):
                kwargs["aws_session_token"] = os.environ["AWS_SESSION_TOKEN"]
        self._client: anthropic.AnthropicBedrock = anthropic.AnthropicBedrock(**kwargs)

    def complete(self, request: CompletionRequest) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=request.max_tokens,
            system=request.system + _JSON_ENFORCEMENT_SUFFIX,
            messages=[{"role": "user", "content": request.user}],
        )
        raw: str = response.content[0].text if response.content else "{}"
        return _extract_json(raw)
