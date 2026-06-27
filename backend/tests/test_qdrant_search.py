"""Tests for qdrant_store.search filter construction and result passthrough."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ingestion import qdrant_store


def _client(points: list) -> AsyncMock:
    client = AsyncMock()
    client.query_points.return_value = SimpleNamespace(points=points)
    return client


@pytest.mark.asyncio
async def test_search_returns_points_and_filters_active_by_default():
    points = [SimpleNamespace(payload={"job_id": "greenhouse_1"})]
    client = _client(points)

    result = await qdrant_store.search([0.1] * 384, limit=10, client=client)

    assert result == points
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["limit"] == 10
    # Default active_only=True -> one filter condition (is_active).
    assert len(kwargs["query_filter"].must) == 1


@pytest.mark.asyncio
async def test_search_no_filter_when_unfiltered():
    client = _client([])
    await qdrant_store.search(
        [0.1] * 384, limit=5, active_only=False, client=client
    )
    assert client.query_points.await_args.kwargs["query_filter"] is None


@pytest.mark.asyncio
async def test_search_adds_seniority_and_role_filters():
    client = _client([])
    await qdrant_store.search(
        [0.1] * 384,
        limit=5,
        seniority="senior",
        role_cluster="backend",
        client=client,
    )
    # is_active + seniority + role_cluster = 3 conditions.
    assert len(client.query_points.await_args.kwargs["query_filter"].must) == 3
