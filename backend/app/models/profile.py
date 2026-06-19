"""Candidate profile models.

These describe everything we know about a job seeker: their skills, work
history, education, and projects. Agents extract this from a resume and enrich
it as the pipeline runs.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class SkillLevel(str, Enum):
    """Self-reported / inferred proficiency for a single skill."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class Skill(BaseModel):
    """A single skill held by the candidate.

    ``canonical_name`` is left empty at extraction time and filled in later by
    the normalization step so that "JS" and "JavaScript" collapse together.
    """

    name: str
    level: SkillLevel
    years_experience: float | None = None
    canonical_name: str | None = None

    @field_validator("name", "canonical_name", mode="before")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()


class Experience(BaseModel):
    """A single role in the candidate's work history."""

    company: str
    title: str
    start_date: date
    end_date: date | None = None  # None means this is the current role
    description: str = ""
    skills_used: list[str] = Field(default_factory=list)
    is_current: bool = False

    @model_validator(mode="after")
    def _check_dates(self) -> "Experience":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be after start_date")
        return self

    @property
    def tenure_months(self) -> int:
        """Whole months spent in this role (through end_date or today)."""

        end = self.end_date or date.today()
        months = (end.year - self.start_date.year) * 12 + (
            end.month - self.start_date.month
        )
        # Don't count a partial trailing month that hasn't completed.
        if end.day < self.start_date.day:
            months -= 1
        return max(months, 0)


class Education(BaseModel):
    """A degree or program of study."""

    institution: str
    degree: str
    field_of_study: str | None = None
    graduation_year: int | None = Field(default=None, ge=1950, le=2030)
    gpa: float | None = Field(default=None, ge=0.0, le=4.0)


class Project(BaseModel):
    """A portfolio project the candidate has built."""

    name: str
    description: str = ""
    skills_demonstrated: list[str] = Field(default_factory=list)
    url: HttpUrl | None = None
    is_open_source: bool = False


class CandidateProfile(BaseModel):
    """The complete, structured view of a candidate.

    ``raw_resume_text`` is excluded from serialization so it is never leaked to
    the client; it exists only for server-side re-processing.
    """

    full_name: str
    email: str | None = None
    linkedin_url: HttpUrl | None = None
    github_url: HttpUrl | None = None
    summary: str = ""
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    target_role: str  # supplied by the user at upload time
    target_seniority: str | None = None
    total_years_experience: float = 0.0  # auto-computed if not supplied
    raw_resume_text: str | None = Field(default=None, exclude=True)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _compute_total_years(self) -> "CandidateProfile":
        # Only auto-compute when the caller didn't supply a value.
        if not self.total_years_experience and self.experiences:
            total_months = sum(exp.tenure_months for exp in self.experiences)
            self.total_years_experience = round(total_months / 12, 1)
        return self

    @property
    def skill_names(self) -> set[str]:
        """Set of skill names (canonical where available)."""

        return {skill.canonical_name or skill.name for skill in self.skills}

    @property
    def current_role(self) -> Experience | None:
        """First experience flagged as current, if any."""

        return next((exp for exp in self.experiences if exp.is_current), None)
