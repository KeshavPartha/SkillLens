"""Classify postings: seniority, role cluster, and required skills.

Heuristics (deterministic, free, instant) do the bulk of the work. When the role cluster
can't be determined confidently from keywords, an optional Groq/Llama tail classifies it
via the LLM router (metered, free-tier, $0.50-capped). Skill and seniority inference are
heuristic-only.
"""

from __future__ import annotations

import re

from app.llm import LLMMessage, LLMRouter, ModelTask
from app.models import JobPosting, RequiredSkill, SeniorityLevel

# Canonical role clusters the system recognizes.
ROLE_CLUSTERS = (
    "ml-engineer",
    "data-engineer",
    "frontend",
    "backend",
    "fullstack",
    "mobile",
    "infrastructure",
    "security",
    "distributed-systems",
    "software-engineer",  # generic fallback
)

# Seniority keyword -> level, checked in priority order (most specific first).
_SENIORITY_RULES: tuple[tuple[str, SeniorityLevel], ...] = (
    ("intern", SeniorityLevel.INTERN),
    ("principal", SeniorityLevel.PRINCIPAL),
    ("distinguished", SeniorityLevel.PRINCIPAL),
    ("fellow", SeniorityLevel.PRINCIPAL),
    ("staff", SeniorityLevel.STAFF),
    ("vp", SeniorityLevel.VP),
    ("vice president", SeniorityLevel.VP),
    ("director", SeniorityLevel.DIRECTOR),
    ("manager", SeniorityLevel.MANAGER),
    ("lead", SeniorityLevel.LEAD),
    ("senior", SeniorityLevel.SENIOR),
    ("sr.", SeniorityLevel.SENIOR),
    ("sr ", SeniorityLevel.SENIOR),
    ("junior", SeniorityLevel.JUNIOR),
    ("jr.", SeniorityLevel.JUNIOR),
    ("new grad", SeniorityLevel.JUNIOR),
    ("graduate", SeniorityLevel.JUNIOR),
    ("entry level", SeniorityLevel.JUNIOR),
    ("entry-level", SeniorityLevel.JUNIOR),
)

# Role cluster keyword -> cluster, checked in priority order.
_ROLE_RULES: tuple[tuple[str, str], ...] = (
    ("machine learning", "ml-engineer"),
    ("ml engineer", "ml-engineer"),
    ("ai engineer", "ml-engineer"),
    ("data engineer", "data-engineer"),
    ("data platform", "data-engineer"),
    ("distributed systems", "distributed-systems"),
    ("full stack", "fullstack"),
    ("full-stack", "fullstack"),
    ("fullstack", "fullstack"),
    ("front end", "frontend"),
    ("front-end", "frontend"),
    ("frontend", "frontend"),
    ("ios", "mobile"),
    ("android", "mobile"),
    ("mobile", "mobile"),
    ("site reliability", "infrastructure"),
    ("devops", "infrastructure"),
    ("infrastructure", "infrastructure"),
    ("platform engineer", "infrastructure"),
    ("security", "security"),
    ("backend", "backend"),
    ("back end", "backend"),
    ("back-end", "backend"),
    ("server", "backend"),
)

# Skill keyword (regex-safe substring) -> canonical skill name.
_SKILL_KEYWORDS: dict[str, str] = {
    "python": "python",
    "java ": "java",
    "javascript": "javascript",
    "typescript": "typescript",
    "golang": "go",
    " go ": "go",
    "rust": "rust",
    "c++": "c++",
    "c#": "c#",
    "ruby": "ruby",
    "scala": "scala",
    "kotlin": "kotlin",
    "swift": "swift",
    "react": "react",
    "node.js": "node.js",
    "nodejs": "node.js",
    "kubernetes": "kubernetes",
    "docker": "docker",
    "terraform": "terraform",
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "kafka": "kafka",
    "spark": "spark",
    "graphql": "graphql",
    "grpc": "grpc",
    "redis": "redis",
    "tensorflow": "tensorflow",
    "pytorch": "pytorch",
}


def classify_seniority(title: str) -> SeniorityLevel:
    """Infer seniority from the title; default MID for an unmarked engineer role."""

    low = f" {title.lower()} "
    for keyword, level in _SENIORITY_RULES:
        if keyword in low:
            return level
    return SeniorityLevel.MID


def classify_role_cluster(title: str, description: str) -> tuple[str | None, bool]:
    """Return ``(cluster, high_confidence)``.

    Title matches are high confidence; description-only matches are lower; no match at all
    returns ``(None, False)`` so the caller can fall back to the LLM tail.
    """

    title_low = title.lower()
    for keyword, cluster in _ROLE_RULES:
        if keyword in title_low:
            return cluster, True
    desc_low = description.lower()
    for keyword, cluster in _ROLE_RULES:
        if keyword in desc_low:
            return cluster, False
    return None, False


def extract_skills(text: str) -> list[RequiredSkill]:
    """Extract a deduplicated list of required skills from posting text."""

    low = f" {text.lower()} "
    found: list[str] = []
    seen: set[str] = set()
    for keyword, canonical in _SKILL_KEYWORDS.items():
        if keyword in low and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return [RequiredSkill(name=name) for name in found]


_VALID_CLUSTER_RE = re.compile("|".join(re.escape(c) for c in ROLE_CLUSTERS))


async def _classify_cluster_llm(
    posting: JobPosting, router: LLMRouter, run_id: str
) -> str:
    """Ask Llama to pick a role cluster when heuristics are inconclusive."""

    options = ", ".join(ROLE_CLUSTERS)
    resp = await router.complete(
        task=ModelTask.CLASSIFICATION,
        run_id=run_id,
        max_tokens=12,
        messages=[
            LLMMessage(
                role="system",
                content=(
                    "You classify software job titles into exactly one role cluster. "
                    f"Reply with ONE of: {options}. Reply with only the cluster."
                ),
            ),
            LLMMessage(
                role="user",
                content=f"Title: {posting.title}\n{posting.description_cleaned[:400]}",
            ),
        ],
    )
    match = _VALID_CLUSTER_RE.search(resp.content.lower())
    return match.group(0) if match else "software-engineer"


async def enrich_posting(
    posting: JobPosting,
    *,
    router: LLMRouter | None = None,
    run_id: str = "ingestion",
    use_llm: bool = True,
) -> JobPosting:
    """Return a copy of ``posting`` with seniority, role cluster, and skills filled."""

    seniority = classify_seniority(posting.title)
    cluster = classify_role_cluster(posting.title, posting.description_cleaned)[0]
    if cluster is None:
        if use_llm and router is not None:
            cluster = await _classify_cluster_llm(posting, router, run_id)
        else:
            cluster = "software-engineer"
    skills = extract_skills(posting.description_cleaned)
    return posting.model_copy(
        update={
            "seniority": seniority,
            "role_cluster": cluster,
            "required_skills": skills,
        }
    )
