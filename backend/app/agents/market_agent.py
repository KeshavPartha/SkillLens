"""Market agent: candidate profile -> top-k relevant postings + skill demand.

Hybrid retrieval over Qdrant: a semantic (vector) ranking and a keyword (skill/title
overlap) ranking are fused with Reciprocal Rank Fusion, then the surviving postings are
hydrated from Postgres and their required skills aggregated. Embeddings are local (same
MiniLM model as ingestion); no LLM call is made here, so this stage adds no run cost.
"""

from __future__ import annotations

import re
from collections import Counter

from app.db.engine import session_scope
from app.db.repository import get_postings_by_ids
from app.ingestion import qdrant_store
from app.ingestion.embed import embed_texts
from app.models import (
    AgentTrace,
    CandidateProfile,
    JobPosting,
    MarketResult,
    ScoredPosting,
    SkillDemand,
    StepType,
    TraceStep,
)

AGENT_NAME = "market_agent"

_TOKEN_RE = re.compile(r"[^a-z0-9+#]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase token set, keeping ``+``/``#`` so c++ / c# survive."""

    return {t for t in _TOKEN_RE.split(text.lower()) if len(t) > 1}


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60
) -> dict[str, float]:
    """Fuse several ranked id lists into one ``{id: score}`` map via RRF.

    Each list contributes ``1 / (k + rank)`` (1-based rank) for every id it ranks.
    """

    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def aggregate_skill_demand(postings: list[JobPosting]) -> list[SkillDemand]:
    """Tally required-skill prevalence across postings, most-demanded first."""

    total = len(postings)
    if total == 0:
        return []
    counts: Counter[str] = Counter()
    for posting in postings:
        # required_skill_names is a set, so each skill counts once per posting.
        counts.update(posting.required_skill_names)
    demands = [
        SkillDemand(skill_name=name, posting_count=count, prevalence=count / total)
        for name, count in counts.items()
    ]
    demands.sort(key=lambda d: (-d.posting_count, d.skill_name))
    return demands


def _build_query_text(profile: CandidateProfile) -> str:
    """Compose the text embedded for semantic retrieval."""

    parts = [profile.target_role]
    if profile.target_seniority:
        parts.append(profile.target_seniority)
    top_skills = [s.canonical_name or s.name for s in profile.skills[:10]]
    if top_skills:
        parts.append(", ".join(top_skills))
    return " ".join(parts)


def _query_tokens(profile: CandidateProfile) -> set[str]:
    tokens = _tokenize(profile.target_role)
    for skill in profile.skills:
        tokens |= _tokenize(skill.canonical_name or skill.name)
    return tokens


def _keyword_score(tokens: set[str], payload: dict) -> int:
    """Overlap between the candidate's tokens and a posting's title/cluster/skills."""

    haystack: set[str] = set()
    haystack |= _tokenize(payload.get("title") or "")
    haystack |= _tokenize(payload.get("role_cluster") or "")
    for skill in payload.get("required_skills") or []:
        haystack |= _tokenize(skill)
    return len(tokens & haystack)


async def _fetch_postings(ids: list[str]) -> dict[str, JobPosting]:
    if not ids:
        return {}
    async with session_scope() as session:
        return await get_postings_by_ids(session, ids)


async def query_market(
    profile: CandidateProfile,
    *,
    top_k: int = 20,
    pool_size: int = 50,
    run_id: str,
    trace: AgentTrace,
) -> MarketResult:
    """Retrieve the top-k postings for the profile's target role via hybrid RAG."""

    trace.append_step(
        TraceStep(
            step_type=StepType.MARKET_QUERY,
            agent_name=AGENT_NAME,
            message=f"Querying market for {profile.target_role}",
        )
    )

    vectors = await embed_texts([_build_query_text(profile)])
    hits = await qdrant_store.search(vectors[0], limit=pool_size)

    # Two rankings over the same candidate pool: semantic order, and keyword overlap.
    vector_ranking = [h.payload["job_id"] for h in hits]
    tokens = _query_tokens(profile)
    keyword_ranking = [
        h.payload["job_id"]
        for h in sorted(hits, key=lambda h: _keyword_score(tokens, h.payload), reverse=True)
    ]

    fused = reciprocal_rank_fusion([vector_ranking, keyword_ranking])
    ranked_ids = [
        pid for pid, _ in sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:top_k]

    postings_by_id = await _fetch_postings(ranked_ids)
    max_score = max(fused.values()) if fused else 1.0
    scored = [
        ScoredPosting(
            posting=postings_by_id[pid], relevance_score=fused[pid] / max_score
        )
        for pid in ranked_ids
        if pid in postings_by_id  # tolerate Qdrant/Postgres drift
    ]

    trace.append_step(
        TraceStep(
            step_type=StepType.MARKET_RESULTS,
            agent_name=AGENT_NAME,
            message=f"Retrieved {len(scored)} postings for {profile.target_role}",
            payload={"posting_count": len(scored), "pool_size": len(hits)},
        )
    )

    skill_demand = aggregate_skill_demand([sp.posting for sp in scored])
    trace.append_step(
        TraceStep(
            step_type=StepType.SKILL_AGGREGATION,
            agent_name=AGENT_NAME,
            message=f"Aggregated demand across {len(skill_demand)} skills",
            payload={"skill_count": len(skill_demand)},
        )
    )

    return MarketResult(
        target_role=profile.target_role, postings=scored, skill_demand=skill_demand
    )
