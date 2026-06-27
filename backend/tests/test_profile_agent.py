"""Tests for the profile agent (PDF resume -> CandidateProfile)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agents.profile_agent import (
    EXTRACT_PROFILE_TOOL,
    ProfileExtractionError,
    _extract_pdf_text,
    extract_profile,
)
from app.llm import LLMResponse, Provider
from app.models import AgentTrace, SkillLevel, StepType

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "resumes"

VALID_TOOL_INPUT = {
    "full_name": "Marcus Webb",
    "email": "marcus.webb@example.com",
    "summary": "Backend engineer with 4 years building distributed systems.",
    "experiences": [
        {
            "company": "Lighthouse Freight",
            "title": "Backend Engineer",
            "start_date": "2021-03-01",
            "end_date": None,
            "description": "Designed event-driven order pipeline.",
            "skills_used": ["python", "kafka"],
            "is_current": True,
        }
    ],
    "education": [],
    "projects": [],
    "skills": [
        {"name": "Python", "level": "advanced", "years_experience": 4},
        {"name": "Go", "level": "intermediate", "years_experience": 2},
    ],
    "target_seniority": "mid",
    "extraction_confidence": 0.9,
}


def _llm_response(content: str, cost: float = 0.002) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-haiku-4-5",
        provider=Provider.ANTHROPIC,
        input_tokens=500,
        output_tokens=300,
        cost_usd=cost,
    )


def _mock_router(*contents: str) -> AsyncMock:
    router = AsyncMock()
    router.complete.side_effect = [_llm_response(c) for c in contents]
    return router


def test_tool_schema_excludes_agent_set_fields():
    props = EXTRACT_PROFILE_TOOL["input_schema"]["properties"]
    assert "target_role" not in props
    assert "total_years_experience" not in props
    assert "raw_resume_text" not in props
    assert "full_name" in props
    assert "experiences" in props
    assert "skills" in props


def test_tool_schema_skill_level_enum_matches_model():
    skill_schema = EXTRACT_PROFILE_TOOL["input_schema"]["properties"]["skills"]["items"]
    assert set(skill_schema["properties"]["level"]["enum"]) == {
        level.value for level in SkillLevel
    }


def test_extract_pdf_text_reads_real_fixture():
    pdf_bytes = (FIXTURES_DIR / "mid_backend.pdf").read_bytes()
    text = _extract_pdf_text(pdf_bytes)
    assert "Marcus Webb" in text
    assert "Lighthouse Freight" in text


@pytest.mark.asyncio
async def test_extract_profile_happy_path():
    pdf_bytes = (FIXTURES_DIR / "mid_backend.pdf").read_bytes()
    router = _mock_router(json.dumps(VALID_TOOL_INPUT))
    trace = AgentTrace(run_id="run-1")

    profile = await extract_profile(
        pdf_bytes,
        target_role="Senior Backend Engineer",
        run_id="run-1",
        trace=trace,
        router=router,
    )

    assert profile.full_name == "Marcus Webb"
    assert profile.target_role == "Senior Backend Engineer"
    assert profile.raw_resume_text is not None
    assert "Marcus Webb" in profile.raw_resume_text
    assert profile.total_years_experience > 0

    step_types = [s.step_type for s in trace.steps]
    assert step_types == [StepType.RESUME_PARSING, StepType.PROFILE_EXTRACTED]
    extracted_step = trace.steps[-1]
    assert extracted_step.cost_usd == 0.002
    assert extracted_step.model_used == "claude-haiku-4-5"
    router.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_profile_retries_once_on_validation_error():
    pdf_bytes = (FIXTURES_DIR / "mid_backend.pdf").read_bytes()
    bad_input = {**VALID_TOOL_INPUT, "full_name": ""}
    bad_input["experiences"] = [
        {**VALID_TOOL_INPUT["experiences"][0], "start_date": "2021-03-01", "end_date": "2020-01-01"}
    ]
    router = _mock_router(json.dumps(bad_input), json.dumps(VALID_TOOL_INPUT))
    trace = AgentTrace(run_id="run-2")

    profile = await extract_profile(
        pdf_bytes,
        target_role="Backend Engineer",
        run_id="run-2",
        trace=trace,
        router=router,
    )

    assert profile.full_name == "Marcus Webb"
    assert router.complete.await_count == 2
    retry_messages = router.complete.await_args_list[1].kwargs["messages"]
    assert any("validation errors" in m.content for m in retry_messages)


@pytest.mark.asyncio
async def test_extract_profile_raises_after_two_validation_failures():
    pdf_bytes = (FIXTURES_DIR / "mid_backend.pdf").read_bytes()
    bad_input = {**VALID_TOOL_INPUT}
    bad_input["experiences"] = [
        {**VALID_TOOL_INPUT["experiences"][0], "start_date": "2021-03-01", "end_date": "2020-01-01"}
    ]
    router = _mock_router(json.dumps(bad_input), json.dumps(bad_input))
    trace = AgentTrace(run_id="run-3")

    with pytest.raises(ProfileExtractionError):
        await extract_profile(
            pdf_bytes,
            target_role="Backend Engineer",
            run_id="run-3",
            trace=trace,
            router=router,
        )

    assert trace.had_error
    assert trace.steps[-1].step_type == StepType.AGENT_ERROR


@pytest.mark.asyncio
async def test_extract_profile_rejects_unparseable_pdf():
    router = _mock_router()
    trace = AgentTrace(run_id="run-4")

    with pytest.raises(ProfileExtractionError):
        await extract_profile(
            b"not a pdf",
            target_role="Backend Engineer",
            run_id="run-4",
            trace=trace,
            router=router,
        )

    router.complete.assert_not_called()
    assert trace.steps[-1].step_type == StepType.AGENT_ERROR


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="requires ANTHROPIC_API_KEY")
class TestProfileAgentIntegration:
    """Hits the real Anthropic API against the 5 fixture resumes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fixture_name",
        [
            "new_grad_frontend.pdf",
            "mid_backend.pdf",
            "senior_ml.pdf",
            "staff_infra.pdf",
            "career_switcher_data.pdf",
        ],
    )
    async def test_extracts_real_resume(self, fixture_name):
        pdf_bytes = (FIXTURES_DIR / fixture_name).read_bytes()
        trace = AgentTrace(run_id=f"integration-{fixture_name}")

        profile = await extract_profile(
            pdf_bytes,
            target_role="Software Engineer",
            run_id=f"integration-{fixture_name}",
            trace=trace,
        )

        assert profile.full_name
        assert profile.extraction_confidence >= 0.5
        assert len(profile.skills) > 0
