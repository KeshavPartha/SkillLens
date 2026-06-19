"""Lever public postings API client.

Endpoint: ``GET https://api.lever.co/v0/postings/{token}?mode=json`` returns a flat list
of postings, each with a plain-text ``descriptionPlain`` and HTML ``description``.
"""

from __future__ import annotations

import httpx

from app.ingestion.ats._http import get_json

_BASE = "https://api.lever.co/v0/postings/{token}?mode=json"


async def fetch_lever(client: httpx.AsyncClient, token: str) -> list[dict]:
    """Return the raw Lever posting dicts for a board token."""

    data = await get_json(client, _BASE.format(token=token))
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]
