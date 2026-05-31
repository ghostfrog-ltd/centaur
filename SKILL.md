# Project Centaur Skills — Compact

## Read-First Alignment
1. Read `CODEX_CONTEXT.md` first.
2. Inspect the relevant code path before editing.
3. Read `CONSTRAINTS.md` if touching risk, paper/live execution, broker routing, scheduler, storage, or persistence.
4. Read detailed decision history only when the task depends on historical intent.
5. Stop for human override if the request conflicts with constraints or logged decisions.

## Adapter-First Refactor
- Treat Alpaca as the first adapter, not the product boundary.
- Keep strategy, fitness, risk, slots, exits, reports, and order intents in Centaur core.
- Put vendor market data, execution, broker/account, capabilities, and symbol mapping behind adapters.
- Use explicit modes: `shadow`, `paper`, `live_dry`, `live`.
- Keep paper/live config, persistence, evidence, logs, permissions, and runtime state separated.
- Preserve PostgreSQL-only active operation.
- Require `ExecutionRouter` and final live guard before any live broker mutation.

## Evidence Capture
When adding learning/evidence data:
1. Define the question being answered.
2. Store context: mode, environment, broker, data provider, execution provider, thresholds, and whether execution was affected.
3. Add to `--evidence-report` or a specific report command.
4. Clearly label observe-only/counterfactual data.
5. Add indexes/bounded lookbacks for report queries.
6. Document interpretation guidance.

## Safe Paper Execution
Before changing paper execution:
- Inspect `risk_cfo_gate()` and `_build_paper_trade_approval()`.
- Preserve `$10` notional, long-only, projected-gain floors, broker routing, daily protector, stale reaper, strategy allowlist, and no-weekend/max-hold red rules unless explicitly overridden.
- Preserve separate equity/crypto limit buffers.
- Do not promote observe-only trailing drawdown into a blocker without approval.

## First Profitability Check
When performance is weak:
1. Check exits before entries.
2. Compare actual exits with `15m`, `1h`, `1d`, and `7d` shadow outcomes.
3. Review whether small positive moves existed before final losses.
4. Check stale/non-marketable exits and fill behaviour.
5. Check the profit-target ladder.
6. Only then consider thresholds, discovery knobs, or strategy allowlists.

## $50/Day Scaling
- Treat `$50/day` as prioritisation only.
- Improve throughput and expectancy before increasing size.
- Expansion requires evidence, clean drawdown behaviour, clean exits, enough proposals to use capacity, explicit approval, and doc updates.
- Preserve `$10` notional unless separately approved.
