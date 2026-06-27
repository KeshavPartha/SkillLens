"""Tests for the market agent: RRF, skill aggregation, and hybrid query."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents.market_agent import (
    aggregate_skill_demand,
    query_market,
    reciprocal_rank_fusion,
)
from app.models import (
    AgentTrace,
    CandidateProfile,
    Company,
    JobPosting,
    RequiredSkill,
    Skill,
    StepType,
)


def _posting(ext_id: str, title: str, skills: list[str]) -> JobPosting:
    return JobPosting(
        id=f"greenhouse_{ext_id}",
        source="greenhouse",
        external_id=ext_id,
        url="https://example.com/job",
        title=title,
        company=Company(id="c1", name="Acme"),
        description_raw="A role doing things.",
        required_skills=[RequiredSkill(name=s) for s in skills],
        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _hit(job_id: str, title: str, skills: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        payload={
            "job_id": job_id,
            "title": title,
            "role_cluster": "backend",
            "required_skills": skills,
        }
    )


# --- pure functions -------------------------------------------------------


def test_rrf_rewards_agreement_across_rankings():
    # b is rank 2 then rank 1 (best combined); c is always near the bottom.
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60)
    ordered = sorted(scores, key=lambda i: scores[i], reverse=True)
    assert ordered[0] == "b"
    assert ordered[-1] == "c"


def test_rrf_uses_one_based_rank():
    scores = reciprocal_rank_fusion([["x"]], k=60)
    assert scores["x"] == pytest.approx(1 / 61)


def test_aggregate_skill_demand_counts_and_sorts():
    postings = [
        _posting("1", "Backend Engineer", ["python", "aws"]),
        _posting("2", "Backend Engineer", ["python", "go"]),
        _posting("3", "Backend Engineer", ["python"]),
    ]
    demand = aggregate_skill_demand(postings)
    assert demand[0].skill_name == "python"
    assert demand[0].posting_count == 3
    assert demand[0].prevalence == pytest.approx(1.0)
    # Ties broken alphabetically; aws before go.
    assert [d.skill_name for d in demand[1:]] == ["aws", "go"]


def test_aggregate_skill_demand_empty():
    assert aggregate_skill_demand([]) == []


def test_aggregate_counts_each_skill_once_per_posting():
    # Duplicate skill entries on one posting must not double-count.
    posting = _posting("1", "Backend Engineer", ["python", "python"])
    demand = aggregate_skill_demand([posting])
    assert demand[0].posting_count == 1


# --- query_market ---------------------------------------------------------


@pytest.mark.asyncio
async def test_query_market_fuses_and_aggregates(monkeypatch):
    profile = CandidateProfile(
        full_name="Dana",
        target_role="Backend Engineer",
        skills=[Skill(name="python", level="advanced")],
    )

    # b ranks first both semantically (hit order) and on keyword overlap.
    hits = [
        _hit("greenhouse_b", "Backend Engineer", ["python", "backend"]),
        _hit("greenhouse_a", "Frontend Developer", ["react"]),
        _hit("greenhouse_c", "Data Analyst", ["sql"]),
    ]

    async def fake_embed(texts):
        return [[0.1] * 384]

    async def fake_search(vector, *, limit, **kwargs):
        return hits

    async def fake_fetch(ids):
        return {
            "greenhouse_a": _posting("a", "Frontend Developer", ["python", "react"]),
            "greenhouse_b": _posting("b", "Backend Engineer", ["python", "aws"]),
            "greenhouse_c": _posting("c", "Data Analyst", ["python", "sql"]),
        }

    monkeypatch.setattr("app.agents.market_agent.embed_texts", fake_embed)
    monkeypatch.setattr("app.ingestion.qdrant_store.search", fake_search)
    monkeypatch.setattr("app.agents.market_agent._fetch_postings", fake_fetch)

    trace = AgentTrace(run_id="m1")
    result = await query_market(profile, top_k=3, run_id="m1", trace=trace)

    # b ranks top in both lists -> highest fused score -> relevance normalized to 1.0.
    assert result.postings[0].posting.id == "greenhouse_b"
    assert result.postings[0].relevance_score == pytest.approx(1.0)
    assert result.posting_count == 3
    assert result.skill_demand[0].skill_name == "python"

    step_types = [s.step_type for s in trace.steps]
    assert step_types == [
        StepType.MARKET_QUERY,
        StepType.MARKET_RESULTS,
        StepType.SKILL_AGGREGATION,
    ]
    # Local embeddings only: this stage adds no run cost.
    assert trace.total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_query_market_tolerates_missing_db_rows(monkeypatch):
    profile = CandidateProfile(full_name="Dana", target_role="Backend Engineer")
    hits = [_hit("greenhouse_a", "Backend Engineer", ["python"])]

    async def fake_embed(texts):
        return [[0.1] * 384]

    async def fake_search(vector, *, limit, **kwargs):
        return hits

    async def fake_fetch(ids):
        return {}  # Qdrant had it, Postgres didn't

    monkeypatch.setattr("app.agents.market_agent.embed_texts", fake_embed)
    monkeypatch.setattr("app.ingestion.qdrant_store.search", fake_search)
    monkeypatch.setattr("app.agents.market_agent._fetch_postings", fake_fetch)

    trace = AgentTrace(run_id="m2")
    result = await query_market(profile, run_id="m2", trace=trace)
    assert result.posting_count == 0
    assert result.skill_demand == []
