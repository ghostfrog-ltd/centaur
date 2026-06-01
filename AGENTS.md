# Project Centaur AGENTS.md — Compact

You are Codex working inside Project Centaur. Build, harden, test, and explain the trading research/micro execution system without bypassing capital-preservation rules.

## Read Order
Default:
1. `CODEX_CONTEXT.md`
2. Relevant source files for the task
3. `CONSTRAINTS.md` only if touching execution/risk/live/storage/persistence
4. `DECISION_LOG.md` only if a decision conflict or historical reason matters

Do not load full historical logs for ordinary code edits.

## Current Truth
- LangGraph-first architecture direction with Pydantic-backed state/contracts; the current ordered pipeline is migration scaffolding, not the desired end state.
- Gemini API only for LLM work; keep it adapter-backed.
- PostgreSQL for active paper/live operations; no silent SQLite fallback when execution is enabled or Postgres is configured.
- Adapter-first design: Alpaca is one adapter, not the product.
- Runtime modes: `shadow`, `paper`, `live_dry`, `live`.
- Active execution: Alpaca Paper.
- Alpaca Live: approved only as same-as-paper follower from 2026-05-29.
- IG: scaffold/shadow only.
- Future brokers/providers: fail closed until implemented, tested, reported, and explicitly approved.

## Prime Directives
1. Preserve capital first.
2. Optimise risk-adjusted return, not raw profit.
3. Keep decisions auditable and measurable.
4. Never treat `$50/day` as permission to widen risk.
5. Any new evidence stream must have a review/report surface.
6. Safety-critical paths need comments/docstrings explaining gates and audit trails.

## Working Style
- No vibes around constraints.
- No silent broker/risk/live behaviour changes.
- New orchestration work should either add typed LangGraph/Pydantic structure or clearly document why it is a temporary migration bridge.
- When orchestration/pipeline nodes or edges change, run `.venv-mac/bin/python scripts/update_mermaid_visuals.py` and keep the rendered flow docs current.
- No new paper strategy execution without explicit approval.
- Prefer deterministic logic over opaque AI behaviour for risk, execution, fitness, and replay.
- Use tokens deliberately: prefer concise answers, targeted file reads, durable docs, and generated visuals over repeated long explanations or broad context dumps.
- Keep dashboards/status honest: recent activity, all-time evidence, paper, live, shadow, and observe-only data must be labelled separately.
- When adding persistence, consider indexes, retention, bounded queries, and control-loop load.
- When changing runtime behaviour, update the compact context and relevant canonical docs.
