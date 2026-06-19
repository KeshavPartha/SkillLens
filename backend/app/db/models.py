"""SQLAlchemy ORM tables for persisted job-posting metadata.

These mirror the ``JobPosting`` / ``Company`` Pydantic models in ``app.models.job`` —
the Pydantic models remain the source of truth passed between agents; these tables are
only the persistence layer. The ``job_postings.id`` primary key is the
``"{source}_{external_id}"`` value enforced by ``JobPosting``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class CompanyRow(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    size_range: Mapped[str | None] = mapped_column(String, nullable=True)
    hq_location: Mapped[str | None] = mapped_column(String, nullable=True)

    postings: Mapped[list[JobPostingRow]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class JobPostingRow(Base):
    __tablename__ = "job_postings"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # {source}_{external_id}
    source: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )

    location: Mapped[str | None] = mapped_column(String, nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    employment_type: Mapped[str] = mapped_column(String, nullable=False)
    seniority: Mapped[str] = mapped_column(String, nullable=False)

    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    description_cleaned: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role_cluster: Mapped[str | None] = mapped_column(String, nullable=True)

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")

    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    embedding_id: Mapped[str | None] = mapped_column(String, nullable=True)
    required_skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    company: Mapped[CompanyRow] = relationship(back_populates="postings")

    __table_args__ = (
        Index("ix_job_postings_company_id", "company_id"),
        Index("ix_job_postings_source", "source"),
        Index("ix_job_postings_role_cluster", "role_cluster"),
        Index("ix_job_postings_seniority", "seniority"),
        Index("ix_job_postings_is_active", "is_active"),
    )
