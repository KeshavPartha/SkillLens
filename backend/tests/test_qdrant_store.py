"""Tests for the Qdrant store helpers (deterministic ids, payload, upsert)."""

from datetime import datetime, timezone

from app.ingestion.qdrant_store import point_id, upsert_postings
from app.models import Company, JobPosting, JobSource, SeniorityLevel


def _posting(ext="123") -> JobPosting:
    return JobPosting(
        id=f"greenhouse_{ext}",
        source=JobSource.GREENHOUSE,
        external_id=ext,
        url="https://example.com/jobs/" + ext,
        title="Senior Backend Engineer",
        company=Company(id="greenhouse_acme", name="Acme"),
        seniority=SeniorityLevel.SENIOR,
        role_cluster="backend",
        description_raw="x",
        description_cleaned="build backend systems",
        posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def test_point_id_is_deterministic_and_uuid():
    a = point_id("greenhouse_123")
    b = point_id("greenhouse_123")
    c = point_id("greenhouse_456")
    assert a == b  # stable across calls -> idempotent upserts
    assert a != c
    assert len(a) == 36  # uuid string


class _FakeClient:
    def __init__(self):
        self.collection_exists_called = False
        self.upserted = None

    async def upsert(self, *, collection_name, points):
        self.upserted = (collection_name, points)


async def test_upsert_postings_builds_points_with_payload():
    client = _FakeClient()
    postings = [_posting("1"), _posting("2")]
    vectors = [[0.1] * 384, [0.2] * 384]
    n = await upsert_postings(postings, vectors, client=client)

    assert n == 2
    collection_name, points = client.upserted
    assert collection_name == "job_postings"
    assert points[0].id == point_id("greenhouse_1")
    payload = points[0].payload
    assert payload["job_id"] == "greenhouse_1"
    assert payload["seniority"] == "senior"
    assert payload["role_cluster"] == "backend"
    assert payload["source"] == "greenhouse"


async def test_upsert_empty_is_noop():
    client = _FakeClient()
    n = await upsert_postings([], [], client=client)
    assert n == 0
    assert client.upserted is None
