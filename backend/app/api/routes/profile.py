"""Resume parsing endpoint.

``POST /profile/parse`` streams the profile agent's live trace over Server-Sent
Events, then a terminal ``profile`` (or ``error``) frame. This is the seed of the
streaming-trace UI differentiator.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.agents import ProfileExtractionError, extract_profile
from app.api.sse import sse_frame
from app.config import get_settings
from app.llm import RunCostExceeded, get_router
from app.models import AgentTrace, CandidateProfile

router = APIRouter()


async def _stream_extraction(
    pdf_bytes: bytes,
    *,
    target_role: str,
    target_seniority: str | None,
    run_id: str,
) -> AsyncIterator[str]:
    """Yield SSE frames: one per trace step, then a terminal profile/error frame."""

    trace = AgentTrace(run_id=run_id)
    # Trace steps (dicts) and the terminal result (a tuple) share one FIFO queue, so
    # step frames are emitted in order before the terminal frame.
    queue: asyncio.Queue = asyncio.Queue()
    trace.listener = lambda step: queue.put_nowait(trace.to_sse_payload(step))

    async def runner() -> None:
        try:
            profile = await extract_profile(
                pdf_bytes,
                target_role=target_role,
                target_seniority=target_seniority,
                run_id=run_id,
                trace=trace,
                router=get_router(),
            )
            queue.put_nowait(("done", profile))
        except (ProfileExtractionError, RunCostExceeded) as exc:
            queue.put_nowait(("error", str(exc)))

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if isinstance(item, dict):  # a per-step SSE payload
                yield sse_frame(item)
                continue
            kind, value = item
            if kind == "done":
                profile: CandidateProfile = value
                yield sse_frame(
                    {
                        "run_id": run_id,
                        "profile": profile.model_dump(mode="json"),
                        "running_cost_usd": trace.total_cost_usd,
                    },
                    event="profile",
                )
            else:
                yield sse_frame(
                    {"run_id": run_id, "error": value, "running_cost_usd": trace.total_cost_usd},
                    event="error",
                )
            break
    finally:
        await task


@router.post("/profile/parse")
async def parse_profile(
    file: Annotated[UploadFile, File()],
    target_role: Annotated[str, Form()],
    target_seniority: Annotated[str | None, Form()] = None,
) -> StreamingResponse:
    """Parse an uploaded resume PDF into a CandidateProfile, streaming the trace."""

    settings = get_settings()
    pdf_bytes = await file.read()
    run_id = str(uuid4())

    async def generate() -> AsyncIterator[str]:
        if len(pdf_bytes) > settings.api.max_upload_bytes:
            yield sse_frame(
                {"run_id": run_id, "error": "uploaded file exceeds the size limit"},
                event="error",
            )
            return
        async for frame in _stream_extraction(
            pdf_bytes,
            target_role=target_role,
            target_seniority=target_seniority,
            run_id=run_id,
        ):
            yield frame

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
