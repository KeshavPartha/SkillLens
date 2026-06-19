"""SkillLens data models — the source of truth shared across all agents.

Re-exports every model so callers can write::

    from app.models import CandidateProfile, JobPosting, SkillGap
"""

from app.models.profile import (
    SkillLevel,
    Skill,
    Experience,
    Education,
    Project,
    CandidateProfile,
)
from app.models.job import (
    JobSource,
    SeniorityLevel,
    EmploymentType,
    RequiredSkill,
    Company,
    JobPosting,
)
from app.models.gap import (
    GapSeverity,
    PostingEvidence,
    SkillGap,
)
from app.models.plan import (
    ResourceType,
    Resource,
    WeeklyMilestone,
    PlanStatus,
    CareerPlan,
)
from app.models.trace import (
    StepType,
    TraceStep,
    AgentTrace,
)

__all__ = [
    # profile
    "SkillLevel",
    "Skill",
    "Experience",
    "Education",
    "Project",
    "CandidateProfile",
    # job
    "JobSource",
    "SeniorityLevel",
    "EmploymentType",
    "RequiredSkill",
    "Company",
    "JobPosting",
    # gap
    "GapSeverity",
    "PostingEvidence",
    "SkillGap",
    # plan
    "ResourceType",
    "Resource",
    "WeeklyMilestone",
    "PlanStatus",
    "CareerPlan",
    # trace
    "StepType",
    "TraceStep",
    "AgentTrace",
]
