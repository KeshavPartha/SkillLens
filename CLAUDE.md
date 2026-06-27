# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What SkillLens is

A multi-agent AI system that analyzes resumes against real job-market data, identifies skill gaps,
and generates evidence-backed career roadmaps. Python/FastAPI backend with a LangGraph agent
pipeline; Next.js frontend that renders a live agent activity feed over Server-Sent Events.

This is a **prospective career planner**, not a resume-to-job matcher. Every design decision
should serve that distinction.

## Current state

See `git log` for current build state — this file describes invariants and conventions, not
progress. The `backend/app/models/` Pydantic data models are the source of truth for every agent;
build all new functionality against them.

## Commands

The backend uses `uv` and a checked-in virtualenv at `backend/.venv`. Run all backend commands
from the `backend/` directory.

```bash
# Install / sync dependencies (including dev group)
uv sync

# Run the full test suite
.venv/bin/python -m pytest

# Run one test file / one test
.venv/bin/python -m pytest tests/test_models.py
.venv/bin/python -m pytest tests/test_models.py::test_plan_gap_counts

# Lint
.venv/bin/ruff check .

# Start infrastructure (Postgres, Qdrant, Redis) — from repo root
docker-compose up -d

# Start backend
uv run uvicorn app.api.main:app --reload --port 8000
```

Frontend (from `frontend/`, uses pnpm):

```bash
pnpm dev      # next dev
pnpm build
pnpm lint
```

Copy `.env.example` to `.env` and fill in keys before running anything that touches external
services.

## Git workflow

- Commit after every coherent unit of work: new model, new endpoint, passing test suite, etc.
- Commit message format: `type(scope): description`
  - Examples: `feat(models): add CareerPlan validators`, `fix(api): correct SSE content-type header`
  - Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
- **Never push without explicit user confirmation.** Always show the proposed commit message and a
  summary of changed files, then ask "OK to push?"
- Never force-push to `main`.

## Architecture

### The agent pipeline

The intended flow is encoded in `backend/app/models/trace.py` `StepType`, which is the canonical
ordering of pipeline stages:

`resume_parsing` → `profile_extracted` → `market_query` → `market_results` → `skill_aggregation`
→ `gap_analysis_start` / `gap_identified` / `gap_analysis_done` → `plan_draft` →
`critique_start` / `critique_challenge` / `plan_revision` (up to 2 rounds) → `plan_final`.

This maps to the data models, each owned by a stage:

- **`profile.py` — `CandidateProfile`**: extracted from the uploaded resume. Carries `target_role`
  (user-supplied at upload) and `raw_resume_text` (server-only, `exclude=True`).
- **`job.py` — `JobPosting`**: fetched from ATS sources (Greenhouse, Lever) during the market
  query, normalized and embedded. `id` must be `"{source}_{external_id}"`.
- **`gap.py` — `SkillGap`**: the core analysis unit. Every gap requires ≥1 `PostingEvidence`
  (enforced at the model level, not in agent code) — the system never asserts a gap without a real
  JD excerpt to back it.
- **`plan.py` — `CareerPlan`**: the deliverable. Wraps the gaps plus 1–12 `WeeklyMilestone`s;
  gap counts and milestone sequencing are validated/computed by the model.

### Agents

Agents live in `app/agents/`, one module per pipeline stage. Each takes a live `AgentTrace`,
appends `TraceStep`s as it works (the terminal step of any LLM-backed stage carries
`cost_usd` / `input_tokens` / `output_tokens` / `model_used`), and returns a validated Pydantic
model — never a raw dict.

- **`profile_agent.py` — `extract_profile(pdf_bytes, *, target_role, run_id, trace, router)`**:
  PDF → `CandidateProfile`. Extracts text with `pypdf` inside `asyncio.to_thread`, then calls Claude
  Haiku (`ModelTask.EXTRACTION`) with a **forced tool call** (the `extract_profile` tool +
  `tool_choice` pinned to it) for reliable structured output.
  - `_AGENT_SET_FIELDS` (`target_role`, `raw_resume_text`, `total_years_experience`) are injected by
    the agent, **not** the LLM — they're deliberately omitted from the tool schema. Keep new
    server-owned fields out of the tool schema and set them in `_build_profile`.
  - Self-correction: on a Pydantic `ValidationError`, the validation error is fed back to the model
    and extraction is retried **once**; a second failure raises `ProfileExtractionError` and records
    an `AGENT_ERROR` step. Don't widen this beyond one retry without a reason (cost ceiling).
- **`market_agent.py` — `query_market(profile, *, top_k=20, run_id, trace)`**: hybrid RAG over
  Qdrant → `MarketResult` (`app/models/market.py`). Embeds a query string locally
  (`ingestion.embed.embed_texts`, **same MiniLM model/dim as ingestion**), runs a semantic search
  plus a keyword (skill/title overlap) re-rank over the candidate pool, and fuses the two with
  **Reciprocal Rank Fusion** (`reciprocal_rank_fusion`, k=60). Surviving ids are hydrated to full
  `JobPosting`s from Postgres (`repository.get_postings_by_ids`, the inverse of `upsert_posting`)
  and `relevance_score` is RRF normalized to 1.0 at the top. `aggregate_skill_demand` tallies
  required-skill prevalence across the top-k. Makes **no LLM call**, so it adds no run cost.

### API surface

- `app/api/main.py` is the FastAPI app (`app.api.main:app`); routes live in `app/api/routes/`.
- `POST /profile/parse` (multipart: `file` + `target_role`) **streams** the profile agent's trace
  over SSE: one `data:` frame per step, then a terminal `event: profile` (or `event: error`) frame.
  SSE framing helpers are in `app/api/sse.py`; step payloads must use `AgentTrace.to_sse_payload`.
  `AgentTrace.listener` is the hook the route uses to push steps onto an `asyncio.Queue` as they're
  appended (keep it sync and non-blocking).

### Tracing and streaming

`AgentTrace` (in `trace.py`) is a live, mutating accumulator — a plain class, not a `BaseModel`.
Agents call `append_step(step)`, which rolls each step's cost/token figures into running totals
and flips `had_error`. `to_sse_payload(step)` produces the `{run_id, step, running_cost_usd}`
dict streamed to the frontend. Cost/token tracking is per-step, so any LLM call should emit a
`TraceStep` with `cost_usd` / `input_tokens` / `output_tokens` set.

### SSE payload contract

Every streamed step must use `AgentTrace.to_sse_payload(step)` — do not hand-roll SSE dicts.
The shape `{run_id, step, running_cost_usd}` is what the frontend expects. The FastAPI `/docs`
Swagger UI is the contract for the frontend; do not change route signatures without a
corresponding frontend update.

## LLM calls — mandatory routing

All LLM calls must go through `backend/app/llm/` (the provider router). **Never** import or
instantiate the Anthropic SDK, Groq client, or any LLM SDK directly in `agents/`, `api/`, or
`tools/`. This is how per-run cost tracking and model routing are enforced.

Model assignment — do not deviate:

| Task | Model |
|---|---|
| Resume extraction, job posting parsing | Claude Haiku 4.5 |
| Gap analysis, career planning (actor-critic) | Claude Sonnet 4.6 |
| Skill normalization / classification | Llama 3.3 via Groq |

Hard cost limit: raise an error if a single agent run exceeds $0.50.

- Callers route by `ModelTask` (`EXTRACTION` / `ANALYSIS` / `CLASSIFICATION`), never by model name
  — `LLMRouter._routes` is the only place a `ModelTask` maps to a `(Provider, model)` pair.
- All three routes are wired: `ModelTask.CLASSIFICATION` → Groq/Llama (`GroqProvider`), and
  `EXTRACTION` → Haiku / `ANALYSIS` → Sonnet via `AnthropicProvider` (`app/llm/anthropic_provider.py`,
  the only place the Anthropic SDK may be imported). `AnthropicProvider` returns a forced `tool_use`
  block as JSON when one is present, falling back to text — callers that pass `tools` +
  `tool_choice` get structured output back in `LLMResponse.content`.
- Cost is metered from a hardcoded `PRICING` table in `app/llm/cost.py` (published list rates, not
  the vendor's actual bill — Groq's free tier still meters as if paid). Update `PRICING` whenever
  a model's list price changes or a new model/provider is added to the routing table.
- The $0.50/run ceiling (`CostTracker`) is enforced per `run_id`, in-process, in memory — it does
  not survive a process restart and is not shared across worker processes.

## Ingestion pipeline

`app/ingestion/` fetches job postings from ATS boards, normalizes/classifies/embeds them, and
writes them to both Postgres and Qdrant. See `app/ingestion/pipeline.py::run_pipeline` for the
orchestration.

- Company → board mapping is a static, curated list in `app/ingestion/registry.py`
  (`REGISTRY: list[BoardConfig]`) — adding a company means adding a `BoardConfig` entry, not an
  env/config change (this is reference data, not environment config, by design).
- `normalize.py` builds `JobPosting`s but deliberately leaves `seniority` / `role_cluster` /
  `required_skills` at model defaults — `classify.py` fills those in. Don't move classification
  logic into `normalize.py` or vice versa.
- Classification is heuristic-first: `classify_seniority` and `extract_skills` are keyword-only,
  no LLM path. `classify_role_cluster` checks title keywords, then description keywords, and only
  calls the LLM (via `ModelTask.CLASSIFICATION`) when both heuristic passes are inconclusive.
  Don't add an LLM call for seniority or skills without a strong reason — the cost/latency
  asymmetry is intentional.
- Embeddings are local (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, cosine), not routed
  through `app/llm/` — embeddings aren't chat completions and don't fit the `ModelTask` contract.
  `embed.py` runs the sync model via `asyncio.to_thread`; never call `model.encode()` directly on
  the event loop.
- Qdrant point IDs are deterministic (`uuid5` of the Postgres `JobPosting.id`) so re-running
  ingestion upserts the same point instead of duplicating — never use Qdrant's auto-generated IDs
  for postings.
- `qdrant_store.ensure_collection` also creates payload indexes (`is_active`, `seniority`,
  `role_cluster`) — Qdrant rejects a filtered search on an unindexed field. The market agent
  filters on `is_active`, so any field you want to filter on at query time must be added to
  `_PAYLOAD_INDEXES` and `ensure_collection` re-run (it's idempotent).
- **Cross-store invariant**: whenever a posting is soft-deleted in Postgres
  (`app.db.mark_inactive`), the same ids must be soft-deleted in Qdrant
  (`app.ingestion.qdrant_store.mark_inactive`, which flips the `is_active` payload field via
  `set_payload` without re-sending the vector). `pipeline.py::ingest_board` already does this — if
  you add another path that marks postings inactive, propagate it to Qdrant the same way, or
  search results will surface stale postings.
- The pipeline is idempotent in the sense that re-running never duplicates data, but it does redo
  all fetch/classify/embed work each time — `content_hash` (in `app/db/repository.py`) is computed
  and stored but not yet consulted to skip re-embedding unchanged postings; that's a known gap,
  not a bug, if you're asked to add one.

## Environment / config

All env vars must be loaded via `pydantic-settings` `BaseSettings` classes — **never** use
`os.environ` or `os.getenv` directly anywhere in the codebase. Settings classes live in
`backend/app/config.py`. Never commit `.env`.

- Supabase exposes a transaction pooler (port 6543) and a session pooler (port 5432); the
  transaction pooler breaks ORM/prepared-statement workloads (no cached prepared statements,
  inconsistent read-after-write). `DatabaseSettings.async_url` / `async_migration_url` always
  resolve to the session pooler — never hardcode or pass through a `:6543/` URL for app or
  migration traffic.
- The async engine (`app/db/engine.py`) auto-detects a pgbouncer-style URL and disables asyncpg's
  statement cache + randomizes prepared-statement names when it can't avoid one. Don't bypass
  `get_engine()` / `create_migration_engine()` by constructing your own `create_async_engine()`.
- All DB writes go through `app/db/repository.py`'s upsert functions (`upsert_company`,
  `upsert_posting`, `mark_inactive`) — they're `ON CONFLICT DO UPDATE` keyed on primary key, which
  is what makes re-running ingestion idempotent. Never hand-roll an `INSERT`/`UPDATE` against
  `CompanyRow`/`JobPostingRow` elsewhere.
- Postings that disappear from a source are soft-deleted (`is_active=False`), never hard-deleted.

## Async discipline

All Python in `backend/` is async/await throughout. No synchronous blocking calls inside FastAPI
routes or agent code:

- HTTP: use `httpx.AsyncClient`, not `requests`
- Database: use async SQLAlchemy / asyncpg, not synchronous drivers
- If a library only has a sync interface, run it in a thread pool via `asyncio.to_thread`

## Model conventions

- **Pydantic v2 only**: use `field_validator` / `model_validator` with explicit `mode=`. Do not
  use the v1 `@validator` decorator — ever.
- **Import order is deliberate to avoid cycles**: `profile` → `job` → `gap` (no profile dep) →
  `plan` (imports `gap`) → `trace` (no model deps). Keep `gap` independent of `profile`.
- **`Field(exclude=True)`** marks fields that must never reach the client:
  `CandidateProfile.raw_resume_text`, `JobPosting.embedding_id`.
- **Skill names are normalized** (stripped + lowercased) by validators; `canonical_name` is filled
  in later by a normalization step, and properties like `skill_names` / `required_skill_names`
  prefer it.
- All agent outputs must be validated Pydantic models — no raw dicts passed between agents.
- `app/models/__init__.py` re-exports everything, so import as `from app.models import CandidateProfile`.

## Testing

- Tests live in `backend/tests/`, use `pytest-asyncio`
- Mark async tests with `@pytest.mark.asyncio`
- Run with `.venv/bin/python -m pytest`
- Every new module gets a corresponding test file: `models/gap.py` → `tests/test_gap.py`
- Tests must pass before any commit — run `ruff check .` and `pytest` together before committing

## Key differentiators — never remove or bypass

1. Every skill gap is hyperlinked to real job postings that prove it exists (`PostingEvidence`)
2. Streaming agent trace UI — users see live reasoning steps via SSE
3. Actor-critic loop between planner and gap_critic (max 2 rounds)
4. Published eval harness comparing 3 scoring strategies (lives in `backend/app/evals/`)
5. Per-run cost displayed in the UI ($0.10–$0.30 target)

## Infrastructure

`docker-compose.yml` provides Postgres (5432), Qdrant (6333), and Redis (6379). External services
configured via `.env`: Anthropic, Groq, Tavily (search), Supabase, LangSmith (tracing).

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
