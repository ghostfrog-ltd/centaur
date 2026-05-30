# Project Centaur Skills

This file captures reusable playbooks for common Centaur tasks.

## Skill: Read-First Alignment
Before changing code or behavior:
1. Read `AGENTS.md`
2. Read `CONSTRAINTS.md`
3. Read `DECISION_LOG.md`
4. Read `PROGRESS.txt`
5. Check the relevant code paths before editing
6. For unattended scheduler changes, keep the live wrapper, launch agent interval, and lock/skip behavior aligned so the configured cadence matches real operation
7. For safety-critical trading paths, keep docstrings/comments aligned with the current gate, risk boundary, and audit trail

## Skill: Safe Paper Execution Checks
When working on Alpaca paper execution:
1. Confirm the task does not violate `CONSTRAINTS.md`
2. Inspect `risk_cfo_gate()` in `centaur/pipelines.py`
3. Inspect `_build_paper_trade_approval()` in `centaur/pipelines.py`
4. Preserve `$10` notional unless a human explicitly overrides it
5. Preserve the current asset-class and market-window rules unless explicitly overridden again
6. Keep all broker payloads persisted to PostgreSQL
7. Preserve the minimum projected-gain floors unless a human explicitly changes them; the current paper rules are `1.5%` for equities and `2.0%` for crypto
8. Preserve the paper profit-capture rule unless a human explicitly changes it; the current paper managed-exit capture is `1.25%` and does not replace the entry projected-gain floor
9. Keep fractional-equity order styles aligned with Alpaca's supported time-in-force rules, and keep the equity and crypto marketable-limit buffers separate unless a human explicitly changes them
10. Preserve the daily equity-drawdown protector and stale-order reaper unless a human explicitly changes them
11. Preserve the currently configured broker routing unless a human explicitly overrides it
12. Preserve the strategy-allocation suppress thresholds unless a human explicitly overrides them; equities and crypto may now use different paper suppress lines
13. Preserve the paper high-score near-miss override unless a human explicitly changes it; it only applies to already allowed paper strategies with raw `signal_score >= 90.0` and composite fitness within `0.25` of the active threshold
14. Preserve the current adaptive cliff-governor safety gap unless a human explicitly overrides it

## Skill: First Profitability Check
When Centaur is not making profit, or when the operator sees repeated small wins turn into losses, check exits before changing entries:
1. First ask whether the target or holding window is too ambitious for `$10` micro trades
2. Compare actual paper exits with `15m`, `1h`, `1d`, and `7d` shadow outcomes
3. Check whether small positive moves were available before the final exit turned flat or negative
4. Check whether the current profit-capture rule is firing and whether broker fills confirm it
5. Check the shadow profit-target ladder to see whether higher targets such as `2%`, `3%`, `4%`, or `6%` would have hit after the current `1.25%` capture
6. Only after that review should you consider loosening entry thresholds, suppress thresholds, strategy allowlists, or discovery knobs
7. Treat this as a capital-preservation check: a system can have acceptable entries and still lose because it waits for unrealistic exits

## Skill: Broker Refactor
When changing execution toward multi-broker support:
1. Keep the currently working Alpaca path stable first
2. Move broker-specific execution behavior behind a broker adapter before changing risk policy
3. Tag persisted trade records with `broker_id`
4. Keep inactive brokers scaffold-only until their constraints are explicit
5. Veto any new broker path that cannot honor the repo notional and leverage rules
6. Do not silently mix account or trade history from different brokers
7. Treat `alpaca_live` as scaffold-only until the go-live checklist and constraints explicitly allow live order submission

## Skill: Historical Replay
When building evidence quickly:
1. Prefer replay over waiting for live ticks
2. Use chunked replay for larger windows
3. Check both proposal counts and evaluated outcomes
4. Distinguish recent-window charts from all-time totals

## Skill: Paper Exit Review
When reviewing whether current paper exits are making good decisions:
1. Run `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>` for the combined operator view when you need paper P/L, exit reasons, proposal flow, and raw-vs-suppressed strategy activity in one place
2. Run `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
3. Compare recent and all-time `1h` versus `1d` deltas separately, and include `7d` checkpoints when they are available
4. Treat recent drift as a hypothesis, not an automatic policy change
5. Cross-check with `.venv-mac/bin/python main.py --holding-window-advice`
6. Do not change managed paper exits without explicit human approval

## Skill: Crypto Overnight Check
When reviewing whether Centaur is actually seeing crypto overnight:
1. Run `.venv-mac/bin/python main.py --crypto-health`
2. Check whether the configured crypto universe count matches the expected live symbol list
3. Check whether recent `crypto_only_window` ticks are fetching bars
4. Compare ticks with crypto raw previews versus crypto suppressed previews
5. Check which crypto symbols are appearing as selected overnight candidates versus actual crypto strategy previews
6. Treat quiet overnight crypto as either weak candidate quality or fitness suppression before assuming the scheduler or market-hours gate is broken

## Skill: Managed Exit Override
When changing a managed paper exit rule by explicit human override:
1. Preserve stop loss, target, notional, broker routing, and CFO approval rules unless separately overridden
2. Persist the new exit policy in the paper-order plan metadata
3. Surface the active exit policy in status/dashboard views
4. Update `CONSTRAINTS.md`, `DECISION_LOG.md`, `docs/DECISION_LOG.md`, and `PROGRESS.txt` in the same task

## Skill: Dashboard Honesty
When changing dashboard or status behavior:
1. Avoid misleading aggregates
2. Keep recent activity and all-time training volume separate
3. Show zero-data states explicitly
4. Prefer truthful labels over pretty but ambiguous visuals
5. If Centaur is running headless, keep dashboard snapshot refresh off the critical control-tick path; prefer manual or separately scheduled snapshot generation

## Skill: Durable Memory Update
When a major behavior changes:
1. Update `PROGRESS.txt`
2. Update `docs/PROJECT_RECORD.md` if operating reality changed
3. Update `docs/DECISION_LOG.md` if an architectural or policy decision changed
4. Keep root reliability-stack files aligned with the current repo
