"""Database layer: async engine, ORM tables, and idempotent repositories."""

from app.db.engine import get_engine, get_sessionmaker, session_scope
from app.db.models import Base, CompanyRow, JobPostingRow
from app.db.repository import (
    content_hash,
    mark_inactive,
    upsert_company,
    upsert_posting,
)

__all__ = [
    "Base",
    "CompanyRow",
    "JobPostingRow",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "content_hash",
    "mark_inactive",
    "upsert_company",
    "upsert_posting",
]
