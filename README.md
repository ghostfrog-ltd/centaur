# Project Centaur

Project Centaur is a pipeline-first trading research and micro paper-trading system. It scans equity and crypto markets, creates deterministic strategy signals, scores them with stored shadow/paper outcomes, applies strict CFO/risk gates, and submits tiny Alpaca Paper orders only when the configured constraints allow it.

Centaur is built for auditable learning, not reckless automation. The current operating goal is to prove that a small, tightly controlled trading loop can stay active, measurable, and capital-preserving before any live-money discussion.

## Current Status

- Runtime: Python control pipeline, scheduled locally by macOS `launchd`
- Operations store: PostgreSQL
- Dashboard: DDEV/OrbStack web dashboard at `https://ghostfrog-centaur.ddev.site`
- Active broker: Alpaca Paper
- Live broker: Alpaca Live dormant follower lane, safe-off by default
- Paper trade size: `$10`
- Base paper slots: `10`
- Earned-slot rule: each full `$10` of tracked paper P/L earns one extra `$10` slot
- Gemini analysis: adapter present, live runtime currently disabled for cost control

Live-money trading is not active. API keys alone must not activate live trading.

## Safety Rules

Read these before changing behaviour:

- [AGENTS.md](AGENTS.md)
- [CONSTRAINTS.md](CONSTRAINTS.md)
- [DECISION_LOG.md](DECISION_LOG.md)
- [SKILL.md](SKILL.md)
- [PROGRESS.txt](PROGRESS.txt)

Important current constraints:

- No live-money order submission without a separate go-live override.
- No paper trade above `$10` notional without explicit approval.
- No silent broker switch.
- No silent risk widening.
- No new paper entry after the daily drawdown protector has triggered.
- Equities require market hours when configured.
- Current paper execution is long-only.

## Architecture

The default control tick is an explicit sequence of pipeline steps:

1. Account, clock, positions, and order sync
2. Paper/live protection checks
3. Market gate and latest bar collection
4. Managed exit checks
5. Shadow outcome evaluation
6. Strategy fitness scoring
7. Market scan and context enrichment
8. Strategy signal generation
9. Shadow proposal creation
10. Paper CFO approval
11. Paper execution
12. Dormant live follower approval/execution
13. Post-trade evaluation and diagnostics

The system keeps the shared trade brain separate from account-specific execution. Paper and future live can see the same signal, but each account must pass its own position, order, slot, drawdown, kill-switch, and broker checks.

## Key Commands

Run one control tick:

```bash
.venv-mac/bin/python main.py
```

Show current status:

```bash
.venv-mac/bin/python main.py --status
```

Run threshold advice:

```bash
.venv-mac/bin/python main.py --threshold-advice
```

Run holding-window advice:

```bash
.venv-mac/bin/python main.py --holding-window-advice
```

Run historical replay:

```bash
.venv-mac/bin/python main.py --replay
```

Start DDEV:

```bash
ddev start
```

## Configuration

Local secrets and runtime values live in `.env`, which is intentionally ignored by Git. Use `.env.example` as the committed template.

Current important environment areas:

- Alpaca Paper credentials
- Alpaca Live credentials, currently inactive by default
- PostgreSQL connection
- paper execution limits
- live execution gates
- strategy threshold/adaptive settings
- Gemini API settings

The live lane requires more than credentials. A future go-live review must explicitly set live enablement, disable the live kill switch, provide `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`, configure a live strategy allowlist, and record rollback conditions.

## Dashboard

The primary dashboard is the DDEV/OrbStack web app:

```text
https://ghostfrog-centaur.ddev.site
```

It reads the host-written dashboard snapshot from:

```text
var/dashboard_snapshot.json
```

That file is runtime output and is ignored by Git.

## Git Hygiene

Ignored by default:

- `.env`
- virtualenvs
- Python caches
- runtime logs
- `var/` snapshots and SQLite files
- IDE and OS noise

Trackable by default:

- source code
- docs
- scripts
- web dashboard files
- `.env.example`
- DDEV project config

## Durable Project Memory

Long-lived project history lives in:

- [docs/PROJECT_RECORD.md](docs/PROJECT_RECORD.md)
- [docs/DECISION_LOG.md](docs/DECISION_LOG.md)
- [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)
- [docs/STRATEGY_SELECTION_CHECKLIST.md](docs/STRATEGY_SELECTION_CHECKLIST.md)

When runtime behaviour or risk policy changes, update the reliability stack in the same task.

## Disclaimer

Centaur is a research and paper-trading system. Paper results are exploratory and may not translate to live execution. Live trading involves real risk, including slippage, rejected orders, partial fills, changing market regimes, and loss of capital.
