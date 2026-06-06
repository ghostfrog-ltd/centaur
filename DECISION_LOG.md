# Project Centaur Decision Log — Compact Head

Keep the full canonical history in `docs/DECISION_LOG.md`. This file should only hold the latest durable decisions that matter for ordinary work.

## 2026-06-05
- Paper/live fast-path admission is now fitness-only. Raw score remains shadow/reporting evidence and no longer bypasses fitness into execution.
- Paper daily equity drawdown protector is `$10.00`. This widens only the paper daily entry latch, not notional, slots, strategies, broker scope, or live behaviour.
- Added shadow-only crypto research profiles `crypto_research.dip_rebound` and `crypto_research.range_breakout`; they are evidence-only and not execution-approved.

## 2026-06-04
- Live is an independent lane governed by `LIVE_*` dials exactly, not a blind copy of paper.
- Shared evidence/signals feed separate paper and live proposal/risk/execution lanes.
- Alpaca Live no longer requires a same-tick paper order before considering a live entry.
- Candidate-speed migration is active: fast selected candidates can trade; leftovers go to `slow.enrichment_queue` for advisory evidence with `trade_authority=none`.
- Heavy GA threshold advice is off the hot trading path; fast ticks use cached adaptive threshold state only.
- Equity close policy: block new entries in final `15` minutes; flatten in final `5` minutes.

## 2026-05-31
- Runtime modes, provenance, and storage lanes are explicit: `core` evidence plus separate `paper` / `live` execution lanes.
- `ModeContext`, `ExecutionRouter`, and `LiveRiskGuard` are core safety boundaries.
- PostgreSQL is required for configured/executing operations; no silent SQLite fallback.
- Dashboard/reporting surfaces must keep paper, live, shadow, and observe-only evidence clearly separated.

## Older Durable State
- Paper notional remains `$10`, one order per tick, long-only.
- Active execution adapters are `alpaca_paper` and `alpaca_live`; other providers fail closed unless explicitly approved.
- `launchd` runs the supervised heartbeat service; dashboard refresh remains separate from the normal control tick.
