"""Tests for the /profile/parse SSE endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import app
from app.llm import LLMResponse, Provider

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
    "skills": [{"name": "Python", "level": "advanced", "years_experience": 4}],
    "target_seniority": "mid",
    "extraction_confidence": 0.9,
}


def _mock_router(*contents: str) -> AsyncMock:
    router = AsyncMock()
    router.complete.side_effect = [
        LLMResponse(
            content=c,
            model="claude-haiku-4-5",
            provider=Provider.ANTHROPIC,
            input_tokens=500,
            output_tokens=300,
            cost_usd=0.002,
        )
        for c in contents
    ]
    return router


async def _post(pdf_bytes: bytes, target_role: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/profile/parse",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"target_role": target_role},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return resp.text


@pytest.mark.asyncio
async def test_parse_profile_streams_steps_then_profile(monkeypatch):
    router = _mock_router(json.dumps(VALID_TOOL_INPUT))
    monkeypatch.setattr("app.api.routes.profile.get_router", lambda: router)
    pdf_bytes = (FIXTURES_DIR / "mid_backend.pdf").read_bytes()

    body = await _post(pdf_bytes, "Senior Backend Engineer")

    # Step frames stream first, in pipeline order, then the terminal profile frame.
    assert body.index("resume_parsing") < body.index("profile_extracted")
    assert body.index("profile_extracted") < body.index("event: profile")
    assert "Marcus Webb" in body
    assert "Senior Backend Engineer" in body
    # raw_resume_text is excluded from serialization and must not leak.
    assert "raw_resume_text" not in body
    router.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_parse_profile_bad_pdf_emits_error(monkeypatch):
    router = _mock_router()  # complete must never be called for an unparseable PDF
    monkeypatch.setattr("app.api.routes.profile.get_router", lambda: router)

    body = await _post(b"not a pdf", "Backend Engineer")

    assert "agent_error" in body  # the AGENT_ERROR trace step
    assert "event: error" in body
    router.complete.assert_not_called()
