"""Tests for raw ATS payload -> JobPosting normalization."""

from app.ingestion.normalize import (
    clean_html,
    clean_title,
    is_swe,
    normalize_greenhouse,
    normalize_lever,
)
from app.ingestion.registry import BoardConfig
from app.models import EmploymentType, JobSource

GH_BOARD = BoardConfig("Cloudflare", JobSource.GREENHOUSE, "cloudflare")
LV_BOARD = BoardConfig("Spotify", JobSource.LEVER, "spotify")


def _gh_raw(**overrides) -> dict:
    base = dict(
        id=7462799,
        title="Distributed Systems Engineer (Austin)",
        location={"name": "Remote US"},
        first_published="2026-06-12T11:47:29-04:00",
        updated_at="2026-06-16T17:34:32-04:00",
        absolute_url="https://boards.greenhouse.io/cloudflare/jobs/7462799",
        content="&lt;div&gt;&lt;strong&gt;Build&lt;/strong&gt; systems&lt;/div&gt;",
    )
    base.update(overrides)
    return base


def _lv_raw(**overrides) -> dict:
    base = dict(
        id="e8ef80ed-633f",
        text="Backend Engineer - Platform",
        categories={"location": "Toronto", "commitment": "Full-time"},
        createdAt=1741185010328,
        workplaceType="remote",
        hostedUrl="https://jobs.lever.co/spotify/e8ef80ed-633f",
        description="<p>Build the platform</p>",
        descriptionPlain="Build the platform",
    )
    base.update(overrides)
    return base


# ---- helpers ----

def test_clean_html_unescapes_and_strips_tags():
    assert clean_html("&lt;div&gt;Hello &amp; bye&lt;/div&gt;") == "Hello & bye"


def test_clean_html_empty():
    assert clean_html(None) == ""
    assert clean_html("") == ""


def test_clean_title_trims_trailing_paren_location():
    assert clean_title("Software Engineer (Austin)") == "Software Engineer"
    assert clean_title("  Senior   SWE  ") == "Senior SWE"


def test_is_swe_includes_and_excludes():
    assert is_swe("Senior Software Engineer")
    assert is_swe("Distributed Systems Engineer")
    assert not is_swe("Sales Engineer")
    assert not is_swe("Engineering Manager")
    assert not is_swe("Product Designer")


# ---- greenhouse ----

def test_normalize_greenhouse_builds_valid_posting():
    p = normalize_greenhouse(_gh_raw(), GH_BOARD)
    assert p.id == "greenhouse_7462799"
    assert p.source is JobSource.GREENHOUSE
    assert p.external_id == "7462799"
    assert p.title == "Distributed Systems Engineer"  # paren location trimmed
    assert p.company.id == "greenhouse_cloudflare"
    assert p.is_remote is True  # "Remote US"
    assert p.description_cleaned == "Build systems"
    assert p.posted_at.year == 2026


def test_normalize_greenhouse_intern_employment_type():
    p = normalize_greenhouse(_gh_raw(title="Software Engineer Intern"), GH_BOARD)
    assert p.employment_type is EmploymentType.INTERNSHIP


# ---- lever ----

def test_normalize_lever_builds_valid_posting():
    p = normalize_lever(_lv_raw(), LV_BOARD)
    assert p.id == "lever_e8ef80ed-633f"
    assert p.source is JobSource.LEVER
    assert p.title == "Backend Engineer - Platform"
    assert p.location == "Toronto"
    assert p.is_remote is True
    assert p.employment_type is EmploymentType.FULL_TIME
    assert p.description_cleaned == "Build the platform"
    assert p.posted_at.tzinfo is not None
