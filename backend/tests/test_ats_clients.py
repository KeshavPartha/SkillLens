"""Tests for the Greenhouse/Lever async clients using httpx MockTransport."""

import httpx

from app.ingestion.ats import fetch_greenhouse, fetch_lever


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_greenhouse_returns_job_dicts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "boards/acme/jobs" in str(request.url)
        return httpx.Response(
            200, json={"jobs": [{"id": 1, "title": "SWE"}, {"id": 2, "title": "SRE"}]}
        )

    async with _client(handler) as c:
        jobs = await fetch_greenhouse(c, "acme")
    assert [j["id"] for j in jobs] == [1, 2]


async def test_fetch_lever_returns_posting_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "postings/acme" in str(request.url)
        return httpx.Response(200, json=[{"id": "a", "text": "SWE"}])

    async with _client(handler) as c:
        postings = await fetch_lever(c, "acme")
    assert postings[0]["text"] == "SWE"


async def test_fetch_retries_then_succeeds_on_500():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"jobs": [{"id": 9}]})

    async with _client(handler) as c:
        jobs = await fetch_greenhouse(c, "acme")
    assert calls["n"] == 2
    assert jobs[0]["id"] == 9
