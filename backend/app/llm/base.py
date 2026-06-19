"""Core LLM router types.

These are provider-agnostic. Callers in ``agents/``, ``api/``, and ``tools/`` must go
through :class:`~app.llm.router.LLMRouter` and never import a provider SDK directly — that
is how per-run cost tracking and model routing are enforced.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Provider(str, Enum):
    """Backing LLM provider."""

    ANTHROPIC = "anthropic"
    GROQ = "groq"


class ModelTask(str, Enum):
    """Routing key — selects model + provider, not the model name directly.

    Per the project model-assignment table:
      * ``EXTRACTION``    -> Claude Haiku 4.5   (resume / JD parsing)
      * ``ANALYSIS``      -> Claude Sonnet 4.6  (gap analysis, planning)
      * ``CLASSIFICATION``-> Llama 3.3 via Groq (skill / role classification)
    """

    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    CLASSIFICATION = "classification"


class LLMMessage(BaseModel):
    """A single chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    """Normalized completion result with token + cost accounting."""

    content: str
    model: str
    provider: Provider
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BaseLLMProvider(ABC):
    """Provider interface. Implementations wrap exactly one vendor SDK."""

    provider: Provider

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        **kwargs: object,
    ) -> LLMResponse:
        """Run a chat completion and return a normalized response."""
        raise NotImplementedError
