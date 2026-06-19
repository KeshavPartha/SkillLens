"""Career plan models.

A CareerPlan turns a set of SkillGaps into a week-by-week learning roadmap with
concrete, portfolio-worthy deliverables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    model_validator,
)

from app.models.gap import SkillGap, GapSeverity


class ResourceType(str, Enum):
    """Kind of learning resource."""

    COURSE = "course"
    BOOK = "book"
    PROJECT = "project"
    DOCUMENTATION = "documentation"
    TUTORIAL = "tutorial"
    PRACTICE = "practice"
    COMMUNITY = "community"
    CERTIFICATION = "certification"


class Resource(BaseModel):
    """A single learning resource attached to a milestone."""

    title: str
    url: HttpUrl | None = None
    resource_type: ResourceType
    is_free: bool = False
    estimated_hours: float | None = None
    description: str = ""


class WeeklyMilestone(BaseModel):
    """One week of the learning plan."""

    week_number: int = Field(ge=1, le=12)
    theme: str  # e.g. "RAG Fundamentals"
    gap_skill_names: list[str] = Field(min_length=1)  # links to SkillGap.skill_name
    learning_objectives: list[str] = Field(min_length=1, max_length=5)
    resources: list[Resource] = Field(default_factory=list)
    deliverable: str = Field(min_length=10, max_length=500)
    deliverable_is_portfolio_worthy: bool = False
    estimated_hours_per_week: float = Field(default=10, ge=1, le=40)


class PlanStatus(str, Enum):
    """Lifecycle state of a plan as it moves through critique rounds."""

    DRAFT = "draft"
    REVISED = "revised"
    FINAL = "final"


class CareerPlan(BaseModel):
    """The full deliverable: gaps, a weekly roadmap, and summary scoring."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    candidate_name: str
    target_role: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: PlanStatus = PlanStatus.DRAFT
    gaps: list[SkillGap] = Field(min_length=1)
    total_gaps: int = 0  # auto-computed
    critical_gaps: int = 0  # auto-computed
    strengths: int = 0  # auto-computed
    milestones: list[WeeklyMilestone] = Field(default_factory=list)
    executive_summary: str = Field(min_length=50, max_length=2000)
    overall_readiness_score: float = Field(ge=0.0, le=1.0)
    critique_rounds: int = Field(default=0, ge=0, le=2)
    critique_notes: list[str] = Field(default_factory=list)
    run_cost_usd: float = 0.0

    @model_validator(mode="after")
    def _compute_gap_counts(self) -> "CareerPlan":
        # Strengths are tracked in the gaps list but counted separately; the
        # "gap" totals reflect actual gaps (everything that isn't a strength).
        strengths = [g for g in self.gaps if g.severity is GapSeverity.STRENGTH]
        self.strengths = len(strengths)
        self.total_gaps = len(self.gaps) - self.strengths
        self.critical_gaps = sum(
            1 for g in self.gaps if g.severity is GapSeverity.CRITICAL
        )
        return self

    @model_validator(mode="after")
    def _validate_milestone_sequence(self) -> "CareerPlan":
        if not self.milestones:
            return self
        if len(self.milestones) > 12:
            raise ValueError("a plan may have at most 12 milestones")
        for index, milestone in enumerate(self.milestones, start=1):
            if milestone.week_number != index:
                raise ValueError(
                    "milestones must be sequential starting at 1 "
                    f"(expected week {index}, got week {milestone.week_number})"
                )
        return self

    @property
    def portfolio_deliverables(self) -> list[str]:
        """Deliverables flagged as portfolio-worthy across all weeks."""

        return [
            m.deliverable for m in self.milestones if m.deliverable_is_portfolio_worthy
        ]

    @property
    def total_estimated_hours(self) -> float:
        """Sum of weekly effort across the whole plan."""

        return sum(m.estimated_hours_per_week for m in self.milestones)
