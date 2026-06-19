"""Shared async HTTP helper with a small retry/backoff (no extra deps)."""

from __future__ import annotations

import asyncio

import httpx


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
) -> object:
    """GET ``url`` and return parsed JSON, retrying transient failures.

    Raises ``httpx.HTTPStatusError`` on a non-retryable 4xx (other than 429).
    """

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.get(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"retryable status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (2**attempt))
    assert last_exc is not None
    raise last_exc
