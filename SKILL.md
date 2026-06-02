# Project Centaur Skill

## Read First
1. `CODEX_CONTEXT.md`
2. Relevant source path
3. `CONSTRAINTS.md` when touching risk, paper/live execution, broker routing, scheduler, storage, or persistence
4. Decision history only when historical intent matters

Stop for human override if a request conflicts with constraints or logged decisions.

## Design Bias
- Adapter-first: Alpaca/Trading 212 are lanes, not product boundaries.
- Core owns strategy, fitness, risk, slots, exits, reports, instruments, evidence, and order intents.
- Vendors own market data, execution formatting, broker/account state, capabilities, and symbol mapping.
- Use explicit modes: `shadow`, `paper`, `live_dry`, `live`.
- Keep paper/live config, persistence, evidence, logs, permissions, and runtime state separated.
- Preserve PostgreSQL-only active operation and require `ExecutionRouter` plus final live guard before live broker mutation.

## Evidence
For new evidence, define the question; store mode/env/broker/providers/thresholds/execution impact; expose `--evidence-report` or a specific report; label observe-only/counterfactual data; add bounded/indexed queries; document interpretation.

## Paper Execution
Before changing paper execution, inspect `risk_cfo_gate()` and `_build_paper_trade_approval()`. Preserve `$10` notional, long-only, projected-gain floors, broker routing, daily protector, stale reaper, allowlist, no-weekend carry, max-hold red rules, and separate equity/crypto buffers unless explicitly approved. Do not promote observe-only trailing drawdown without approval.

## Profitability Triage
When performance is weak: check exits before entries; compare actual exits with `15m`, `1h`, `1d`, `7d` shadow outcomes; review small positive moves before losses; inspect stale/non-marketable exits and fills; check the profit ladder; only then consider thresholds, discovery knobs, or allowlists.

## `$50/Day`
Treat `$50/day` as prioritisation only. Increase throughput/expectancy before size. Expansion needs evidence, clean drawdown/exits, enough proposals to use capacity, explicit approval, and doc updates. Preserve `$10` notional unless approved.
