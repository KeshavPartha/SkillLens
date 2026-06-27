"""FastAPI application entry point (``app.api.main:app``)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import profile
from app.config import get_settings

app = FastAPI(title="SkillLens API")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router, tags=["profile"])


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""

    return {"status": "ok"}
