# Project Centaur — Codex Context

Purpose: compact read-first truth for safe work. Load archived logs only when the task needs history.

## Identity
Centaur is an auditable trading research and micro paper/live execution system. Preserve capital first; optimise risk-adjusted, measurable growth rather than raw profit.

## Prime Rules
1. Preserve capital and compliance.
2. Keep decisions auditable, measurable, and data-attributable.
3. Never use the `$50/day` target to widen risk, notional, slots, broker scope, live behaviour, or strategy gates.
4. New evidence streams need a report/status/dashboard/query path.
5. Safety-critical paths need comments/docstrings for gates, risk boundaries, and audit trails.

## Current Truth
- Architecture direction: LangGraph-first with Pydantic state/contracts. `ControlPipelineRunner` is migration scaffolding; new orchestration should use typed graph/node surfaces where practical.
- Modes: `shadow`, `paper`, `live_dry`, `live`.
- LLM: Gemini API only, adapter-backed.
- Active operations store: PostgreSQL. If Postgres is configured or execution is enabled, fail closed rather than silently using SQLite.
- Scheduler: macOS `launchd`, `.venv-mac`, skip-if-busy 30-second control tick, separate read-only dashboard API.
- Storage direction: shared `core` evidence/fitness/instruments plus separated `paper`/`live` execution and evidence lanes; current Postgres routing uses lane schemas plus provenance labels.

## Execution Envelope
- Active paper lanes: `alpaca_paper` plus separate `trading212_paper` equities where eligible.
- Current approved live runtime: Alpaca Live is still implemented as the same-as-paper follower recorded on 2026-05-29 until the independent live proposal lane is implemented, tested, reported, and explicitly activated.
- Target live architecture, approved as documentation direction on 2026-06-04: paper and live should be independent execution lanes over shared evidence/strategy signals. Paper must obey `PAPER_*` dials; live must obey `LIVE_*` dials from `.env` exactly. Live must not blindly copy paper once this migration is implemented, and it must not invent behaviour outside `.env`.
- The independent live lane must keep the existing capital envelope unless `.env` and an explicit approval say otherwise: configured strategies/assets only, configured notional, configured slots, configured per-tick order cap, configured daily protector, configured projected-gain floors, configured buffers, and configured broker routing.
- IG is scaffold/shadow only. Trading 212 Live has adapter/readiness wiring but order mutation is hard-disabled. Other brokers/providers fail closed until implemented, tested, reported, and approved.
- Long-only. Paper trade notional is `$10` unless explicitly approved; Trading 212 paper currently uses `£5` native sizing for the reset £100 demo account.
- Max orders per tick: `1`. Base slots: `10`; earned slots add +1 per full `$10` tracked P/L above baseline and can fall away.
- Daily equity drawdown protector: `$2.00`; baseline uses the more protective of the first Centaur-seen session equity and the broker-reported `last_equity`/previous equity, and latches once breached.
- Stale unfilled equity entries: reap after `5` minutes.
- Allowed strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`.
- Projected-gain floors: equities `1.5%`, crypto `2.0%`.
- Buffers: equities `5` bps `DAY` limits; crypto `25` bps `IOC` limits.
- Crypto momentum: `1.0%` stop; require instrument identity, reject spikes above `2.5%`, notional candidate volume below `£50,000` where derivable, and spread above `0.25%` when spread evidence exists.
- Managed exits: profit capture uses the current runtime config (`PAPER_EXECUTION_PROFIT_CAPTURE_PCT` / `LIVE_EXECUTION_PROFIT_CAPTURE_PCT`) at exit-decision time, not the value or take-profit target stored on the entry order; stored targets are only a legacy fallback when current profit capture is disabled. Profit ladder evidence remains at `1.25,2,3,4,6%` unless reconfigured.
- Operator-facing ratio controls for profit capture, stop loss, projected-gain floors, and trailing giveback use percent notation in `.env`: `0.5` means `0.5%`, `1` means `1%`, `2` means `2%`; legacy decimal ratio values below `0.1` are still parsed as-is. Movement, spread, and ladder `PCT` fields are already percent-point values.
- Same-symbol managed exits must use the most protective still-open entry stop.
- Alpaca Live entries fail closed while any existing live position lacks a persisted managed-exit entry plan.
- Max-hold is a hard backstop: no red deferral after the configured max hold.
- Equity no-overnight-carry: block new entries in final 60 minutes of every equity session; flatten equities in final 15 minutes, including missing-plan positions via an audited unmanaged flatten. Close-flattening must fall back to broker position price when latest bars are unavailable. Crypto uses the hard max-hold backstop.
- Alpaca Live equity PDT guard: new live equity entries fail closed unless the live account proves prior/effective equity >= `$25,000`; exits still route when permitted. Do not auto-unblock on Alpaca’s 2026-06-04 framework date without observed account/API behaviour and explicit review.
- Trailing drawdown observer is observe-only until promoted.

## Strategy / Fitness
- Prefer deterministic, auditable logic over opaque AI for trading, risk, execution, fitness, and replay.
- Equity suppress threshold has adaptive paper-only rails; do not mutate `.env`, notional, broker routing, live readiness, max slots, floors, daily protection, stale-order rules, market-hours rules, long-only policy, or allowlist.
- Crypto suppress threshold is separate and fixed.
- Score-to-trade override: already allowed strategies with raw score >= configured `PAPER_MIN_SIGNAL_SCORE_TO_TRADE`/`LIVE_MIN_SIGNAL_SCORE_TO_TRADE` survive fitness suppression so the relevant lane CFO/risk gate can evaluate them. Current dial is `90.0`. Fitness remains ranking/reporting evidence.
- Holding-window advice is recommendation-only. When not compounding, review exits, holding-window advice, profit ladder, stale exits, and fill behaviour before loosening entries.

## Broker / Adapter Notes
Centaur is broker-agnostic: core owns instruments, signals, scoring, fitness, risk, slots, intents, exits, reports, and evidence interpretation. Vendors own market data, order formatting, account state, capabilities, and symbol mapping behind adapters.

- Execution adapter lookup resolves `alpaca_paper`, `alpaca_live`, `trading212_paper`, and disabled `trading212_live`.
- Trading 212 Paper is paper/equity-only with its own 10 slots, UK weekday session (`Europe/London`, default `08:00-16:30`), account sync/protection/evidence, and duplicate client-order-id guard.
- Trading 212 entries require a configured UK symbol, real venue ticker, trusted latest price, and Trading 212-compatible proposal evidence. The public API metadata surface is not a watchlist price feed.
- `TRADING212_PAPER_MARKET_DATA_PROVIDER=positions_api` only prices seeded/held symbols via `/equity/positions currentPrice`; seed-only holdings do not consume Centaur strategy slots, block same-symbol entries, or trigger managed exits until a Centaur managed buy exists.
- GBX prices must convert to GBP before sizing. Trading 212 Live remains disabled unless separately approved with evidence/reporting/latest-price/final-live-guard review.

## Architecture Progress
- Runtime implementation ownership lives under `app/`; old `centaur/` is removed.
- Heartbeat flow starts at `app/heartbeat/`: `pipeline.py` is the master pipeline, `graph.py` owns the LangGraph/Pydantic `StateGraph`, and `steps/NN_name/` mirrors generated Mermaid order with local `pipeline.py`, `contract/`, and `implementation/main.py`.
- `app/framework/engine/control_graph.py` is a compatibility facade; new orchestration belongs in `app/heartbeat/graph.py`, heartbeat step pipelines, or narrower typed domain nodes.
- `ModeContext`, `ExecutionRouter`, and `LiveRiskGuard` are core safety boundaries.
- `live_dry` records live intents in `execution_router_intents` without mutating brokers.
- Canonical instrument registry persists `InstrumentRef`, `canonical_instrument_id`, `venue`, and `venue_symbol` where derivable.
- Config is `.env` only, grouped core/paper/live. Current same-as-paper runtime fails closed on unnamed live-vs-paper differences outside `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES`; the migration target is stricter and clearer lane ownership where paper uses `PAPER_*`, live uses `LIVE_*`, and any live action reports the exact dials that authorized it.
- Dashboard/status must label paper, live, shadow, observe-only, recent, all-time, and broker-ledger evidence separately.
- Slack is one-way notification only, never a command surface. Hourly liveness/status messages may be enabled via `SLACK_HOURLY_STATUS_*`; if they stop arriving, treat scheduler/control-loop freshness as suspect until checked.
- Scheduled test monitoring runs the unit suite and a read-only scheduler freshness check; stale/missing/non-ok control ticks fail the monitor and can alert.

## Evidence / Reports
For new evidence, define the question, persist provenance (mode/env/broker/providers/thresholds/execution impact), expose a report/status/query, label observe-only/counterfactual data, and keep queries bounded/indexed.

Useful commands:
- `.venv-mac/bin/python -m unittest discover tests`
- `.venv-mac/bin/python scripts/run_test_monitor.py`
- `.venv-mac/bin/python main.py --status`
- `.venv-mac/bin/python main.py --evidence-report`
- `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --holding-window-advice`
- `.venv-mac/bin/python main.py --overnight-giveback`
- `.venv-mac/bin/python main.py --crypto-health`
- `.venv-mac/bin/python main.py --adapter-inventory`
- `.venv-mac/bin/python main.py --storage-separation-report`

## Work Rules
Before changing behaviour, inspect the exact code path. If touching execution, risk, live, broker routing, storage, or persistence, read `CONSTRAINTS.md`. If changing orchestration nodes/edges, run `.venv-mac/bin/python scripts/update_mermaid_visuals.py` and keep generated flow docs current. Update compact context and canonical docs when runtime behaviour changes.
