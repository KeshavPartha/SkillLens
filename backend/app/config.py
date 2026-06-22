"""Application settings.

All configuration is loaded here via ``pydantic-settings`` ``BaseSettings`` classes.
Nothing in the codebase should read ``os.environ`` / ``os.getenv`` directly — import
``get_settings()`` instead.

Env var names map to the existing ``.env`` (bare names like ``ANTHROPIC_API_KEY``,
``SUPABASE_DB_URL``, ``QDRANT_URL``). Settings that ``.env`` does not yet define carry
sensible defaults below.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = ".env"


class DatabaseSettings(BaseSettings):
    """Postgres (Supabase) connection settings."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/skilllens",
        validation_alias="SUPABASE_DB_URL",
    )
    # Optional direct/session-mode DSN for migrations. Supabase's transaction
    # pooler (port 6543) can't run alembic/ORM prepared statements, so migrations
    # use this instead. Defaults to deriving the session pooler from ``url``.
    migration_url: str | None = Field(
        default=None, validation_alias="SUPABASE_DB_DIRECT_URL"
    )
    pool_size: int = 10
    max_overflow: int = 5
    echo: bool = False

    @staticmethod
    def _to_asyncpg(url: str) -> str:
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @staticmethod
    def _prefer_session_pooler(url: str) -> str:
        """Route Supabase's transaction pooler (6543) to its session pooler (5432).

        The transaction pooler can't serve this ORM/migration workload (no cached
        prepared statements, inconsistent read-after-write); the session pooler can.
        """

        if "pooler.supabase.com" in url and ":6543/" in url:
            return url.replace(":6543/", ":5432/")
        return url

    @property
    def async_url(self) -> str:
        """Runtime DSN with the asyncpg driver (session pooler for Supabase)."""

        return self._prefer_session_pooler(self._to_asyncpg(self.url))

    @property
    def async_migration_url(self) -> str:
        """DSN used for alembic migrations.

        Uses ``SUPABASE_DB_DIRECT_URL`` when set; otherwise the same session-pooler
        DSN as the runtime connection.
        """

        if self.migration_url:
            return self._prefer_session_pooler(self._to_asyncpg(self.migration_url))
        return self.async_url


class QdrantSettings(BaseSettings):
    """Vector store settings. Defaults match all-MiniLM-L6-v2 (384-dim, cosine)."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    url: str = Field(default="http://localhost:6333", validation_alias="QDRANT_URL")
    api_key: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    collection_name: str = "job_postings"
    vector_size: int = 384
    distance: str = "Cosine"


class EmbeddingSettings(BaseSettings):
    """Local sentence-transformers embedding settings."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 64
    device: str = "cpu"
    normalize: bool = True


class LLMSettings(BaseSettings):
    """LLM provider settings. API keys use the bare env names in ``.env``."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    anthropic_api_key: str | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY"
    )
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    max_run_cost_usd: float = 0.50
    request_timeout_seconds: int = 60


class IngestionSettings(BaseSettings):
    """Job ingestion pipeline tuning."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    target_active_postings: int = 500
    swe_only: bool = True
    http_timeout: int = 30
    company_concurrency: int = 5
    classify_low_confidence_with_llm: bool = True


class Settings(BaseSettings):
    """Root settings aggregating every sub-config."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""

    return Settings()
