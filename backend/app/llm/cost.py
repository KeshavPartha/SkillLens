"""Per-run cost tracking and the hard cost ceiling.

Cost is computed from published per-token rates so the figure is meaningful even on
Groq's free tier (where the real charge is $0). Every call through the router is metered;
a run that would exceed ``max_run_cost_usd`` raises :class:`RunCostExceeded`.
"""

from __future__ import annotations

# (input_per_1m_tokens, output_per_1m_tokens), in USD.
PRICING: dict[str, tuple[float, float]] = {
    # Groq — published list rates (free tier bills $0, but we meter against these).
    "llama-3.3-70b-versatile": (0.59, 0.79),
    # Anthropic — for when EXTRACTION / ANALYSIS tasks are wired up.
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a single completion. Unknown models cost $0 (but are still metered)."""

    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


class RunCostExceeded(Exception):
    """Raised when a single run's cumulative LLM cost exceeds the configured ceiling."""

    def __init__(self, run_id: str, attempted: float, limit: float) -> None:
        self.run_id = run_id
        self.attempted = attempted
        self.limit = limit
        super().__init__(
            f"run '{run_id}' cost ${attempted:.4f} would exceed limit ${limit:.2f}"
        )


class CostTracker:
    """Accumulates per-``run_id`` cost and enforces the ceiling."""

    def __init__(self, max_run_cost_usd: float) -> None:
        self._max = max_run_cost_usd
        self._totals: dict[str, float] = {}

    def add(self, run_id: str, cost_usd: float) -> float:
        """Add cost to a run, raising before recording if it would breach the limit."""

        projected = self._totals.get(run_id, 0.0) + cost_usd
        if projected > self._max:
            raise RunCostExceeded(run_id, projected, self._max)
        self._totals[run_id] = projected
        return projected

    def get_cost(self, run_id: str) -> float:
        return self._totals.get(run_id, 0.0)

    def reset(self, run_id: str) -> None:
        self._totals.pop(run_id, None)
