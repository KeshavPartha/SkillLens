"""Market query models.

The market agent's output: the top-k postings retrieved for a candidate's target
role (each with a relevance score), plus the aggregated skill demand across them.
These feed the downstream gap analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.job import JobPosting


class ScoredPosting(BaseModel):
    """A retrieved posting with its fused relevance score (1.0 = best match)."""

    posting: JobPosting
    relevance_score: float = Field(ge=0.0, le=1.0)


class SkillDemand(BaseModel):
    """How often a single skill is required across the retrieved postings."""

    skill_name: str
    posting_count: int = Field(ge=0)
    # Fraction of retrieved postings that require this skill (0–1).
    prevalence: float = Field(ge=0.0, le=1.0)


class MarketResult(BaseModel):
    """The market agent's deliverable for one target role."""

    target_role: str
    postings: list[ScoredPosting] = Field(default_factory=list)
    skill_demand: list[SkillDemand] = Field(default_factory=list)

    @property
    def posting_count(self) -> int:
        """Number of postings retrieved."""

        return len(self.postings)
