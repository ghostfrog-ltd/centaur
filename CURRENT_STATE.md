# Project Centaur Current State — Compact
Last compacted: 2026-05-31

## Runtime
- `ModeContext` centralises runtime/environment permission checks.
- `paper` mode skips live broker sync/order mutation.
- `live_dry` can read live broker state for readiness/risk review and records intended actions without submitting/cancelling live orders.
- Existing approved live follower resolves to `live` under legacy activation flags.

## Execution
- `ExecutionRouter` is the choke point before broker submit/cancel/mutation.
- `LiveRiskGuard` checks mode, activation, kill switch, broker, strategy where relevant, account/sync readiness, capacity, latest-bar/instrument availability, same-paper validation, and notional.
- Live-dry intents are persisted in `execution_router_intents` and surfaced in evidence reporting.

## Adapters / Instruments
- Active execution adapters: `alpaca_paper`, `alpaca_live`.
- IG and future vendors fail closed until implemented and approved.
- Alpaca market-data adapter boundary exists.
- Canonical instrument registry exists with `InstrumentRef` and venue mappings such as `ALPACA:BTC/USD`, `BINANCE:BTCUSDT`, `COINBASE:BTC-USD` mapping to canonical IDs.
- Broker orders, shadow proposals/outcomes, latest bars, historical bars, discovery candidates, and strategy signals carry derivable instrument metadata.

## Storage / Config
- PostgreSQL row-level provenance is active.
- Optional `POSTGRES_SCHEMA` is honoured.
- Storage lanes modelled as `core`, `paper`, and `live`; physical paper/live migration remains pending.
- `scripts/bootstrap_storage_lanes.py` prepares lane schemas/tables without switching active scheduler state.
- Runtime configuration is `.env` only, grouped into core, paper, and live sections. Mirrored live execution levers match paper by default; named live differences must be listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES` or config load fails closed while live is armed.

## App Architecture
- Target `app/` package exists for `core`, `engine`, `adapters`, `runtime`, `storage`, `reporting`, and `strategies`.
- First implementation ownership moved into `app/` for runtime mode context, live guard, execution router, execution adapters, market-data adapters, instruments, and storage layout.
- `app/` is now the only active package; the old `centaur/` package has been removed.

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
