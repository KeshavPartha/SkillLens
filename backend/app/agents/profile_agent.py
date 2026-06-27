"""Profile agent: PDF resume -> validated CandidateProfile.

Parses the uploaded PDF, asks Claude Haiku (via the mandatory ``app/llm``
router) to extract a structured profile using a forced tool call, and
assembles a validated :class:`CandidateProfile`. ``target_role`` and
``raw_resume_text`` are set by this agent, not the LLM.
"""

from __future__ import annotations

import asyncio
import io
import json

from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.llm import LLMMessage, LLMRouter, ModelTask, RunCostExceeded, get_router
from app.models import AgentTrace, CandidateProfile, SkillLevel, StepType, TraceStep

AGENT_NAME = "profile_agent"

# Fields the LLM must not set — they're injected by this agent.
_AGENT_SET_FIELDS = ("target_role", "raw_resume_text", "total_years_experience")

_SYSTEM_PROMPT = (
    "You extract structured candidate profile data from raw resume text. "
    "Call the extract_profile tool exactly once with everything you can find. "
    "Use ISO 8601 dates (YYYY-MM-DD); if only a month/year is known, use the "
    "first day of that month. Leave fields out if you can't find them. Set "
    "extraction_confidence to your honest confidence (0-1) that the "
    "extraction is complete and accurate."
)

_SKILL_LEVELS = [level.value for level in SkillLevel]

_EXPERIENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "title": {"type": "string"},
        "start_date": {"type": "string", "format": "date", "description": "ISO 8601, YYYY-MM-DD"},
        "end_date": {
            "type": ["string", "null"],
            "format": "date",
            "description": "ISO 8601, YYYY-MM-DD. Omit or null if this is the current role.",
        },
        "description": {"type": "string"},
        "skills_used": {"type": "array", "items": {"type": "string"}},
        "is_current": {"type": "boolean"},
    },
    "required": ["company", "title", "start_date"],
}

_EDUCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "institution": {"type": "string"},
        "degree": {"type": "string"},
        "field_of_study": {"type": ["string", "null"]},
        "graduation_year": {"type": ["integer", "null"]},
        "gpa": {"type": ["number", "null"]},
    },
    "required": ["institution", "degree"],
}

_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "skills_demonstrated": {"type": "array", "items": {"type": "string"}},
        "url": {"type": ["string", "null"]},
        "is_open_source": {"type": "boolean"},
    },
    "required": ["name"],
}

_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "level": {"type": "string", "enum": _SKILL_LEVELS},
        "years_experience": {"type": ["number", "null"]},
    },
    "required": ["name", "level"],
}

EXTRACT_PROFILE_TOOL = {
    "name": "extract_profile",
    "description": "Record the structured candidate profile extracted from a resume.",
    "input_schema": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "email": {"type": ["string", "null"]},
            "linkedin_url": {"type": ["string", "null"]},
            "github_url": {"type": ["string", "null"]},
            "summary": {"type": "string"},
            "experiences": {"type": "array", "items": _EXPERIENCE_SCHEMA},
            "education": {"type": "array", "items": _EDUCATION_SCHEMA},
            "projects": {"type": "array", "items": _PROJECT_SCHEMA},
            "skills": {"type": "array", "items": _SKILL_SCHEMA},
            "target_seniority": {"type": ["string", "null"]},
            "extraction_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["full_name", "extraction_confidence"],
    },
}


class ProfileExtractionError(Exception):
    """Raised when a resume PDF can't be turned into a CandidateProfile."""


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise ProfileExtractionError(f"failed to parse PDF: {exc}") from exc


def _build_tool_input_messages(raw_text: str) -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(role="user", content=raw_text),
    ]


async def extract_profile(
    pdf_bytes: bytes,
    *,
    target_role: str,
    target_seniority: str | None = None,
    run_id: str,
    trace: AgentTrace,
    router: LLMRouter | None = None,
) -> CandidateProfile:
    """Parse a resume PDF into a validated CandidateProfile via Claude Haiku."""

    router = router or get_router()

    trace.append_step(
        TraceStep(
            step_type=StepType.RESUME_PARSING,
            agent_name=AGENT_NAME,
            message="Parsing resume PDF",
        )
    )

    try:
        raw_text = await asyncio.to_thread(_extract_pdf_text, pdf_bytes)
    except ProfileExtractionError as exc:
        trace.append_step(
            TraceStep(
                step_type=StepType.AGENT_ERROR,
                agent_name=AGENT_NAME,
                message=str(exc),
            )
        )
        raise

    if not raw_text.strip():
        message = "Resume PDF contained no extractable text"
        trace.append_step(
            TraceStep(step_type=StepType.AGENT_ERROR, agent_name=AGENT_NAME, message=message)
        )
        raise ProfileExtractionError(message)

    messages = _build_tool_input_messages(raw_text)

    tool_input, resp = await _call_extract_profile(router, messages, run_id)

    try:
        profile = _build_profile(tool_input, target_role, target_seniority, raw_text)
    except ValidationError as exc:
        messages = messages + [
            LLMMessage(role="assistant", content=resp.content),
            LLMMessage(
                role="user",
                content=(
                    "Your previous extraction had validation errors:\n"
                    f"{exc}\n"
                    "Call extract_profile again with corrected data."
                ),
            ),
        ]
        tool_input, resp = await _call_extract_profile(router, messages, run_id)
        try:
            profile = _build_profile(tool_input, target_role, target_seniority, raw_text)
        except ValidationError as retry_exc:
            trace.append_step(
                TraceStep(
                    step_type=StepType.AGENT_ERROR,
                    agent_name=AGENT_NAME,
                    message="Extraction failed validation after one retry",
                )
            )
            raise ProfileExtractionError(str(retry_exc)) from retry_exc

    trace.append_step(
        TraceStep(
            step_type=StepType.PROFILE_EXTRACTED,
            agent_name=AGENT_NAME,
            message=f"Extracted profile for {profile.full_name}",
            payload={
                "skill_count": len(profile.skills),
                "experience_count": len(profile.experiences),
            },
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_usd=resp.cost_usd,
            model_used=resp.model,
        )
    )
    return profile


def _build_profile(
    tool_input: dict,
    target_role: str,
    target_seniority: str | None,
    raw_text: str,
) -> CandidateProfile:
    cleaned = {k: v for k, v in tool_input.items() if k not in _AGENT_SET_FIELDS}
    llm_seniority = cleaned.pop("target_seniority", None)
    return CandidateProfile(
        **cleaned,
        target_role=target_role,
        target_seniority=target_seniority or llm_seniority,
        raw_resume_text=raw_text,
    )


async def _call_extract_profile(
    router: LLMRouter, messages: list[LLMMessage], run_id: str
) -> tuple[dict, object]:
    try:
        resp = await router.complete(
            task=ModelTask.EXTRACTION,
            run_id=run_id,
            max_tokens=4096,
            messages=messages,
            tools=[EXTRACT_PROFILE_TOOL],
            tool_choice={"type": "tool", "name": "extract_profile"},
        )
    except RunCostExceeded:
        raise
    except Exception as exc:
        raise ProfileExtractionError(f"LLM call failed: {exc}") from exc

    try:
        tool_input = json.loads(resp.content)
    except json.JSONDecodeError as exc:
        raise ProfileExtractionError(f"model did not return valid JSON: {exc}") from exc

    return tool_input, resp
