"""Async persistence for companies and job postings.

All writes are idempotent: companies and postings upsert on their primary key, so
re-running ingestion updates rows in place rather than duplicating them. Postings that
vanish from a company's board are soft-deleted via :func:`mark_inactive`.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CompanyRow, JobPostingRow
from app.models import Company, JobPosting


def content_hash(posting: JobPosting) -> str:
    """Stable hash of the embed-relevant content, for change detection on reruns."""

    basis = f"{posting.title}\n{posting.description_cleaned}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


async def upsert_company(session: AsyncSession, company: Company) -> None:
    """Insert or update a company row by primary key."""

    values = company.model_dump()
    stmt = insert(CompanyRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[CompanyRow.id],
        set_={
            "name": stmt.excluded.name,
            "industry": stmt.excluded.industry,
            "size_range": stmt.excluded.size_range,
            "hq_location": stmt.excluded.hq_location,
        },
    )
    await session.execute(stmt)


async def upsert_posting(session: AsyncSession, posting: JobPosting) -> None:
    """Insert or update a job posting row by primary key (``{source}_{external_id}``)."""

    values = {
        "id": posting.id,
        "source": posting.source.value,
        "external_id": posting.external_id,
        "url": str(posting.url),
        "title": posting.title,
        "company_id": posting.company.id,
        "location": posting.location,
        "is_remote": posting.is_remote,
        "employment_type": posting.employment_type.value,
        "seniority": posting.seniority.value,
        "description_raw": posting.description_raw,
        "description_cleaned": posting.description_cleaned,
        "role_cluster": posting.role_cluster,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_currency": posting.salary_currency,
        "posted_at": posting.posted_at,
        "fetched_at": posting.fetched_at,
        "is_active": posting.is_active,
        "embedding_id": posting.embedding_id,
        "required_skills": [s.model_dump() for s in posting.required_skills],
        "content_hash": content_hash(posting),
    }
    stmt = insert(JobPostingRow).values(**values)
    update_cols = {
        col: stmt.excluded[col]
        for col in values
        if col not in ("id", "external_id", "source")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=[JobPostingRow.id], set_=update_cols
    )
    await session.execute(stmt)


async def mark_inactive(
    session: AsyncSession, company_id: str, seen_ids: set[str]
) -> list[str]:
    """Soft-delete postings for a company that were not seen in the latest fetch.

    Returns the ids of the postings marked inactive, so callers can propagate the
    same soft-delete to other stores (e.g. Qdrant) keyed off those ids.
    """

    stmt = (
        update(JobPostingRow)
        .where(JobPostingRow.company_id == company_id)
        .where(JobPostingRow.is_active.is_(True))
        .where(JobPostingRow.id.notin_(seen_ids) if seen_ids else True)
        .values(is_active=False)
        .returning(JobPostingRow.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
