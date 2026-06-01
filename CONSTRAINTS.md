# Project Centaur Constraints — Compact

## Hard Nos
- Do not use the `$50/day` target to bypass risk controls, widen notional, add slots, loosen gates, change brokers, or alter live behaviour.
- No live-money trading outside the recorded 2026-05-29 Alpaca Live same-as-paper override.
- No Alpaca Live entry unless live enablement, kill switch, credentials, activation acknowledgement, readiness, same-paper validation, and live guard all pass.
- No paper trade above `$10` notional without explicit approval.
- No silent broker switch.
- No unsupported direction changes; current execution is long-only.
- No paper order when kill switch is on, daily drawdown protector has triggered, market-hours rules block equities, or slots/orders are full.
- No raw chain-of-thought logging.
- No contradiction of constraints/decision log without human override.
- No safety-critical trading path without clear comments/docstrings.
- No evidence capture without a report/dashboard/status/query surface.
- No high-volume persistence path without bounded queries/index discipline.

## Active Paper Envelope
- Broker: `alpaca_paper`.
- Asset classes: equities and crypto.
- Notional: `$10` exactly unless overridden.
- Max orders per tick: `1`.
- Base slots: `10`.
- Earned slots: +1 per full `$10` tracked P/L above baseline; dynamic and can fall away.
- Daily equity drawdown protector: `$5.00`.
- Long-only.
- Allowed strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`.
- Projected-gain floors: equities `1.5%`, crypto `2.0%`.
- Crypto momentum stop: `1.0%`; crypto remains enabled, but future `$10` crypto losses should be capped near `$0.10` before slippage/fill drift.
- Crypto momentum candidate gates: require instrument identity, reject movement above `2.5%`, reject derived/supplied notional volume below `£50,000`, and reject spreads above `0.25%` when spread data is available.
- Limit buffer: equities `5` bps, crypto `25` bps.
- Equity fractional orders: `DAY` limits.
- Crypto orders/exits: `IOC` limits.
- Stale unfilled equity entries: reap after `5` minutes.
- Profit capture: `1.25%` managed exit; does not lower entry floors.
- Aggregated same-symbol managed positions must use the most protective still-open entry stop for exits, because the broker exposes one long position even when Centaur entered multiple lots.
- Profit-target ladder evidence: `1.25,2,3,4,6` percent.
- Max-hold red deferral: do not sell red solely due to elapsed max-hold for `profit_after_1h_else_1d` or `profit_capture_else_1d`.
- Equity no-weekend-carry: block new Friday equity entries in final 60 minutes; flatten managed equity positions in final 15 minutes. Crypto unchanged.
- Alpaca Live equity PDT guard: new live equity entries fail closed unless the live account proves prior/effective equity at or above `$25,000`; this avoids entering positions whose same-day exits may be broker-rejected. Existing live exits still route when the broker permits them. Crypto is not blocked by this PDT guard. Alpaca announced a new intraday-margin framework for 2026-06-04, but do not auto-unblock on date alone; require observed API/account behavior and explicit review.

## Live Lane
Alpaca Live is approved only as a same-as-paper follower. It must not invent live-only thresholds, order limits, strategies, asset classes, broker routing, or notional. The final live guard is a real-money safety boundary, not a strategy engine.

Crypto momentum tuning has separate paper/live environment keys for testing and audit clarity, but armed live still defaults to paper values and must fail closed on unnamed live-vs-paper differences.

## Broker Routing
- Active: Alpaca Paper.
- Approved live follower: Alpaca Live, same-as-paper only.
- IG: scaffold/shadow only; no IG trade may exceed `$10` notional or imply more than `1x` leverage.
- Trading 212 Paper: approved for paper equity execution only. It has its own 10 base slots, fixed `£10` native order sizing, broker-specific protection/evidence, and duplicate client-order-id guard. Do not route crypto, live money, short selling, or widened notional through Trading 212.
- Other providers: not implemented; fail closed.

## Evidence And Storage
- PostgreSQL is the active operations store.
- If PostgreSQL is configured or execution is enabled, fail closed rather than silently using SQLite.
- Paper/live/core separation is currently row-level provenance plus lane scaffolding; physical migration requires a checklist.
- Evidence rows must carry enough provenance to separate environment, mode, source environment, broker, data provider, and execution provider.
- Slack is notification-only. It may report broker/risk alerts and action-required reminders, but must not accept commands or mutate live trading state.
