"""Local embeddings via sentence-transformers (all-MiniLM-L6-v2, 384-dim).

The model is sync/CPU, so encoding runs in a thread pool to stay async-friendly. The model
is loaded once, lazily, on first use.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.config import get_settings
from app.models import JobPosting

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        settings = get_settings().embedding
        _model = SentenceTransformer(settings.model_name, device=settings.device)
    return _model


def build_embedding_text(posting: JobPosting) -> str:
    """Compose the text representation embedded for a posting."""

    parts = [
        posting.title,
        f"{posting.seniority.value} {posting.role_cluster or ''}".strip(),
        posting.location or "",
        posting.description_cleaned,
    ]
    return "\n".join(p for p in parts if p)


def _encode(texts: list[str]) -> list[list[float]]:
    settings = get_settings().embedding
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=settings.batch_size,
        normalize_embeddings=settings.normalize,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed raw texts; returns one 384-dim vector per input."""

    if not texts:
        return []
    return await asyncio.to_thread(_encode, texts)


async def embed_postings(postings: list[JobPosting]) -> list[list[float]]:
    """Embed a batch of postings using their composed text representation."""

    return await embed_texts([build_embedding_text(p) for p in postings])
