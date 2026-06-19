"""Curated company -> ATS board registry.

Board tokens are verified against the live public APIs (see ``discovery.py``). The list
mixes the reachable subset of the target 50 with other well-known Greenhouse/Lever SWE
employers so the pipeline can reach ~500 active SWE postings.

This is static reference data, not environment config, so it lives here rather than in
``app.config``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import JobSource


@dataclass(frozen=True)
class BoardConfig:
    """One company's job board on a given ATS."""

    name: str
    source: JobSource
    token: str  # board slug used in the ATS API URL

    @property
    def company_id(self) -> str:
        return f"{self.source.value}_{self.token}"


# Verified live (HTTP 200 with postings) at build time.
REGISTRY: list[BoardConfig] = [
    # --- Greenhouse ---
    BoardConfig("Stripe", JobSource.GREENHOUSE, "stripe"),
    BoardConfig("Databricks", JobSource.GREENHOUSE, "databricks"),
    BoardConfig("Airbnb", JobSource.GREENHOUSE, "airbnb"),
    BoardConfig("Cloudflare", JobSource.GREENHOUSE, "cloudflare"),
    BoardConfig("Figma", JobSource.GREENHOUSE, "figma"),
    BoardConfig("Anthropic", JobSource.GREENHOUSE, "anthropic"),
    BoardConfig("GitLab", JobSource.GREENHOUSE, "gitlab"),
    BoardConfig("Coinbase", JobSource.GREENHOUSE, "coinbase"),
    BoardConfig("Reddit", JobSource.GREENHOUSE, "reddit"),
    BoardConfig("Brex", JobSource.GREENHOUSE, "brex"),
    BoardConfig("Robinhood", JobSource.GREENHOUSE, "robinhood"),
    BoardConfig("Dropbox", JobSource.GREENHOUSE, "dropbox"),
    # --- Lever ---
    BoardConfig("Spotify", JobSource.LEVER, "spotify"),
    BoardConfig("Mistral AI", JobSource.LEVER, "mistral"),
]


def get_registry() -> list[BoardConfig]:
    """Return the curated board registry."""

    return REGISTRY
