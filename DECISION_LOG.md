# Project Centaur Decision Log — Compact Rolling Head

This is the short rolling decision head. Keep the full canonical history in `docs/DECISION_LOG.md`, but do not load it for every task.

## 2026-06-03
- Operator approved raising the paper/live daily equity drawdown protector from `$1.00` to `$2.00` for the active Alpaca Paper, Trading 212 Paper, and Alpaca Live same-as-paper lanes.
- Rationale: the recent `$10` micro-trade/10-slot paper evidence showed normal open-P/L noise around `$1.35-$1.80`, making `$1.00` too likely to halt new entries before enough throughput can be observed.
- This widens only the daily entry-protection latch. It does not widen notional, slots, strategies, broker routing, order frequency, projected-gain floors, long-only policy, or live independence.

## 2026-06-01
- Architecture constraint tightened from "pipeline-first, LangGraph-compatible" to LangGraph-first with Pydantic-backed state and node contracts.
- Current `ControlPipelineRunner` remains the behaviour-preserving migration scaffold, but new orchestration work should not deepen untyped dict-only pipeline control flow when a typed graph node/model is practical.
- Graph visualization/export is now part of orchestration discipline: update generated/visual docs when nodes or edges change.
- Generated orchestration visuals must remain code-aware: runtime nodes should expose source module/function or typed graph ownership and be grouped by the relevant `app/` domain boundary so diagrams do not drift away from code/folder structure.
- This is an architecture/documentation constraint only; it does not approve any change to notional, thresholds, broker routing, paper/live behaviour, strategy allowlists, or risk gates.

## 2026-05-31
- Runtime provenance now labels environment/mode/source/data-provider/execution-provider across shadow proposals/outcomes, broker orders, and strategy fitness where relevant.
- Explicit `CENTAUR_MODE=paper` skips live broker sync and live order mutation. `live_dry` can record intended live actions without broker mutation.
- Existing approved live follower remains active because legacy activation resolves runtime to `live`.
- `ModeContext`, `ExecutionRouter`, and `LiveRiskGuard` are core safety boundaries.
- Canonical instrument registry and `InstrumentRef` foundation exist; venue symbols can map to canonical instruments.
- Market-data and execution adapter boundaries exist; active execution adapters are only `alpaca_paper` and `alpaca_live`.
- IG, Binance, Coinbase, Polygon, and other providers remain scaffold/not implemented and must fail closed.
- Storage is modelled as `core`, `paper`, and `live` lanes. Current implementation is PostgreSQL row-level provenance; physical split remains pending.
- `POSTGRES_SCHEMA` is honoured by operations storage.
- `scripts/bootstrap_storage_lanes.py` prepares lane schemas/tables without switching active operation.
- Runtime configuration is `.env` only, grouped into core, paper, and live sections. Mirrored live execution levers match paper by default; named live differences must be listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES` or config load fails closed while live is armed.
- `app/` package now owns the runtime/adapters/instruments/storage/reporting/strategy implementation; the old `centaur/` package has been removed.
- Live-dry order-action intents persist in `execution_router_intents` and appear in `--evidence-report`.
- Operator clarified Alpaca Live should be exactly paper, but live; no separate live-only threshold or max-daily-order policy.
- Dashboard/status/reporting labels were tightened so paper, live, shadow, recent, all-time, broker-ledger, and observe-only evidence are not blurred.
- Database/reporting indexes were added for regular status, dashboard, evidence, strategy-health, paper-exit, and holding-window paths.
- PostgreSQL enforcement tightened: when Postgres is configured or execution is enabled, fail closed instead of silently falling back to SQLite.
- New core directive: every new evidence/data-capture feature needs a runnable evidence surface and query/index discipline.
- Trailing drawdown/high-water observer added as observe-only only.
- Max-hold red deferral approved: do not sell red solely due to elapsed max-hold for `profit_after_1h_else_1d` or `profit_capture_else_1d`.
- Equity no-weekend-carry guard approved: block final-60-minute Friday equity entries and flatten final-15-minute managed equity positions. Crypto unchanged.

## 2026-05-29
- GO-LIVE OVERRIDE: operator explicitly approved Alpaca Live same-as-paper follower lane.
- Launch envelope: same current paper strategies, equities plus crypto, `$10` entries, 10 base slots, one order per tick, `$5` daily protector, shared paper/shadow fitness, read-only live execution intelligence.
- Live account pre-check: active, funded around `$132.05`, no positions, no recent/open orders. `$100` is operating bankroll; extra funds are buffer.
- Live activation flags were set: `LIVE_EXECUTION_ENABLED=true`, `LIVE_EXECUTION_KILL_SWITCH=false`, `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`.
- First live-enabled observed tick submitted zero live orders because there was no paper-approved trade to follow.

## 2026-05-28
- Paper managed exits may capture profit at `1.25%` for equities and crypto.
- Profit-target ladder records `1.25`, `2`, `3`, `4`, and `6` percent counterfactuals.
- Crypto marketable-limit buffer split to `25` bps; equities remain `5` bps.
- `crypto_momentum.trend` exit mode changed to `profit_capture_else_1d`.
- High-score near-miss paper override added for allowed strategies with raw score at least `90` and composite fitness within `0.25` of threshold.
- Crypto discovery floor lowered from `4.5` to `2.5` without changing risk envelope.

## 2026-05-27 And Earlier Key State
- Launchd cadence tightened to 30 seconds with skip-if-busy locking.
- Dashboard snapshot refresh moved out of normal control tick.
- Crypto universe widened to 11 USD pairs.
- Crypto got separate conservative knobs and fixed suppress threshold.
- Equity adaptive threshold rails tightened to block weak drift while keeping paper active.
- Paper has earned-slot compounding: +1 slot per full `$10` tracked P/L above baseline, while per-trade notional stays `$10`.
