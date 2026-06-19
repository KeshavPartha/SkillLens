"""Groq provider — the only place the Groq SDK is imported."""

from __future__ import annotations

from groq import AsyncGroq

from app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, Provider
from app.llm.cost import compute_cost


class GroqProvider(BaseLLMProvider):
    """Async wrapper over the Groq chat completions API."""

    provider = Provider.GROQ

    def __init__(self, api_key: str, timeout: int = 60) -> None:
        self._client = AsyncGroq(api_key=api_key, timeout=timeout)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        **kwargs: object,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        return LLMResponse(
            content=content,
            model=model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost(model, input_tokens, output_tokens),
        )
