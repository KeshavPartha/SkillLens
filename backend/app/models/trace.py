"""Agent trace models for SSE streaming.

As the agent pipeline runs it emits TraceSteps. The AgentTrace accumulates them
(and their cost/token totals) and serializes individual steps for Server-Sent
Events so the frontend can render a live activity feed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class StepType(str, Enum):
    """The kind of event a trace step represents."""

    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"
    RESUME_PARSING = "resume_parsing"
    PROFILE_EXTRACTED = "profile_extracted"
    MARKET_QUERY = "market_query"
    MARKET_RESULTS = "market_results"
    SKILL_AGGREGATION = "skill_aggregation"
    GAP_ANALYSIS_START = "gap_analysis_start"
    GAP_IDENTIFIED = "gap_identified"
    GAP_ANALYSIS_DONE = "gap_analysis_done"
    PLAN_DRAFT = "plan_draft"
    CRITIQUE_START = "critique_start"
    CRITIQUE_CHALLENGE = "critique_challenge"
    PLAN_REVISION = "plan_revision"
    PLAN_FINAL = "plan_final"
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    THINKING = "thinking"
    INFO = "info"


class TraceStep(BaseModel):
    """A single event emitted by an agent during a run."""

    step_id: str = Field(default_factory=lambda: str(uuid4()))
    step_type: StepType
    agent_name: str  # which agent emitted this
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = Field(min_length=1, max_length=500)  # UI headline
    payload: dict[str, Any] | None = None  # structured detail for expandable view
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    model_used: str | None = None
    duration_ms: int | None = None

    @property
    def is_llm_step(self) -> bool:
        """Whether this step bookends an LLM call."""

        return self.step_type in (StepType.LLM_CALL_START, StepType.LLM_CALL_END)

    @property
    def is_error(self) -> bool:
        """Whether this step represents an agent error."""

        return self.step_type is StepType.AGENT_ERROR


class AgentTrace:
    """Mutable container accumulating a run's steps and running totals.

    This is intentionally a plain class rather than a BaseModel: it is a live,
    mutating accumulator used during a run, not a serialized payload shape.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id: str = run_id
        self.steps: list[TraceStep] = []
        self.started_at: datetime = datetime.now(timezone.utc)
        self.completed_at: datetime | None = None
        self.is_complete: bool = False
        self.had_error: bool = False
        self.total_cost_usd: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        # Optional sync listener notified after each step is appended (e.g. the
        # SSE endpoint pushes the step onto an asyncio.Queue). Kept sync so
        # append_step stays sync; the listener must not block.
        self.listener: Callable[[TraceStep], None] | None = None

    def append_step(self, step: TraceStep) -> TraceStep:
        """Append a step and roll its cost/token figures into the totals."""

        self.steps.append(step)
        if step.cost_usd is not None:
            self.total_cost_usd += step.cost_usd
        if step.input_tokens is not None:
            self.total_input_tokens += step.input_tokens
        if step.output_tokens is not None:
            self.total_output_tokens += step.output_tokens
        if step.is_error:
            self.had_error = True
        if self.listener is not None:
            self.listener(step)
        return step

    def to_sse_payload(self, step: TraceStep) -> dict[str, Any]:
        """Build the dict emitted over SSE for a single step."""

        return {
            "run_id": self.run_id,
            "step": step.model_dump(mode="json"),
            "running_cost_usd": self.total_cost_usd,
        }
