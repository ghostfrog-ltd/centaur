# Project Centaur Skills

This file captures reusable playbooks for common Centaur tasks.

## Skill: Read-First Alignment
Before changing code or behavior:
1. Read `AGENTS.md`
2. Read `CONSTRAINTS.md`
3. Read `DECISION_LOG.md`
4. Read `PROGRESS.txt`
5. Check the relevant code paths before editing

## Skill: Safe Paper Execution Checks
When working on Alpaca paper execution:
1. Confirm the task does not violate `CONSTRAINTS.md`
2. Inspect `risk_cfo_gate()` in `centaur/pipelines.py`
3. Inspect `_build_paper_trade_approval()` in `centaur/pipelines.py`
4. Preserve `$10` notional unless a human explicitly overrides it
5. Preserve the current asset-class and market-window rules unless explicitly overridden again
6. Keep all broker payloads persisted to PostgreSQL
7. Preserve the minimum projected-gain floor unless a human explicitly changes it
8. Keep fractional-equity order styles aligned with Alpaca's supported time-in-force rules
9. Preserve the daily equity-drawdown protector and stale-order reaper unless a human explicitly changes them
10. Preserve the currently configured broker routing unless a human explicitly overrides it
11. Preserve the strategy-allocation suppress threshold unless a human explicitly overrides it

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

## Skill: Dashboard Honesty
When changing dashboard or status behavior:
1. Avoid misleading aggregates
2. Keep recent activity and all-time training volume separate
3. Show zero-data states explicitly
4. Prefer truthful labels over pretty but ambiguous visuals

## Skill: Durable Memory Update
When a major behavior changes:
1. Update `PROGRESS.txt`
2. Update `docs/PROJECT_RECORD.md` if operating reality changed
3. Update `docs/DECISION_LOG.md` if an architectural or policy decision changed
4. Keep root reliability-stack files aligned with the current repo
