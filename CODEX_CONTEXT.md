# Project Centaur — Codex Context

Purpose: compact read-first truth for safe work. Load history only when needed.

## Identity
- Centaur is an auditable trading research and micro paper/live execution system.
- Preserve capital first; optimise risk-adjusted, measurable growth.

## Prime Rules
1. Do not widen risk from the `$50/day` idea.
2. Keep decisions auditable, measurable, and data-attributable.
3. New evidence needs a report/status/query surface.
4. Safety-critical paths need comments/docstrings for gates and audit trails.

## Current Truth
- Architecture direction: LangGraph-first with Pydantic contracts; `ControlPipelineRunner` is migration scaffolding.
- Modes: `shadow`, `paper`, `live_dry`, `live`.
- PostgreSQL is the active operations store; fail closed rather than silently using SQLite when execution is enabled or Postgres is configured.
- `launchd` runs the supervised heartbeat via `.venv-mac`; ticks are sequential and reload `.env` and runtime storage each loop.
- Storage model: shared `core` evidence/fitness plus separate `paper` / `live` execution lanes.

## Execution Envelope
- Paper lanes: `alpaca_paper` and eligible `trading212_paper`.
- Live lane: independent Alpaca Live using `LIVE_*` dials exactly; still blocked unless live activation gates permit it.
- Long-only.
- Paper notional: `$10` unless explicitly approved; Trading 212 paper currently uses `£5`.
- Max orders per tick: `1`. Base slots: `10`.
- Paper daily equity protector: `$10.00`.
- Stale unfilled equity entries: reap after `5` minutes.
- Allowed execution strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`.
- Projected-gain floors: equities `1.5%`, crypto `2.0%`.
- Buffers: equities `5` bps `DAY`; crypto `25` bps `IOC`.
- Equity no-overnight carry: block final 15-minute entries; flatten in final 5 minutes.
- Live equity entries fail closed below the Alpaca PDT threshold.

## Strategy / Fitness
- Prefer deterministic, auditable logic over opaque AI.
- Shadow learning can be broad; paper/live are money-facing.
- Fast-path candidate split: only selected candidates go through same-tick enrichment and trade evaluation.
- Slow queue is advisory evidence only with `trade_authority=none`.
- Fast tick uses cached adaptive threshold state; heavy GA advice stays off the hot path.
- Crypto suppress threshold is fixed; equity threshold can adapt within paper-only rails.
- Paper/live admission is fitness-only on the fast execution path. Raw score remains ranking/reporting/shadow evidence only.
- Broker paper execution now requires a persisted manual promotion record at `paper_approved`; replay/paper-sim evidence may recommend but must not auto-enable paper trading.
- `main.py --research-cycle` now runs replay-only research, persists per-strategy/profile backtest evidence decisions, and updates promotion summaries without approving broker paper or live trading.
- `main.py --research-autopilot` now parks same-run `deprioritise_until_new_data` candidates, passes those run-scoped parked keys back into the portfolio planner so the same candidate is excluded for the rest of the run, replans for alternatives, and can execute allowlisted research-only runtime-prep commands such as replay dataset precompute steps when the planner surfaces or infers an exact safe command. If a candidate already completed precompute but still has weak post-precompute evidence, autopilot must park that candidate for the run and replan instead of re-emitting the same precompute action; operator-facing summaries now include explicit precompute-command mapping diagnostics.
- When `RESEARCH_CYCLE_ENABLED=true`, the supervised heartbeat can trigger the same safe research-cycle autonomously from the control step; this remains replay-only and must not place broker paper or live orders.
- Shadow-only research profiles must stay out of paper/live allowlists unless explicitly approved.
- `crypto_pullback.downside_reversal_watch` is a paper-research/watch-only crypto pullback profile. It emits non-executable `pullback_watch` proposals for diagnostics/evidence and must not be live-approved.
- `crypto_pullback.downside_continuation_watch` is a replay/reporting-only inverse interpretation of moderate downside pullbacks from `-0.15%` to `-1.00%`. It is research-only, stores no broker orders, and must not be promoted to paper/live without explicit approval.
- `crypto_pullback.extreme_drop_reversal_watch` is a replay/reporting-only segmentation for pullbacks worse than `-1.00%` where short-term reversal behavior is reviewed separately. It is research-only and non-executable.
- Replay summaries compare these two crypto pullback regimes explicitly, including low-sample warnings, symbol rankings, and checkpoint recommendations; this surface remains report-only.

## Broker Notes
- Execution adapter lookup resolves `alpaca_paper`, `alpaca_live`, `trading212_paper`, and disabled `trading212_live`.
- IG is scaffold/shadow only.
- Trading 212 Paper is paper equity only; Trading 212 Live remains mutation-disabled.

## Evidence / Reports
- Persist provenance for environment, mode, broker, providers, thresholds, and execution impact.
- Keep queries bounded and indexed.
- Label paper, live, shadow, observe-only, recent, and all-time evidence separately.

## Useful Commands
- `.venv-mac/bin/python -m unittest discover tests`
- `.venv-mac/bin/python main.py --status`
- `.venv-mac/bin/python main.py --heartbeat-autonomous-learning-once --force-research-cycle`
- `.venv-mac/bin/python main.py --real-learning-proof --run-fresh`
- `.venv-mac/bin/python main.py --evidence-report`
- `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --strategy-research-planner --base-strategy <strategy>`
- `.venv-mac/bin/python main.py --paper-candidate-decision-report`
- `.venv-mac/bin/python main.py --proposal-pipeline-diagnostics`
- `.venv-mac/bin/python main.py --promotion-status`
- `.venv-mac/bin/python main.py --promotion-evaluate --strategy-id <strategy> --profile-id <profile>`
- `.venv-mac/bin/python main.py --promotion-approve-paper --strategy-id <strategy> --profile-id <profile> --max-paper-notional <usd> --max-open-trades <n> --cooldown-minutes <n> --confirm-promotion-approval`
- `.venv-mac/bin/python main.py --promotion-reject --strategy-id <strategy> --profile-id <profile> --reason <text>`
- `.venv-mac/bin/python main.py --historical-bars-status`
- `.venv-mac/bin/python main.py --slow-enrichment-queue-process`
- `.venv-mac/bin/python main.py --slow-enrichment-queue-repair`
- `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --holding-window-advice`
- `.venv-mac/bin/python main.py --crypto-health`
- `.venv-mac/bin/python main.py --adapter-inventory`
- `.venv-mac/bin/python main.py --storage-separation-report`

## Work Rules
- Inspect the exact code path before changing behaviour.
- Read `CONSTRAINTS.md` for execution, risk, live, broker, storage, or persistence work.
- If orchestration nodes/edges change, run `.venv-mac/bin/python scripts/update_mermaid_visuals.py`.
- Update compact docs when runtime behaviour changes.
