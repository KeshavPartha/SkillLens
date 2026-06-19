"""Greenhouse public board API client.

Endpoint: ``GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true``
returns every posting with full (HTML-entity-escaped) ``content`` in a single call.
"""

from __future__ import annotations

import httpx

from app.ingestion.ats._http import get_json

_BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


async def fetch_greenhouse(
    client: httpx.AsyncClient, token: str
) -> list[dict]:
    """Return the raw Greenhouse job dicts for a board token."""

    data = await get_json(client, _BASE.format(token=token))
    if isinstance(data, dict):
        jobs = data.get("jobs", [])
    else:
        jobs = data
    return [j for j in jobs if isinstance(j, dict)]
