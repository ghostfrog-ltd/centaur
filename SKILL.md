# Project Centaur Skills

This file captures reusable playbooks for common Centaur tasks.

## Skill: Read-First Alignment
Before changing code or behavior:
1. Read `AGENTS.md`
2. Read `CONSTRAINTS.md`
3. Read `DECISION_LOG.md`
4. Read `centaur-codex-architecture-instructions.md`
5. Read `PROGRESS.txt`
6. Check the relevant code paths before editing
7. For unattended scheduler changes, keep the live wrapper, launch agent interval, and lock/skip behavior aligned so the configured cadence matches real operation
8. For safety-critical trading paths, keep docstrings/comments aligned with the current gate, risk boundary, and audit trail
9. For any new evidence/data-capture feature, add or update the report/dashboard/status surface that will make the data reviewable later
10. For any new persistent data path, check the query shape and add indexes or bounded lookbacks so reporting and ticks do not create database drag
11. If PostgreSQL is configured, or paper/live execution is enabled, treat SQLite fallback as unsafe and fail closed rather than continuing against the wrong operations store

## Skill: Adapter-First Architecture
When refactoring Centaur toward pluggable vendors:
1. Start from `centaur-codex-architecture-instructions.md`
2. Treat Alpaca as the first adapter, not the product boundary
3. Keep strategy, fitness, risk, slot logic, exits, reports, and order intents in shared Centaur core code
4. Put vendor market-data, execution, broker/account, and symbol-mapping behavior behind adapters
5. Use explicit runtime modes (`shadow`, `paper`, `live_dry`, `live`) rather than branch names, API-key names, folder names, or inferred database names
6. Keep paper and live configuration, persistence, evidence, logs, permissions, and runtime state separated
7. Preserve PostgreSQL-only live operations; do not implement the architecture examples using SQLite database files for paper/live execution
8. Require an `ExecutionRouter` plus final live guard before any live order can reach a broker adapter

## Skill: Evidence Capture And Reporting
When adding features that collect data for learning:
1. Define the question the data is meant to answer
2. Persist enough context to audit the answer later, including mode, thresholds, and whether the feature affected execution
3. Add the stream to `.venv-mac/bin/python main.py --evidence-report` or a more specific report command in the same task
4. Keep observe-only/counterfactual data clearly labeled so it is not mistaken for active trading policy
5. Document the interpretation rule in `docs/DECISION_LOG.md`, `PROGRESS.txt`, or the relevant operator doc
6. Use indexed/bounded queries for reports and avoid adding unbounded database reads to the normal control tick

## Skill: $50/Day Scaling Work
When working on the `$50/day` strategic target:
1. Start from `docs/FIFTY_DOLLAR_DAY_PLAN.md`
2. Treat the target as a prioritization goal, not permission to widen risk
3. Improve valid trade throughput before increasing size
4. Improve average net expectancy toward `1.0%` per closed `$10` trade using evidence reports before changing exits or thresholds
5. Treat `latest_bar_unavailable`, stale exits, and managed-exit reliability issues as blockers before slot/capital expansion
6. Use staged promotion gates for any slot increase: positive realized expectancy, clean drawdown evidence, clean exit behavior, enough proposals to use capacity, explicit approval, and reliability-stack updates
7. Preserve `$10` per-trade notional unless the operator explicitly approves a separate risk-envelope change

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
15. Preserve the equity no-weekend-carry guard unless a human explicitly changes it; current paper rules block new equity entries in the final `60` minutes of the regular Friday session and flatten managed equity positions in the final `15` minutes
16. Preserve the max-hold red deferral unless a human explicitly changes it; max-hold may not be the sole reason to sell a red `profit_after_1h_else_1d` or `profit_capture_else_1d` managed position
17. Treat the trailing drawdown observer as evidence-only unless a separate explicit human override promotes it into an entry blocker; observe-only output must not affect paper or live execution

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
1. Run `.venv-mac/bin/python main.py --evidence-report` first when the user asks for a broad report, so every active shadow/counterfactual stream is listed before narrowing the diagnosis
2. Run `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>` for the combined operator view when you need paper P/L, exit reasons, proposal flow, and raw-vs-suppressed strategy activity in one place
3. Run `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
4. Compare recent and all-time `1h` versus `1d` deltas separately, and include `7d` checkpoints when they are available
5. Treat recent drift as a hypothesis, not an automatic policy change
6. Cross-check with `.venv-mac/bin/python main.py --holding-window-advice`
7. Do not change managed paper exits without explicit human approval
8. Treat Friday equity exits separately from ordinary `1d` backstops, because `friday_no_weekend_carry` is meant to avoid calendar-time weekend drift rather than judge a Monday recovery window
9. Treat `max_hold_red_deferred` as a live risk signal to review, not as proof the position is safe; stop loss and profit exits remain the active deterministic exits
10. Review `trailing_drawdown_observer` tick snapshots before considering an active giveback guard, because the first implementation is deliberately counterfactual

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
