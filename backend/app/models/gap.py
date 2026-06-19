"""Skill gap models.

A SkillGap is the core unit of analysis: it pairs what the candidate has against
what the market demands for a single skill, backed by concrete evidence from
real job postings.
"""

from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    model_validator,
)


class GapSeverity(str, Enum):
    """How much a gap matters to the candidate's target role."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    STRENGTH = "strength"  # not a gap — something the candidate already has


class PostingEvidence(BaseModel):
    """A pointer back to a real job posting that justifies a gap.

    ``jd_excerpt`` is the actual text from the job description so the UI can show
    the candidate *why* we flagged the skill.
    """

    posting_id: str
    posting_url: HttpUrl
    company_name: str
    job_title: str
    jd_excerpt: str = Field(min_length=10, max_length=500)
    relevance_score: float = Field(ge=0.0, le=1.0)


class SkillGap(BaseModel):
    """The delta between candidate ability and market demand for one skill."""

    skill_name: str
    canonical_name: str | None = None
    severity: GapSeverity
    candidate_level: str | None = None  # what the candidate has today
    market_expectation: str = Field(min_length=10, max_length=500)
    evidence: list[PostingEvidence] = Field(min_length=1)
    market_prevalence: float = Field(ge=0.0, le=1.0)
    estimated_weeks_to_close: int | None = Field(default=None, ge=1, le=52)
    learning_priority: int = Field(ge=1, le=10)  # 1 = highest

    @model_validator(mode="after")
    def _strengths_have_no_eta(self) -> "SkillGap":
        # A strength is not something you "close", so drop any ETA.
        if self.severity is GapSeverity.STRENGTH:
            self.estimated_weeks_to_close = None
        return self

    @property
    def posting_ids(self) -> list[str]:
        """IDs of every posting cited as evidence."""

        return [item.posting_id for item in self.evidence]

    @property
    def is_blocker(self) -> bool:
        """Whether this gap blocks the candidate from the role."""

        return self.severity is GapSeverity.CRITICAL
