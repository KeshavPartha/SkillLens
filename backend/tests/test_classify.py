"""Tests for heuristic classification (seniority, role cluster, skills)."""

from app.ingestion.classify import (
    classify_role_cluster,
    classify_seniority,
    enrich_posting,
    extract_skills,
)
from app.ingestion.normalize import normalize_greenhouse
from app.ingestion.registry import BoardConfig
from app.models import JobSource, SeniorityLevel

BOARD = BoardConfig("Acme", JobSource.GREENHOUSE, "acme")


def _posting(title: str, content: str = "We build things."):
    raw = dict(
        id=1,
        title=title,
        location={"name": "Remote"},
        first_published="2026-06-12T11:47:29-04:00",
        absolute_url="https://boards.greenhouse.io/acme/jobs/1",
        content=content,
    )
    return normalize_greenhouse(raw, BOARD)


def test_classify_seniority():
    assert classify_seniority("Staff Software Engineer") is SeniorityLevel.STAFF
    assert classify_seniority("Senior Backend Engineer") is SeniorityLevel.SENIOR
    assert classify_seniority("Software Engineer Intern") is SeniorityLevel.INTERN
    assert classify_seniority("Principal Engineer") is SeniorityLevel.PRINCIPAL
    # Unmarked engineer role defaults to MID.
    assert classify_seniority("Software Engineer") is SeniorityLevel.MID


def test_classify_role_cluster_from_title_is_high_confidence():
    cluster, high = classify_role_cluster("Backend Engineer", "")
    assert cluster == "backend"
    assert high is True

    cluster, high = classify_role_cluster("Machine Learning Engineer", "")
    assert cluster == "ml-engineer"

    cluster, high = classify_role_cluster("Distributed Systems Engineer", "")
    assert cluster == "distributed-systems"


def test_classify_role_cluster_no_match_returns_none():
    cluster, high = classify_role_cluster("Software Engineer", "general work")
    assert cluster is None
    assert high is False


def test_extract_skills_dedupes_and_canonicalizes():
    skills = extract_skills("We use Python, Golang, Kubernetes and postgres.")
    names = {s.name for s in skills}
    assert "python" in names
    assert "go" in names  # golang canonicalized
    assert "kubernetes" in names
    assert "postgresql" in names  # postgres canonicalized


async def test_enrich_posting_without_llm_uses_fallback():
    p = _posting("Senior Backend Engineer", "Python and Kafka required.")
    enriched = await enrich_posting(p, router=None, use_llm=False)
    assert enriched.seniority is SeniorityLevel.SENIOR
    assert enriched.role_cluster == "backend"
    assert {s.name for s in enriched.required_skills} >= {"python", "kafka"}


async def test_enrich_posting_fallback_cluster_when_no_match_and_no_llm():
    p = _posting("Software Engineer", "general engineering work")
    enriched = await enrich_posting(p, router=None, use_llm=False)
    assert enriched.role_cluster == "software-engineer"
