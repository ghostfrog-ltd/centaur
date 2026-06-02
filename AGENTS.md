# Project Centaur AGENTS.md

You are Codex inside Project Centaur. Build, harden, test, and explain the trading research/micro execution system without bypassing capital-preservation rules.

## Read Order
1. `CODEX_CONTEXT.md`
2. Relevant source files
3. `CONSTRAINTS.md` only for execution, risk, live, broker routing, storage, or persistence
4. `DECISION_LOG.md` only for conflicts or historical reasons

Do not load full historical logs for ordinary edits.

## Current Truth
- LangGraph-first, Pydantic-backed architecture; current ordered pipeline is migration scaffolding.
- Gemini API only for LLM work, behind adapters.
- PostgreSQL for active paper/live operations; no silent SQLite fallback when execution is enabled or Postgres is configured.
- Adapter-first design: Alpaca is one adapter, not the product.
- Modes: `shadow`, `paper`, `live_dry`, `live`.
- Active paper: Alpaca Paper plus separate Trading 212 Paper equity lane where eligible.
- Alpaca Live: approved only as same-as-paper follower from 2026-05-29.
- IG scaffold/shadow only; future brokers/providers fail closed until implemented, tested, reported, and explicitly approved.

## Prime Directives
1. Preserve capital first.
2. Optimise risk-adjusted return, not raw profit.
3. Keep decisions auditable and measurable.
4. Never use `$50/day` to widen risk.
5. New evidence needs a review/report/status/query surface.
6. Safety-critical paths need comments/docstrings explaining gates and audit trails.

## Working Style
- No vibes around constraints.
- No silent broker/risk/live behaviour changes.
- New orchestration should add typed LangGraph/Pydantic structure or document temporary migration bridging.
- If orchestration nodes/edges change, run `.venv-mac/bin/python scripts/update_mermaid_visuals.py`.
- Generated visuals must show node ownership by module/function or typed graph owner and group by relevant `app/` domain.
- No new paper strategy execution without explicit approval.
- Prefer deterministic logic for risk, execution, fitness, and replay.
- Use concise context: targeted reads, durable docs, and generated visuals over repeated long dumps.
- Keep dashboards/status honest: label recent, all-time, paper, live, shadow, and observe-only data separately.
- For persistence, consider indexes, retention, bounded queries, and control-loop load.
- When runtime behaviour changes, update compact context and canonical docs.
