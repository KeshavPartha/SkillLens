"""Server-Sent Events framing helpers.

Every streamed agent step must use ``AgentTrace.to_sse_payload(step)`` for its data
shape (the ``{run_id, step, running_cost_usd}`` contract the frontend expects); these
helpers only handle the wire framing around that payload.
"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(data: dict[str, Any], event: str | None = None) -> str:
    """Format one SSE frame. ``event`` names a custom event type (e.g. ``profile``)."""

    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n"
