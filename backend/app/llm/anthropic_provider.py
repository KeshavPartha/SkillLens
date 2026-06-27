"""Anthropic provider — the only place the Anthropic SDK is imported."""

from __future__ import annotations

import json

from anthropic import AsyncAnthropic

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, Provider
from app.llm.cost import compute_cost


class AnthropicProvider(BaseLLMProvider):
    """Async wrapper over the Anthropic messages API."""

    provider = Provider.ANTHROPIC

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        **kwargs: object,
    ) -> LLMResponse:
        system_parts = [m.content for m in messages if m.role == "system"]
        chat_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        create_kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
            **kwargs,
        }
        if system_parts:
            create_kwargs["system"] = "\n\n".join(system_parts)

        resp = await self._client.messages.create(**create_kwargs)
        content = self._extract_content(resp)
        usage = resp.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        return LLMResponse(
            content=content,
            model=model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost(model, input_tokens, output_tokens),
        )

    @staticmethod
    def _extract_content(resp: object) -> str:
        """Prefer a forced tool_use block; fall back to plain text."""

        for block in resp.content:
            if block.type == "tool_use":
                return json.dumps(block.input)
        for block in resp.content:
            if block.type == "text":
                return block.text
        return ""
