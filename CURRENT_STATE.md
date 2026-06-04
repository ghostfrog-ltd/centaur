# Project Centaur Current State
Last compacted: 2026-06-04

## Runtime
- `ModeContext` centralises runtime/environment permission checks.
- `paper` mode skips live broker sync/order mutation.
- `live_dry` can read live broker state for readiness/risk review and records intended actions without submitting/cancelling live orders.
- Existing approved live follower resolves to `live` under legacy activation flags.
- Target direction recorded on 2026-06-04: live should become an independent lane controlled exactly by `LIVE_*` `.env` dials, not a blind copy of paper.

## Execution
- `ExecutionRouter` is the choke point before broker submit/cancel/mutation.
- Current `LiveRiskGuard` checks mode, activation, kill switch, broker, strategy where relevant, account/sync readiness, capacity, latest-bar/instrument availability, same-paper validation, and notional.
- Target live-lane work should replace the same-paper entry dependency with lane-specific live proposal/risk approval while preserving the final live guard and reporting every live trade/skip/block reason.
- Live-dry intents are persisted in `execution_router_intents` and surfaced in evidence reporting.

## Adapters / Instruments
- Execution adapter lookup resolves `alpaca_paper`, `alpaca_live`, `trading212_paper`, and disabled `trading212_live`.
- Alpaca Live is same-as-paper only in the current runtime; target runtime is independent Alpaca Live proposals governed by `LIVE_*` dials after implementation/testing/reporting/activation. Trading 212 Paper is paper/equity-only; Trading 212 Live and IG/future vendors fail closed for mutation until approved.
- Canonical instrument registry persists `InstrumentRef`, canonical IDs, venue, and venue symbols across broker orders and evidence where derivable.

## Storage / Config
- PostgreSQL row-level provenance is active.
- Optional `POSTGRES_SCHEMA` is honoured.
- Storage lanes modelled as `core`, `paper`, and `live`; physical paper/live migration remains pending.
- `scripts/bootstrap_storage_lanes.py` prepares lane schemas/tables without switching active scheduler state.
- Runtime configuration is `.env` only, grouped into core, paper, and live sections. Current follower runtime mirrors live execution levers to paper by default and fails closed on unnamed differences. Target independent-lane runtime should treat `PAPER_*` as paper authority and `LIVE_*` as live authority, with status/reporting showing the exact dials used.

## App Architecture
- `app/` is the only active package; old `centaur/` has been removed.
- Heartbeat orchestration lives in `app/heartbeat/` with a typed LangGraph/Pydantic graph and step folders that mirror generated Mermaid order.
- Compatibility imports route through `app/framework/engine/control_graph.py`.

## Operations
- Launchd runs on `/Volumes/Bob/www/ghostfrog-centaur` using `.venv-mac`.
- Control tick target: 30 seconds, skip-if-busy.
- Dashboard snapshot refresh is separate: every 300 seconds, skip-if-busy.
- `CONTROL_REFRESH_DASHBOARD_SNAPSHOT=false` keeps normal control ticks from waiting on dashboard/report work.

## Reporting
Use:
- `main.py --status`
- `main.py --evidence-report`
- `main.py --strategy-health --strategy-id <strategy>`
- `main.py --paper-exit-review --strategy-id <strategy>`
- `main.py --holding-window-advice`
- `main.py --crypto-health`
- `main.py --adapter-inventory`
- `main.py --storage-separation-report`
