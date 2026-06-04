# Project Centaur Constraints

## Hard Nos
- Do not use the `$50/day` target to widen risk, notional, slots, gates, brokers, or live behaviour.
- No live-money trading outside the 2026-05-29 Alpaca Live same-as-paper override until the independent live proposal lane is implemented, tested, reported, and explicitly activated.
- In the current follower runtime, no Alpaca Live entry unless enablement, kill switch, credentials, activation ack, readiness, same-paper validation, and live guard all pass.
- In the target independent-lane runtime, no Alpaca Live entry unless the live lane's own proposal and risk gates pass using the active `LIVE_*` `.env` dials exactly, followed by the final live guard.
- No paper trade above `$10` notional without explicit approval.
- No silent broker switch or unsupported direction change; execution is long-only.
- No paper order when kill switch, daily drawdown, market-hours, slot, or open-order gates block it.
- No raw chain-of-thought logging.
- No contradiction of constraints/decision log without human override.
- No safety-critical trading path without comments/docstrings explaining gates and audit trail.
- No evidence capture without a report/dashboard/status/query surface.
- No high-volume persistence without bounded queries and indexes.

## Architecture Contracts
- Direction is LangGraph-first orchestration with Pydantic-backed state, node inputs, and node outputs.
- `ControlPipelineRunner`/`StepDefinition` is migration scaffolding; do not deepen opaque dict-only control flow when a typed graph node/model is practical.
- New workflow state should use explicit Pydantic models, especially for market data, candidates, signals, fitness allocation, risk approvals, order intents, execution results, and evidence summaries.
- Named capital gates must stay auditable: market readiness, fitness allocation, lane CFO risk, execution router, live guard, notifications/reporting.
- Orchestration node/edge changes require `.venv-mac/bin/python scripts/update_mermaid_visuals.py` and updated generated visual docs.
- Generated visuals must show source module/function or typed graph ownership and group by relevant `app/` domain.
- LangGraph/Pydantic migration must be behaviour-preserving unless a separate trading-policy change is approved.

## Token Discipline
- Load only context needed for the task; prefer compact docs, search results, and precise source slices over full logs.
- Put durable explanations in docs or generated visuals so future turns can link instead of re-explaining.

## Active Paper Envelope
- Paper lanes: `alpaca_paper` plus separate `trading212_paper` equities where enabled/eligible.
- Assets: equities and crypto.
- Notional: `$10` unless approved; Trading 212 paper currently uses `£5` native sizing for the reset £100 demo account.
- Max orders/tick `1`; base slots `10`; earned slots +1 per full `$10` tracked P/L above baseline and can fall away.
- Daily equity drawdown protector `$2.00`; baseline uses the more protective of first Centaur-seen session equity and broker-reported `last_equity`/previous equity, then latches once breached. Long-only.
- Allowed strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`.
- Projected-gain floors: equities `1.5%`, crypto `2.0%`.
- Crypto momentum: `1.0%` stop; require instrument identity; reject movement > `2.5%`, notional candidate volume < `£50,000` where derivable, and spread > `0.25%` when known.
- Buffers/orders: equity `5` bps `DAY` limits; crypto `25` bps `IOC` limits.
- Stale unfilled equity entries: reap after `5` minutes.
- Managed exits: profit capture uses the current runtime config (`PAPER_EXECUTION_PROFIT_CAPTURE_PCT` / `LIVE_EXECUTION_PROFIT_CAPTURE_PCT`) at exit-decision time, not stale entry-order metadata or stored take-profit targets; stored targets are only a legacy fallback when current profit capture is disabled. Ladder evidence `1.25,2,3,4,6%`.
- Operator-facing ratio controls for profit capture, stop loss, projected-gain floors, and trailing giveback use percent notation in `.env`: `0.5` means `0.5%`, `1` means `1%`, `2` means `2%`; legacy decimal ratio values below `0.1` are still parsed as-is. Movement, spread, and ladder `PCT` fields are already percent-point values.
- Same-symbol managed exits must use the most protective still-open entry stop.
- New Alpaca Live entries are blocked while any existing live position lacks a persisted managed-exit entry plan.
- Max-hold is a hard backstop: no red deferral after the configured max hold.
- Equity no-overnight-carry: block entries in final 60 minutes of every equity session; flatten equities in final 15 minutes, including missing-plan positions via an audited unmanaged flatten. Close-flattening must fall back to broker position price when latest bars are unavailable. Crypto uses the hard max-hold backstop.
- Alpaca Live equity PDT guard: new live equity entries fail closed unless prior/effective equity >= `$25,000`; exits still route when permitted. Do not auto-unblock on the 2026-06-04 framework date without observed account/API behaviour and explicit review.

## Live Lane
Current runtime: Alpaca Live is same-as-paper only. It must not invent live-only thresholds, order limits, strategies, assets, broker routing, or notional. The final live guard is a real-money safety boundary, not a strategy engine. The live CFO gate also fails closed on new entries while current live positions cannot be matched to persisted managed-exit entry plans.

Target runtime direction approved for documentation on 2026-06-04: live should not be a blind copy of paper. Paper and live should be separate execution lanes fed by shared evidence/signals, with paper applying `PAPER_*` dials and live applying `LIVE_*` dials from `.env` exactly. Live independence means "obey the live dials and audit the decision," not "freestyle outside config." Any migration must preserve long-only execution, managed-exit plans, live account readiness, kill switch, activation acknowledgement, broker support, final `LiveRiskGuard`, and bounded status/reporting that explains every live trade/skip/block reason.

Crypto momentum has separate paper/live env keys for audit clarity. The current follower runtime defaults armed live to paper values unless named differences are allowed; the target independent live lane should instead treat the live keys as the authoritative live dials.

## Broker Routing
- Active paper: Alpaca Paper and separate Trading 212 Paper equity lane.
- Approved live runtime today: Alpaca Live same-as-paper follower only.
- Target live runtime: Alpaca Live independent lane controlled exactly by `LIVE_*` `.env` dials after implementation, tests, reporting, and explicit activation.
- IG: scaffold/shadow only; no trade above `$10` notional or above `1x` leverage.
- Trading 212 Paper: paper/equity-only; 10 slots; broker-specific protection/evidence; duplicate client-order-id guard. No crypto, live money, shorts, or widened notional. Entries require configured UK symbol, real venue ticker, trusted latest-price/proposal provider, and GBX-to-GBP conversion before sizing. `positions_api` price seeds are only demo holdings: the seed command may place capped tiny paper buys, but seeds must not consume strategy slots, block same-symbol entries, or be auto-sold unless a filled Centaur managed buy exists.
- Trading 212 Live: readiness/config may exist, but real-money mutation is not approved. `TRADING212_LIVE_EXECUTION_ENABLED` must remain false unless separately approved with evidence/reporting/latest-price/final-live-guard review.
- Other providers: fail closed.

## Evidence / Storage
- PostgreSQL is the active operations store; fail closed rather than silently using SQLite when Postgres is configured or execution is enabled.
- Paper/live/core separation uses row-level provenance plus lane scaffolding; physical migration requires a checklist.
- Evidence rows must separate environment, mode, source environment, broker, data provider, and execution provider.
- Slack is notification-only; it may report alerts/reminders but must not accept commands or mutate live state.
