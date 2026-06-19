# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What SkillLens is

A multi-agent AI system that analyzes resumes against real job-market data, identifies skill gaps, and generates evidence-backed career roadmaps. Python/FastAPI backend with a LangGraph agent pipeline; Next.js frontend that renders a live agent activity feed over Server-Sent Events.

## Current state

This is an early scaffold. Only `backend/app/models/` (the Pydantic data models) and the supporting test suite are implemented. The other `backend/app/` subpackages (`agents`, `api`, `db`, `ingestion`, `llm`, `tools`, `evals`) are empty placeholders (`.gitkeep`). The frontend is a default Next.js app. Build new functionality against the existing models — they are the source of truth for every agent.

## Commands

The backend uses `uv` and a checked-in virtualenv at `backend/.venv`. Run all backend commands from the `backend/` directory.

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
```

Frontend (from `frontend/`, uses pnpm):

```bash
pnpm dev      # next dev
pnpm build
pnpm lint
```

Copy `.env.example` to `.env` and fill in keys before running anything that touches external services.

## Architecture

### The agent pipeline

The intended flow is encoded in `backend/app/models/trace.py` `StepType`, which is the canonical ordering of pipeline stages:

`resume_parsing` → `profile_extracted` → `market_query` → `market_results` → `skill_aggregation` → `gap_analysis_start`/`gap_identified`/`gap_analysis_done` → `plan_draft` → `critique_start`/`critique_challenge`/`plan_revision` (up to 2 rounds) → `plan_final`.

This maps to the data models, each owned by a stage:
- **`profile.py` — `CandidateProfile`**: extracted from the uploaded resume. Carries `target_role` (user-supplied at upload) and `raw_resume_text` (server-only, `exclude=True`).
- **`job.py` — `JobPosting`**: fetched from ATS sources (Greenhouse, Lever) during the market query, normalized and embedded. `id` must be `"{source}_{external_id}"`.
- **`gap.py` — `SkillGap`**: the core analysis unit. Every gap requires ≥1 `PostingEvidence` (enforced at the model level, not in agent code) — the system never asserts a gap without a real JD excerpt to back it.
- **`plan.py` — `CareerPlan`**: the deliverable. Wraps the gaps plus 1–12 `WeeklyMilestone`s; gap counts and milestone sequencing are validated/computed by the model.

### Tracing and streaming

`AgentTrace` (in `trace.py`) is a live, mutating accumulator — a plain class, not a `BaseModel`. Agents call `append_step(step)`, which rolls each step's cost/token figures into running totals and flips `had_error`. `to_sse_payload(step)` produces the `{run_id, step, running_cost_usd}` dict streamed to the frontend. Cost/token tracking is per-step, so any LLM call should emit a `TraceStep` with `cost_usd`/`input_tokens`/`output_tokens` set.

### Model conventions (important when extending)

- **Pydantic v2 only**: use `field_validator` / `model_validator` with explicit `mode=`. Do not use the v1 `@validator`.
- **Import order is deliberate to avoid cycles**: `profile` → `job` → `gap` (no profile dep) → `plan` (imports `gap`) → `trace` (no model deps). Keep `gap` independent of `profile`.
- **`Field(exclude=True)`** marks fields that must never reach the client: `CandidateProfile.raw_resume_text`, `JobPosting.embedding_id`.
- **Skill names are normalized** (stripped + lowercased) by validators; `canonical_name` is filled in later by a normalization step, and properties like `skill_names` / `required_skill_names` prefer it.
- `app/models/__init__.py` re-exports everything, so import as `from app.models import CandidateProfile`.

### Infrastructure

`docker-compose.yml` provides Postgres (relational, also via Supabase), Qdrant (vector store for JD embeddings), and Redis. External services per `.env.example`: Anthropic (LLM), Groq, Tavily (search), Supabase, LangSmith (tracing). Default to the latest Claude models for any LLM work.
