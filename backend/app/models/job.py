"""Job posting models.

These represent a single open role fetched from an ATS (Greenhouse, Lever) and
the structured signal we derive from it for matching against a candidate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class JobSource(str, Enum):
    """Which ATS the posting was fetched from."""

    GREENHOUSE = "greenhouse"
    LEVER = "lever"


class SeniorityLevel(str, Enum):
    """Normalized seniority bucket for a role."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    LEAD = "lead"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class EmploymentType(str, Enum):
    """Engagement type for the role."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"


class RequiredSkill(BaseModel):
    """A skill a job posting asks for, with market-derived scoring."""

    name: str
    canonical_name: str | None = None
    is_required: bool = True
    frequency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    market_prevalence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("name", "canonical_name", mode="before")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()


class Company(BaseModel):
    """The hiring company behind a posting."""

    id: str
    name: str
    industry: str | None = None
    size_range: str | None = None  # e.g. "51-200"
    hq_location: str | None = None


class JobPosting(BaseModel):
    """A single open role, normalized for matching and embedding.

    ``embedding_id`` is excluded from serialization — it is an internal handle
    into the vector store, not something the client needs.
    """

    id: str  # must be "{source}_{external_id}"
    source: JobSource
    external_id: str
    url: HttpUrl
    title: str
    company: Company
    location: str | None = None
    is_remote: bool = False
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    description_raw: str
    description_cleaned: str = ""
    required_skills: list[RequiredSkill] = Field(default_factory=list)
    role_cluster: str | None = None  # e.g. "ml-engineer"
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    posted_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True
    embedding_id: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _check_id_format(self) -> "JobPosting":
        expected = f"{self.source.value}_{self.external_id}"
        if self.id != expected:
            raise ValueError(
                f"id must be '{{source}}_{{external_id}}' (expected '{expected}', "
                f"got '{self.id}')"
            )
        return self

    @property
    def required_skill_names(self) -> set[str]:
        """Set of required-skill names (canonical where available)."""

        return {
            skill.canonical_name or skill.name for skill in self.required_skills
        }

    @property
    def salary_midpoint(self) -> int | None:
        """Midpoint of the salary band, or None if not enough data."""

        if self.salary_min is not None and self.salary_max is not None:
            return (self.salary_min + self.salary_max) // 2
        return None
