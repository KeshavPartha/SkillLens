"""Qdrant vector store for job postings.

Point ids are deterministic UUIDs derived from the posting id (Qdrant requires uint/UUID,
not arbitrary strings), so re-running ingestion upserts the same point rather than creating
duplicates. The ``JobPosting.embedding_id`` is set to this UUID.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.config import get_settings
from app.models import JobPosting

# Fixed namespace so point ids are stable across runs/processes.
_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

# Payload fields the market agent filters on; Qdrant requires an index per field.
_PAYLOAD_INDEXES: dict[str, PayloadSchemaType] = {
    "is_active": PayloadSchemaType.BOOL,
    "seniority": PayloadSchemaType.KEYWORD,
    "role_cluster": PayloadSchemaType.KEYWORD,
}


def point_id(job_id: str) -> str:
    """Deterministic Qdrant point id for a posting (uuid5 of the job id)."""

    return str(uuid.uuid5(_NAMESPACE, job_id))


@lru_cache
def get_qdrant_client() -> AsyncQdrantClient:
    """Return the process-wide async Qdrant client."""

    settings = get_settings().qdrant
    return AsyncQdrantClient(url=settings.url, api_key=settings.api_key)


async def ensure_collection(client: AsyncQdrantClient | None = None) -> None:
    """Create the postings collection and its payload indexes if missing.

    Payload indexes are required for the market agent's filtered search (Qdrant
    rejects a filter on an unindexed field). ``create_payload_index`` is idempotent,
    so this is safe to call on an already-populated collection.
    """

    settings = get_settings().qdrant
    client = client or get_qdrant_client()
    if not await client.collection_exists(settings.collection_name):
        await client.create_collection(
            collection_name=settings.collection_name,
            vectors_config=VectorParams(
                size=settings.vector_size,
                distance=getattr(Distance, settings.distance.upper()),
            ),
        )
    for field_name, field_schema in _PAYLOAD_INDEXES.items():
        await client.create_payload_index(
            collection_name=settings.collection_name,
            field_name=field_name,
            field_schema=field_schema,
        )


def _payload(posting: JobPosting) -> dict:
    return {
        "job_id": posting.id,
        "source": posting.source.value,
        "company_id": posting.company.id,
        "company_name": posting.company.name,
        "title": posting.title,
        "seniority": posting.seniority.value,
        "role_cluster": posting.role_cluster,
        "location": posting.location,
        "is_remote": posting.is_remote,
        "employment_type": posting.employment_type.value,
        "is_active": posting.is_active,
        "posted_at": posting.posted_at.isoformat(),
        "url": str(posting.url),
        "required_skills": sorted(posting.required_skill_names),
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
    }


async def upsert_postings(
    postings: list[JobPosting],
    vectors: list[list[float]],
    client: AsyncQdrantClient | None = None,
) -> int:
    """Upsert postings + their vectors as Qdrant points. Returns the count upserted."""

    if not postings:
        return 0
    settings = get_settings().qdrant
    client = client or get_qdrant_client()
    points = [
        PointStruct(
            id=point_id(posting.id),
            vector=vector,
            payload=_payload(posting),
        )
        for posting, vector in zip(postings, vectors, strict=True)
    ]
    await client.upsert(collection_name=settings.collection_name, points=points)
    return len(points)


async def mark_inactive(job_ids: list[str], client: AsyncQdrantClient | None = None) -> None:
    """Flip ``is_active`` to ``False`` on existing points for the given job ids.

    Keeps Qdrant's payload in sync with a Postgres soft-delete (``app.db.mark_inactive``)
    without re-sending vectors, so a stale "active" posting can't surface in search after
    it has vanished from its source board.
    """

    if not job_ids:
        return
    settings = get_settings().qdrant
    client = client or get_qdrant_client()
    await client.set_payload(
        collection_name=settings.collection_name,
        payload={"is_active": False},
        points=[point_id(job_id) for job_id in job_ids],
    )


async def search(
    query_vector: list[float],
    *,
    limit: int,
    seniority: str | None = None,
    role_cluster: str | None = None,
    active_only: bool = True,
    client: AsyncQdrantClient | None = None,
) -> list[ScoredPoint]:
    """Vector search the postings collection, returning scored points with payloads.

    A thin store function: optional payload filters only, no fusion/re-ranking logic
    (that lives in the market agent).
    """

    settings = get_settings().qdrant
    client = client or get_qdrant_client()

    conditions: list[FieldCondition] = []
    if active_only:
        conditions.append(FieldCondition(key="is_active", match=MatchValue(value=True)))
    if seniority:
        conditions.append(
            FieldCondition(key="seniority", match=MatchValue(value=seniority))
        )
    if role_cluster:
        conditions.append(
            FieldCondition(key="role_cluster", match=MatchValue(value=role_cluster))
        )

    response = await client.query_points(
        collection_name=settings.collection_name,
        query=query_vector,
        limit=limit,
        query_filter=Filter(must=conditions) if conditions else None,
        with_payload=True,
    )
    return response.points


async def count_points(client: AsyncQdrantClient | None = None) -> int:
    """Return the number of points in the postings collection."""

    settings = get_settings().qdrant
    client = client or get_qdrant_client()
    result = await client.count(collection_name=settings.collection_name)
    return result.count
