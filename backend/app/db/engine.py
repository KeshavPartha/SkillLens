"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _is_pgbouncer(url: str) -> bool:
    """Detect a Supabase/pgbouncer transaction pooler endpoint."""

    return "pooler.supabase.com" in url or ":6543" in url


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""

    global _engine
    if _engine is None:
        settings = get_settings().database
        url = settings.async_url
        if _is_pgbouncer(url):
            # Transaction pooler can't reuse cached/named prepared statements:
            # disable asyncpg's statement cache, give each statement a unique
            # name, and don't add our own pool on top of pgbouncer.
            _engine = create_async_engine(
                url,
                echo=settings.echo,
                poolclass=NullPool,
                connect_args={
                    "statement_cache_size": 0,
                    "prepared_statement_name_func": lambda: f"__sl_{uuid.uuid4()}__",
                },
            )
        else:
            _engine = create_async_engine(
                url,
                echo=settings.echo,
                pool_size=settings.pool_size,
                max_overflow=settings.max_overflow,
            )
    return _engine


def create_migration_engine() -> AsyncEngine:
    """Build a throwaway engine for alembic against the migration DSN.

    Uses the direct/session-mode connection (port 5432 on Supabase) which supports
    prepared statements, with NullPool so no connections linger after migrating.
    """

    settings = get_settings().database
    return create_async_engine(
        settings.async_migration_url,
        echo=settings.echo,
        poolclass=NullPool,
    )


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async session factory."""

    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional async session scope."""

    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
