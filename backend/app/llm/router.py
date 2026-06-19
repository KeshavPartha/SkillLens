"""The mandatory LLM entry point.

All LLM calls go through :meth:`LLMRouter.complete`, which maps a :class:`ModelTask` to a
provider + model, dispatches to the right provider, and meters cost against the per-run
ceiling. Callers never pass model names or touch a vendor SDK.

For the ingestion pipeline only ``CLASSIFICATION`` (Groq/Llama) is needed; the Anthropic
``EXTRACTION`` / ``ANALYSIS`` tasks are intentionally left as a clear extension point.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.llm.base import (
    BaseLLMProvider,
    LLMMessage,
    LLMResponse,
    ModelTask,
    Provider,
)
from app.llm.cost import CostTracker
from app.llm.groq_provider import GroqProvider


class LLMRouter:
    """Routes tasks to providers and enforces per-run cost tracking."""

    def __init__(self, settings: Settings, cost_tracker: CostTracker) -> None:
        self._settings = settings
        self._cost = cost_tracker
        self._providers: dict[Provider, BaseLLMProvider] = {}

        # Task -> (provider, model name) routing table.
        llm = settings.llm
        self._routes: dict[ModelTask, tuple[Provider, str]] = {
            ModelTask.CLASSIFICATION: (Provider.GROQ, llm.groq_model),
            ModelTask.EXTRACTION: (Provider.ANTHROPIC, llm.haiku_model),
            ModelTask.ANALYSIS: (Provider.ANTHROPIC, llm.sonnet_model),
        }

    def _get_provider(self, provider: Provider) -> BaseLLMProvider:
        if provider not in self._providers:
            llm = self._settings.llm
            if provider is Provider.GROQ:
                if not llm.groq_api_key:
                    raise RuntimeError("GROQ_API_KEY is not configured")
                self._providers[provider] = GroqProvider(
                    api_key=llm.groq_api_key,
                    timeout=llm.request_timeout_seconds,
                )
            else:
                raise NotImplementedError(
                    f"provider {provider.value!r} is not wired up yet "
                    "(only Groq/CLASSIFICATION is implemented)"
                )
        return self._providers[provider]

    async def complete(
        self,
        task: ModelTask,
        messages: list[LLMMessage],
        *,
        run_id: str = "default",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        **kwargs: object,
    ) -> LLMResponse:
        """Run a completion for ``task``, metering cost against ``run_id``."""

        provider_kind, model = self._routes[task]
        provider = self._get_provider(provider_kind)
        response = await provider.complete(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        self._cost.add(run_id, response.cost_usd)
        return response

    def get_cost(self, run_id: str) -> float:
        return self._cost.get_cost(run_id)


@lru_cache
def get_router() -> LLMRouter:
    """Return the process-wide router singleton."""

    settings = get_settings()
    return LLMRouter(settings, CostTracker(settings.llm.max_run_cost_usd))
