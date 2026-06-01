# Project Centaur — Codex Context Pack

Purpose: give Codex enough project truth to work safely without loading the full historic logs on every task. This file is the default read-first context. Use the larger archived logs only when a task needs detailed history.

## Identity
You are working inside Project Centaur: a trading research and micro paper/live follower system. Your job is to build, harden, test, and explain the system without bypassing capital-preservation rules.

Centaur is not a gambling bot. It is an auditable research/execution engine that should optimise for long-term, risk-adjusted growth.

## Prime Directives
1. Preserve capital first.
2. Grow capital safely, legally, repeatedly, and measurably.
3. Maximise risk-adjusted return, not raw profit.
4. Keep decisions auditable, measurable, and attributable to data.
5. Treat strategy fitness as invalid if it depends on violating risk or compliance rules.
6. Every new evidence stream must have a runnable report, dashboard/status surface, or documented query path.
7. Any safety-critical path needs clear comments/docstrings explaining the gate, risk boundary, and audit trail.

## Current System Truth
- Runtime architecture: pipeline-first, LangGraph-compatible control flow.
- Runtime modes: `shadow`, `paper`, `live_dry`, `live`.
- LLM layer: Gemini API only; keep it behind an adapter.
- Operations database: PostgreSQL for active paper/live operation. Do not silently fall back to SQLite when Postgres is configured or execution is enabled.
- Broker routing: Alpaca Paper active; Alpaca Live approved only as the same-as-paper follower lane recorded on 2026-05-29.
- Alpaca Live must remain same-as-paper: same strategies, asset classes, `$10` entries, 10 base slots, one order per tick, `$5` daily protector, shared paper/shadow fitness. No live-only threshold or max-daily-order policy unless explicitly approved.
- IG is scaffold/shadow only. Trading 212 Paper is approved as a separate paper equity lane with its own 10 base slots, fixed `£10` native order sizing, broker-specific account sync/protection/evidence, and duplicate client-order-id guard. Crypto remains Alpaca-only. Binance, Coinbase, Polygon, etc. are future adapters only until implemented, tested, reported, and explicitly approved.
- Storage direction: shared `core` reviewed evidence/fitness/instruments plus separated `paper` and `live` execution/evidence lanes. Active PostgreSQL routing now keeps shadow/fitness evidence in `core` and execution/account rows in the runtime lane schema, with provenance labels retained on rows for audit/reporting.
- Scheduler: macOS `launchd` wrapper on `/Volumes/Bob/www/ghostfrog-centaur`, project-local `.venv-mac`, skip-if-busy locking, 30-second control tick, and a separate read-only dashboard API service for the DDEV operator UI.

## Non-Negotiable Constraints
Do not:
- Use the `$50/day` target to widen risk, notional, slots, broker scope, live behaviour, or strategy gates.
- Submit live-money orders outside the recorded 2026-05-29 same-as-paper Alpaca Live override.
- Submit Alpaca Live entries unless live enablement, kill switch, credentials, activation acknowledgement, readiness checks, same-paper-order validation, and live guard all pass.
- Make paper trades above `$10` notional without explicit human approval.
- Switch brokers silently.
- Allow unsupported directions; current execution is long-only.
- Submit paper orders when the paper kill switch is on, when daily drawdown protection has triggered, when market-hours rules block equities, or when open slots/orders are full.
- Introduce raw chain-of-thought logging.
- Change logic that contradicts constraints or the decision log without asking for human override.
- Add high-volume persistence without bounded queries/indexes.

## Paper Execution Envelope
- Active broker: `alpaca_paper`.
- Secondary paper broker: `trading212_paper` for equities only, with separate 10-slot capacity and broker-labelled evidence.
- Asset classes: equities and crypto.
- Entry style: marketable limit order.
- Equity fractional orders: `DAY` limit orders.
- Crypto entries/exits: `IOC` limit orders.
- Default notional: `$10`.
- Max orders per tick: `1`.
- Base max open positions: `10`.
- Earned slots: +1 effective slot per full `$10` tracked P/L above baseline; slots can fall away.
- Daily equity drawdown protector: `$5.00`.
- Stale unfilled equity entries: reap after `5` minutes.
- Long-only.
- Allowed paper strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`.
- Projected-gain floors: equities `1.5%`, crypto `2.0%`.
- Crypto momentum stop: `1.0%` after 2026-06-01 operator override to keep `$10` trade losses near `$0.10` instead of `$0.30`; crypto remains enabled.
- Crypto momentum now fail-closes missing instrument identity, rejects spikes above `2.5%`, rejects notional candidate volume below `£50,000` where derivable, and rejects spread above `0.25%` when spread evidence is present.
- Live Alpaca equity entries are PDT guarded: if the Alpaca Live account cannot prove prior/effective equity at or above `$25,000`, new live equity entries fail closed because same-day exits may be broker-rejected. Existing live exits still route when permitted. Crypto is not blocked by this PDT guard. Alpaca announced a new intraday-margin framework for 2026-06-04, but do not auto-unblock on date alone; require observed API/account behavior and explicit review.
- Limit buffer: equities `5` bps, crypto `25` bps.
- Profit capture: `1.25%` for paper managed exits, without lowering entry projected-gain floors.
- Aggregated same-symbol managed positions exit using the most protective still-open entry stop; do not fall back to the latest entry plan when an older open lot has a higher stop.
- Profit target ladder evidence: `1.25,2,3,4,6` percent.
- Max-hold red deferral: for `profit_after_1h_else_1d` and `profit_capture_else_1d`, do not sell red solely because max hold elapsed; mark `max_hold_red_deferred`.
- Friday no-weekend-carry for equities: block new equity entries in final 60 minutes of regular Friday session; flatten remaining managed equity positions in final 15 minutes. Crypto unchanged.
- Trailing drawdown observer is observe-only until explicitly promoted.

## Strategy / Fitness Rules
- Prefer deterministic, auditable strategy logic over opaque AI decisions for trading, risk, execution, fitness, and replay.
- Equity suppress threshold has adaptive paper-only controller rails; do not mutate `.env`, notional, broker routing, live readiness, max slots, projected-gain floors, daily protection, stale-order rules, market-hours rules, long-only policy, or strategy allowlist.
- Crypto has separate fixed suppress threshold.
- High-score near-miss override is paper-only and applies only to already allowed strategies with raw signal score at least `90.0` and composite fitness within `0.25` of active suppress threshold.
- Holding-window advice is recommendation-only. Do not change managed exits without explicit approval.
- When Centaur is not compounding, check exits before entries: review paper exits, holding-window advice, profit-target ladder, stale exits, and fill behaviour before loosening thresholds or allowlists.

## Adapter-First Architecture
Treat Alpaca as the first adapter, not the product. Centaur core owns instruments, signals, strategy scoring, fitness, risk, slots, order intents, exits, reports, and evidence interpretation.

Vendor-specific behaviour belongs behind adapters:
- market data
- execution/order formatting
- account/broker state
- venue symbol mapping
- broker capabilities

Current active execution adapter lookup resolves `alpaca_paper`, `alpaca_live`, and `trading212_paper`. Trading 212 must remain paper-only/equity-only unless separately reviewed and approved.

## Evidence / Reporting Discipline
When adding evidence/data capture:
1. Define the question the data answers.
2. Persist enough context: mode, environment, broker, data provider, execution provider, thresholds, and whether it affected execution.
3. Add it to `main.py --evidence-report` or a specific report command.
4. Label observe-only/counterfactual data clearly.
5. Keep queries bounded and indexed.
6. Document how an operator should interpret the evidence.

Useful reports:
- `.venv-mac/bin/python main.py --status`
- `.venv-mac/bin/python main.py --evidence-report`
- `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --holding-window-advice`
- `.venv-mac/bin/python main.py --crypto-health`
- `.venv-mac/bin/python main.py --adapter-inventory`
- `.venv-mac/bin/python main.py --storage-separation-report`

## Current Architecture Progress
- `ModeContext` centralises mode/environment permission checks.
- `ExecutionRouter` is the choke point before broker submit/cancel/mutation.
- `LiveRiskGuard` re-checks activation, kill switch, broker, readiness, capacity, latest-bar/instrument availability, same-paper validation, and notional.
- `live_dry` records intended entry/exit/cancel actions in `execution_router_intents` without mutating the live broker.
- Canonical instrument registry exists with `InstrumentRef`, `canonical_instrument_id`, `venue`, and `venue_symbol` persisted across broker orders and evidence where derivable.
- Runtime implementation ownership now lives under `app/`; the old `centaur/` package has been removed.
- Runtime configuration is `.env` only, grouped into core, paper, and live sections. Mirrored live execution levers match paper by default while live is armed; named live differences must be explicitly listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES` or config load fails closed. Crypto momentum tuning is lane-scoped as `PAPER_CRYPTO_MOMENTUM_*` and `LIVE_CRYPTO_MOMENTUM_*`; legacy `CRYPTO_MOMENTUM_*` names are fallback only.
- Strategy candidates without `asset_class`, `symbol`, or `canonical_instrument_id` fail closed before scoring. Strategy rejection summaries are persisted in tick snapshots and surfaced by `main.py --evidence-report`.
- Dashboard/status wording has been tightened to separate paper account values, live follower monitoring, broker ledger rows, latest tick activity, all-time evidence, shadow recommendations, and observe-only drawdown data.
- Slack alerts are one-way operator notifications only. They use `SLACK_ALERTS_ENABLED`/`SLACK_WEBHOOK_URL`, persist notification events for dedupe, and must never become a live-trading command surface. `LIVE_EQUITY_PDT_REVIEW_REMINDERS_ENABLED=true` sends action-required Slack reminders every `LIVE_EQUITY_PDT_REVIEW_REMINDER_INTERVAL_MINUTES` after `LIVE_EQUITY_PDT_REVIEW_REMINDER_START_DATE` while the Alpaca Live equity PDT guard remains active.
- Scheduled unit-test monitoring is available through `scripts/run_test_monitor.py`, `ops/com.ghostfrog.centaur.test-monitor.plist`, and `ops/centaur_tests.cron`. It runs the unit suite, persists a small `.runtime/test_monitor_state.json` failure fingerprint, sends Slack first-failure/reminder/recovery alerts when enabled, and can be acknowledged with `scripts/run_test_monitor.py --reset-failure-notification`.

## How To Work
Before changing behaviour, read this file, then inspect the exact code path. If the task touches a known safety boundary, check `CONSTRAINTS.md` and recent decision history. For normal coding tasks, do not load the full historic `PROGRESS.txt` or full `docs/DECISION_LOG.md` unless the task specifically asks for historical reasoning.

When changing runtime behaviour, update the compact context and the relevant canonical docs. Keep archived logs as history, not as prompt ballast.
