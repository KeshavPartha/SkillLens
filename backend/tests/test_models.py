"""Tests for the SkillLens data models.

Coverage focuses on the behavior that agents depend on: computed properties,
validators that should pass, validators that should raise, and the AgentTrace
accumulation logic.
"""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    AgentTrace,
    CandidateProfile,
    CareerPlan,
    Company,
    Education,
    Experience,
    GapSeverity,
    JobPosting,
    JobSource,
    PostingEvidence,
    RequiredSkill,
    Resource,
    ResourceType,
    Skill,
    SkillGap,
    SkillLevel,
    StepType,
    TraceStep,
    WeeklyMilestone,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def experience() -> Experience:
    return Experience(
        company="Acme",
        title="Engineer",
        start_date=date(2020, 1, 15),
        end_date=date(2022, 1, 15),
        description="Built things.",
        skills_used=["python"],
        is_current=False,
    )


@pytest.fixture
def current_experience() -> Experience:
    return Experience(
        company="Globex",
        title="Senior Engineer",
        start_date=date(2022, 2, 1),
        end_date=None,
        is_current=True,
    )


@pytest.fixture
def profile(experience: Experience, current_experience: Experience) -> CandidateProfile:
    return CandidateProfile(
        full_name="Ada Lovelace",
        summary="Engineer",
        experiences=[experience, current_experience],
        skills=[
            Skill(name="  Python ", level=SkillLevel.EXPERT),
            Skill(name="SQL", level=SkillLevel.INTERMEDIATE, canonical_name="sql"),
        ],
        target_role="ML Engineer",
    )


@pytest.fixture
def evidence() -> PostingEvidence:
    return PostingEvidence(
        posting_id="greenhouse_123",
        posting_url="https://jobs.example.com/123",
        company_name="Example",
        job_title="ML Engineer",
        jd_excerpt="We require strong experience with RAG pipelines.",
        relevance_score=0.9,
    )


@pytest.fixture
def gap(evidence: PostingEvidence) -> SkillGap:
    return SkillGap(
        skill_name="rag",
        severity=GapSeverity.CRITICAL,
        market_expectation="Production RAG experience is expected.",
        evidence=[evidence],
        market_prevalence=0.7,
        estimated_weeks_to_close=6,
        learning_priority=1,
    )


@pytest.fixture
def strength_gap(evidence: PostingEvidence) -> SkillGap:
    return SkillGap(
        skill_name="python",
        severity=GapSeverity.STRENGTH,
        market_expectation="Strong Python is expected and the candidate has it.",
        evidence=[evidence],
        market_prevalence=0.95,
        estimated_weeks_to_close=4,  # should be wiped by validator
        learning_priority=10,
    )


@pytest.fixture
def milestone() -> WeeklyMilestone:
    return WeeklyMilestone(
        week_number=1,
        theme="RAG Fundamentals",
        gap_skill_names=["rag"],
        learning_objectives=["Understand retrieval"],
        resources=[
            Resource(title="RAG 101", resource_type=ResourceType.COURSE, is_free=True)
        ],
        deliverable="A working RAG demo over a small corpus.",
        deliverable_is_portfolio_worthy=True,
        estimated_hours_per_week=12,
    )


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


def test_skill_name_is_stripped_and_lowercased():
    skill = Skill(name="  PyThon ", level=SkillLevel.EXPERT, canonical_name=" Py ")
    assert skill.name == "python"
    assert skill.canonical_name == "py"


def test_experience_tenure_months(experience: Experience):
    # 2020-01-15 -> 2022-01-15 is exactly 24 months.
    assert experience.tenure_months == 24


def test_experience_tenure_partial_month():
    exp = Experience(
        company="A",
        title="T",
        start_date=date(2020, 1, 20),
        end_date=date(2020, 3, 10),  # day < start day -> partial month dropped
    )
    assert exp.tenure_months == 1


def test_experience_end_before_start_raises():
    with pytest.raises(ValidationError):
        Experience(
            company="A",
            title="T",
            start_date=date(2022, 1, 1),
            end_date=date(2021, 1, 1),
        )


def test_education_graduation_year_bounds():
    with pytest.raises(ValidationError):
        Education(institution="MIT", degree="BS", graduation_year=1900)


def test_education_gpa_bounds():
    with pytest.raises(ValidationError):
        Education(institution="MIT", degree="BS", gpa=5.0)


def test_profile_total_years_autocomputed(profile: CandidateProfile):
    # 24 months + (now since 2022-02-01) -> at least 2 years.
    assert profile.total_years_experience >= 2.0


def test_profile_total_years_respected_when_supplied(experience: Experience):
    profile = CandidateProfile(
        full_name="X",
        summary="",
        experiences=[experience],
        target_role="Eng",
        total_years_experience=10.0,
    )
    assert profile.total_years_experience == 10.0


def test_profile_skill_names_uses_canonical(profile: CandidateProfile):
    assert profile.skill_names == {"python", "sql"}


def test_profile_current_role(profile: CandidateProfile):
    assert profile.current_role is not None
    assert profile.current_role.company == "Globex"


def test_profile_raw_resume_text_excluded():
    profile = CandidateProfile(
        full_name="X",
        summary="",
        target_role="Eng",
        raw_resume_text="SECRET RESUME",
    )
    assert "raw_resume_text" not in profile.model_dump()


# --------------------------------------------------------------------------- #
# Job
# --------------------------------------------------------------------------- #


def _job(**overrides) -> JobPosting:
    base = dict(
        id="greenhouse_abc",
        source=JobSource.GREENHOUSE,
        external_id="abc",
        url="https://jobs.example.com/abc",
        title="ML Engineer",
        company=Company(id="c1", name="Example"),
        description_raw="Full JD text.",
        required_skills=[RequiredSkill(name=" Python ")],
        salary_min=100,
        salary_max=200,
        posted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return JobPosting(**base)


def test_required_skill_name_normalized():
    skill = RequiredSkill(name="  KuBerNetes ")
    assert skill.name == "kubernetes"


def test_job_id_format_valid():
    job = _job()
    assert job.id == "greenhouse_abc"


def test_job_id_format_invalid_raises():
    with pytest.raises(ValidationError):
        _job(id="wrong_id")


def test_job_required_skill_names(job=None):
    job = _job()
    assert job.required_skill_names == {"python"}


def test_job_salary_midpoint():
    assert _job().salary_midpoint == 150


def test_job_salary_midpoint_none_when_missing():
    assert _job(salary_min=None).salary_midpoint is None


def test_job_embedding_id_excluded():
    job = _job(embedding_id="vec_1")
    assert "embedding_id" not in job.model_dump()


# --------------------------------------------------------------------------- #
# Gap
# --------------------------------------------------------------------------- #


def test_gap_requires_evidence():
    with pytest.raises(ValidationError):
        SkillGap(
            skill_name="rag",
            severity=GapSeverity.MAJOR,
            market_expectation="Production RAG experience is expected.",
            evidence=[],
            market_prevalence=0.5,
            learning_priority=2,
        )


def test_gap_posting_evidence_excerpt_bounds():
    with pytest.raises(ValidationError):
        PostingEvidence(
            posting_id="p1",
            posting_url="https://x.com",
            company_name="X",
            job_title="Y",
            jd_excerpt="short",  # < 10 chars
            relevance_score=0.5,
        )


def test_gap_is_blocker(gap: SkillGap):
    assert gap.is_blocker is True


def test_gap_posting_ids(gap: SkillGap):
    assert gap.posting_ids == ["greenhouse_123"]


def test_strength_gap_clears_eta(strength_gap: SkillGap):
    assert strength_gap.estimated_weeks_to_close is None


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


def _plan(gaps, milestones, **overrides) -> CareerPlan:
    base = dict(
        candidate_name="Ada",
        target_role="ML Engineer",
        gaps=gaps,
        milestones=milestones,
        executive_summary="A" * 60,
        overall_readiness_score=0.6,
    )
    base.update(overrides)
    return CareerPlan(**base)


def test_plan_gap_counts(gap: SkillGap, strength_gap: SkillGap, milestone):
    plan = _plan([gap, strength_gap], [milestone])
    assert plan.strengths == 1
    assert plan.total_gaps == 1  # excludes the strength
    assert plan.critical_gaps == 1


def test_plan_requires_at_least_one_gap(milestone):
    with pytest.raises(ValidationError):
        _plan([], [milestone])


def test_plan_milestones_must_be_sequential(gap: SkillGap):
    bad = WeeklyMilestone(
        week_number=2,  # should be 1
        theme="T",
        gap_skill_names=["rag"],
        learning_objectives=["o"],
        deliverable="A concrete deliverable artifact.",
    )
    with pytest.raises(ValidationError):
        _plan([gap], [bad])


def test_plan_portfolio_deliverables(gap: SkillGap, milestone):
    plan = _plan([gap], [milestone])
    assert plan.portfolio_deliverables == [milestone.deliverable]


def test_plan_total_estimated_hours(gap: SkillGap, milestone):
    plan = _plan([gap], [milestone])
    assert plan.total_estimated_hours == 12


def test_plan_executive_summary_too_short(gap: SkillGap, milestone):
    with pytest.raises(ValidationError):
        _plan([gap], [milestone], executive_summary="too short")


def test_plan_id_autogenerated(gap: SkillGap, milestone):
    plan = _plan([gap], [milestone])
    assert isinstance(plan.plan_id, str) and len(plan.plan_id) > 0


# --------------------------------------------------------------------------- #
# Trace
# --------------------------------------------------------------------------- #


def test_trace_step_is_llm_step():
    step = TraceStep(
        step_type=StepType.LLM_CALL_START, agent_name="gap", message="calling"
    )
    assert step.is_llm_step is True


def test_trace_step_is_error():
    step = TraceStep(
        step_type=StepType.AGENT_ERROR, agent_name="gap", message="boom"
    )
    assert step.is_error is True


def test_trace_message_bounds():
    with pytest.raises(ValidationError):
        TraceStep(step_type=StepType.INFO, agent_name="x", message="")


def test_agent_trace_accumulates_cost_and_tokens():
    trace = AgentTrace(run_id="run_1")
    trace.append_step(
        TraceStep(
            step_type=StepType.LLM_CALL_END,
            agent_name="gap",
            message="done",
            cost_usd=0.01,
            input_tokens=100,
            output_tokens=50,
        )
    )
    trace.append_step(
        TraceStep(
            step_type=StepType.LLM_CALL_END,
            agent_name="plan",
            message="done",
            cost_usd=0.02,
            input_tokens=200,
            output_tokens=80,
        )
    )
    assert len(trace.steps) == 2
    assert trace.total_cost_usd == pytest.approx(0.03)
    assert trace.total_input_tokens == 300
    assert trace.total_output_tokens == 130
    assert trace.had_error is False


def test_agent_trace_handles_missing_cost_fields():
    trace = AgentTrace(run_id="run_2")
    trace.append_step(
        TraceStep(step_type=StepType.INFO, agent_name="x", message="info only")
    )
    assert trace.total_cost_usd == 0.0
    assert trace.total_input_tokens == 0


def test_agent_trace_sets_had_error_on_error_step():
    trace = AgentTrace(run_id="run_3")
    trace.append_step(
        TraceStep(step_type=StepType.AGENT_ERROR, agent_name="x", message="boom")
    )
    assert trace.had_error is True


def test_agent_trace_to_sse_payload():
    trace = AgentTrace(run_id="run_4")
    step = trace.append_step(
        TraceStep(
            step_type=StepType.LLM_CALL_END,
            agent_name="gap",
            message="done",
            cost_usd=0.05,
        )
    )
    payload = trace.to_sse_payload(step)
    assert payload["run_id"] == "run_4"
    assert payload["running_cost_usd"] == pytest.approx(0.05)
    assert payload["step"]["message"] == "done"
    assert isinstance(payload["step"], dict)
