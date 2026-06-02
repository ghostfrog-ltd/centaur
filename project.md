# Project Centaur — Orientation

Centaur is now an auditable trading research and micro paper/live follower system. The current operating truth lives in:

- `CODEX_CONTEXT.md` for compact read-first context
- `CONSTRAINTS.md` for safety, execution, live, broker, storage, and persistence rules
- `DECISION_LOG.md` for the rolling decision head
- `docs/DECISION_LOG.md` and `docs/PROJECT_RECORD.md` for full history

## Current Direction
- LangGraph-first orchestration with Pydantic-backed state/contracts.
- Adapter-first broker design: Alpaca and Trading 212 are lanes, not product boundaries.
- Gemini-only LLM layer behind adapters.
- PostgreSQL active operations store; no silent SQLite fallback when execution is enabled or Postgres is configured.
- Runtime modes: `shadow`, `paper`, `live_dry`, `live`.

## Safety Baseline
Preserve capital first, optimise risk-adjusted return, keep decisions auditable, and treat `$50/day` as prioritisation only. Do not widen risk, notional, slots, broker scope, live behaviour, or strategy gates without explicit approval and doc updates.

## Historical Note
Older PoC ideas such as an Alpaca-only product boundary, broad genetic-algorithm framing, or AI-led execution are superseded by the compact context and constraints above. Use archived docs only when a task needs historical reasoning.
