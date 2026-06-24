"""Job ingestion orchestrator.

For each company in the registry: fetch -> normalize + SWE filter -> classify -> persist
to Postgres -> embed -> upsert to Qdrant -> reconcile vanished postings (soft delete).

The whole pipeline is idempotent: Postgres upserts on the posting id and Qdrant upserts on
a deterministic point id, so re-running updates rows/points in place instead of duplicating.
Run with ``python -m app.ingestion.pipeline``.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings
from app.db import mark_inactive, session_scope, upsert_company, upsert_posting
from app.ingestion.ats import fetch_greenhouse, fetch_lever
from app.ingestion.classify import enrich_posting
from app.ingestion.embed import embed_postings
from app.ingestion.normalize import company_from_board, is_swe, normalize
from app.ingestion.qdrant_store import (
    ensure_collection,
    point_id,
    upsert_postings,
)
from app.ingestion.qdrant_store import mark_inactive as mark_inactive_in_qdrant
from app.ingestion.registry import BoardConfig, get_registry
from app.llm import get_router
from app.models import JobPosting, JobSource

logger = logging.getLogger("skilllens.ingestion")


async def _fetch_board(client: httpx.AsyncClient, board: BoardConfig) -> list[dict]:
    if board.source is JobSource.GREENHOUSE:
        return await fetch_greenhouse(client, board.token)
    return await fetch_lever(client, board.token)


async def ingest_board(
    http: httpx.AsyncClient, board: BoardConfig, *, use_llm: bool, run_id: str
) -> int:
    """Ingest a single company's board. Returns the number of active SWE postings stored."""

    raw = await _fetch_board(http, board)
    postings = [normalize(r, board) for r in raw]
    swe = [p for p in postings if is_swe(p.title)]

    router = get_router() if use_llm else None
    enriched: list[JobPosting] = []
    for p in swe:
        e = await enrich_posting(p, router=router, run_id=run_id, use_llm=use_llm)
        enriched.append(e.model_copy(update={"embedding_id": point_id(e.id)}))

    # Persist metadata + reconcile postings that vanished from the board.
    async with session_scope() as session:
        await upsert_company(session, company_from_board(board))
        for e in enriched:
            await upsert_posting(session, e)
        vanished_ids = await mark_inactive(session, board.company_id, {e.id for e in enriched})

    # Embed and store vectors.
    vectors = await embed_postings(enriched)
    await upsert_postings(enriched, vectors)

    # Keep Qdrant's payload in sync with the Postgres soft-delete above.
    await mark_inactive_in_qdrant(vanished_ids)

    logger.info(
        "ingested %s: %d fetched, %d SWE stored", board.name, len(postings), len(enriched)
    )
    return len(enriched)


async def run_pipeline(
    *, target: int | None = None, use_llm: bool | None = None, run_id: str = "ingestion"
) -> int:
    """Run ingestion across the registry until ``target`` active SWE postings are reached."""

    settings = get_settings().ingestion
    target = target if target is not None else settings.target_active_postings
    use_llm = use_llm if use_llm is not None else settings.classify_low_confidence_with_llm

    await ensure_collection()
    total = 0
    async with httpx.AsyncClient(
        timeout=settings.http_timeout, follow_redirects=True
    ) as http:
        for board in get_registry():
            try:
                total += await ingest_board(http, board, use_llm=use_llm, run_id=run_id)
            except Exception:
                logger.exception("failed to ingest %s", board.name)
            if total >= target:
                break

    logger.info("ingestion complete: %d active SWE postings", total)
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    count = asyncio.run(run_pipeline())
    print(f"Done. {count} active SWE postings ingested.")


if __name__ == "__main__":
    main()
