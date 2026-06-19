"""Normalize raw ATS payloads into validated ``JobPosting`` models.

Responsibilities here: HTML cleaning, title cleaning, SWE include/exclude filtering,
remote/employment-type/posted-at parsing, and building the ``JobPosting`` (with its
mandatory ``{source}_{external_id}`` id). Seniority, role cluster, and skill extraction
are *classification* concerns handled in Step 4 (``classify.py``); normalize leaves those
at their model defaults (UNKNOWN / None / []).
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from app.ingestion.registry import BoardConfig
from app.models import Company, EmploymentType, JobPosting, JobSource

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Title keywords that mark a software-engineering role.
_SWE_INCLUDE = (
    "software engineer",
    "software developer",
    "swe",
    "backend engineer",
    "back end engineer",
    "back-end engineer",
    "frontend engineer",
    "front end engineer",
    "front-end engineer",
    "full stack",
    "full-stack",
    "fullstack",
    "platform engineer",
    "infrastructure engineer",
    "systems engineer",
    "distributed systems",
    "machine learning engineer",
    "ml engineer",
    "data engineer",
    "mobile engineer",
    "ios engineer",
    "android engineer",
    "site reliability",
    "devops engineer",
    "security engineer",
)
# Hard exclusions even if a title otherwise looks engineering-ish.
_SWE_EXCLUDE = (
    "sales engineer",
    "solutions engineer",
    "support engineer",
    "engineering manager",
    "recruiter",
    "designer",
    "account executive",
    "customer",
    "marketing",
)


def clean_html(raw: str | None) -> str:
    """Unescape HTML entities and strip tags, returning collapsed plain text."""

    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)  # entities sometimes survive a layer of escaping
    return _WS_RE.sub(" ", text).strip()


def clean_title(raw: str) -> str:
    """Collapse whitespace and trim a trailing parenthetical location from a title."""

    title = _WS_RE.sub(" ", raw).strip()
    # Drop a single trailing "(Location)" segment, e.g. "... Engineer (Austin)".
    title = re.sub(r"\s*\([^()]*\)\s*$", "", title).strip()
    return title or raw.strip()


def is_swe(title: str) -> bool:
    """Heuristic: does this title look like a software-engineering role?"""

    low = title.lower()
    if any(bad in low for bad in _SWE_EXCLUDE):
        return False
    return any(good in low for good in _SWE_INCLUDE)


def _employment_type(title: str, commitment: str | None) -> EmploymentType:
    low = f"{title} {commitment or ''}".lower()
    if "intern" in low:
        return EmploymentType.INTERNSHIP
    if "contract" in low or "contractor" in low:
        return EmploymentType.CONTRACT
    if "part time" in low or "part-time" in low:
        return EmploymentType.PART_TIME
    return EmploymentType.FULL_TIME


def company_from_board(board: BoardConfig) -> Company:
    """Build the ``Company`` for a board (thin metadata; enrich later)."""

    return Company(id=board.company_id, name=board.name)


def normalize_greenhouse(raw: dict, board: BoardConfig) -> JobPosting:
    """Map a raw Greenhouse job dict to a ``JobPosting``."""

    external_id = str(raw["id"])
    title = clean_title(raw.get("title", ""))
    location = (raw.get("location") or {}).get("name")
    posted = raw.get("first_published") or raw.get("updated_at")
    posted_at = (
        datetime.fromisoformat(posted)
        if posted
        else datetime.now(timezone.utc)
    )
    description_raw = html.unescape(raw.get("content") or "")
    is_remote = bool(location) and any(
        kw in location.lower() for kw in ("remote", "distributed")
    )
    return JobPosting(
        id=f"{JobSource.GREENHOUSE.value}_{external_id}",
        source=JobSource.GREENHOUSE,
        external_id=external_id,
        url=raw["absolute_url"],
        title=title,
        company=company_from_board(board),
        location=location,
        is_remote=is_remote,
        employment_type=_employment_type(title, None),
        description_raw=description_raw,
        description_cleaned=clean_html(description_raw),
        posted_at=posted_at,
    )


def normalize_lever(raw: dict, board: BoardConfig) -> JobPosting:
    """Map a raw Lever posting dict to a ``JobPosting``."""

    external_id = str(raw["id"])
    title = clean_title(raw.get("text", ""))
    categories = raw.get("categories") or {}
    location = categories.get("location")
    created_ms = raw.get("createdAt")
    posted_at = (
        datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
        if created_ms
        else datetime.now(timezone.utc)
    )
    description_raw = raw.get("description") or raw.get("descriptionPlain") or ""
    description_cleaned = (
        raw.get("descriptionPlain")
        and _WS_RE.sub(" ", raw["descriptionPlain"]).strip()
    ) or clean_html(description_raw)
    return JobPosting(
        id=f"{JobSource.LEVER.value}_{external_id}",
        source=JobSource.LEVER,
        external_id=external_id,
        url=raw["hostedUrl"],
        title=title,
        company=company_from_board(board),
        location=location,
        is_remote=(raw.get("workplaceType") or "").lower() == "remote",
        employment_type=_employment_type(title, categories.get("commitment")),
        description_raw=description_raw,
        description_cleaned=description_cleaned,
        posted_at=posted_at,
    )


def normalize(raw: dict, board: BoardConfig) -> JobPosting:
    """Dispatch to the source-specific normalizer."""

    if board.source is JobSource.GREENHOUSE:
        return normalize_greenhouse(raw, board)
    return normalize_lever(raw, board)
