# Project Centaur Architecture Instructions for Codex

Last updated: 2026-05-31

## Purpose

Refactor Project Centaur so it is not hard-wired to Alpaca.

Centaur should become a market prediction, signal, fitness, risk, and execution engine with pluggable adapters for future vendors such as Alpaca, Binance, Coinbase, Betfair, Polygon, or other data/execution providers.

The immediate implementation should still support Alpaca paper/live trading, but the file structure and interfaces must make future adapters easy to add without rewriting the strategy, fitness, risk, or dashboard logic.

## Implementation Progress

Status as of 2026-05-31:

Done:
- `CENTAUR_MODE` / `CENTAUR_ENVIRONMENT` exist and status/evidence rows carry runtime provenance.
- `live_dry` is a live-environment dry-run mode that may read live broker state but must not submit or mutate live orders.
- Explicit paper mode skips Alpaca Live broker sync and live order-mutation paths.
- `ExecutionRouter` exists for entry orders, managed exits, and stale-order cancellations, with paper submission/cancellation and live-dry intent handling.
- `LiveRiskGuard` exists immediately before live entry, exit, and cancel actions; it re-checks runtime mode, live enablement, kill switch, activation acknowledgement, live broker id, strategy permission where relevant, live account/sync readiness, live entry capacity, live latest-bar availability, live instrument/venue permission where derivable, same-paper-order validation where relevant, and entry notional.
- `live_dry` router decisions now record intended entry/exit/cancel actions in tick state instead of treating them as broker errors.
- `live_dry` and shadow router intents are also persisted in `execution_router_intents` and summarized by `--evidence-report`, so dry-run action review survives beyond one tick snapshot.
- `--storage-separation-report` exists as a bounded read-only paper/live provenance report. It samples recent broker-order, shadow-proposal, and strategy-fitness rows, confirms required runtime/source metadata, and makes clear that the current storage boundary is row-level provenance on PostgreSQL while physical paper/live database or schema separation is still pending.
- By operator clarification on 2026-05-31, Alpaca Live should be exactly the paper lane, but live. Do not add separate live-only trade-count or bar-age policy knobs unless explicitly requested. Live-only checks are limited to activation, kill switch, account/sync readiness, broker identity, and same-paper-order validation.
- `POSTGRES_SCHEMA` is now honored by the operations store. When configured, `UsageLedger` creates/uses that schema and reports it in backend detail, giving paper/live deployments a schema-level separation path without changing the current shared-schema runtime when unset.
- A first-class storage layout model now records `core`, `paper`, and `live` lanes. `core` is the shared reviewed evidence/fitness/instrument lane; `paper` and `live` are execution/evidence lanes. `--storage-separation-report` prints the lane schemas and storage directories so migration can be verified without duplicating the strategy brain.
- Empty root `storage/` placeholder directories were removed because PostgreSQL is the active operations store; `StorageLayout.ensure_directories()` can recreate lane log/evidence/export directories lazily when a workflow actually needs files.
- `scripts/bootstrap_storage_lanes.py` initializes the configured PostgreSQL `core`, `paper`, and `live` schemas/tables without changing the active control-loop schema, so lane readiness can be verified before cutover.
- Broker order rows, shadow proposals/outcomes, and strategy fitness snapshots carry paper/live/evidence-origin metadata.
- Broker order rows and shadow evidence rows now persist `canonical_instrument_id`, `venue`, and `venue_symbol`; schema bootstrap backfills existing derivable rows and status surfaces the canonical instrument on recent broker orders and proposals.
- Alpaca market-data adapter outputs now carry `asset_class` / `canonical_instrument_id` / `venue` / `venue_symbol` metadata before pipeline persistence or discovery consumes them. New market-data latest-bar rows, historical-bar rows, and strategy-candidate signal rows persist the same metadata. Existing large market-data/signal history is not swept during normal schema bootstrap so status/control ticks stay fast.
- The instrument registry now exposes a first-class `InstrumentRef` for venue-specific resolved identity. Persistence boundaries use it to populate canonical instrument metadata while the wider strategy path is migrated gradually.
- Discovery ranked candidates and strategy signals now preserve a first-class serialized `instrument_ref` when canonical metadata is present on market-data rows, so downstream proposal/order evidence does not need to re-infer the venue mapping.
- Initial PostgreSQL-only paper/live config and deployment examples exist.
- `CENTAUR_CONFIG` is honored as a default config layer for the PostgreSQL-only paper/live YAML files; `.env` values still win as operator overrides.
- Initial canonical instrument registry exists with venue-specific mappings.
- Initial market-data adapter boundary exists. The current Alpaca latest equity/crypto bar fetches and historical equity/crypto backfill fetches now go through `centaur.market_data_adapters` instead of direct pipeline calls to the Alpaca client.
- Initial execution-adapter boundary exists under `centaur.execution_adapters`. Entry/exit order-request building plus submit/cancel now go through that narrower order-planning and mutation interface, currently bridged to the existing broker adapters so order behavior stays unchanged while future vendor execution adapters get a proper home.
- The execution-adapter registry is explicitly allowlisted to `alpaca_paper` and `alpaca_live`; scaffold-only or future providers such as IG, Binance, and Coinbase fail at adapter lookup rather than creating a late-failing bridge.
- `--adapter-inventory` exists as a read-only adapter inventory. It lists active Alpaca market-data/execution/broker-account boundaries, scaffold-only IG account support, and explicitly not-implemented future providers such as Binance, Coinbase, and Polygon.
- The target `app/` package now exists as architecture-facing facade modules over the current `centaur/` implementation: `app/core`, `app/engine`, `app/adapters`, `app/runtime`, `app/storage`, `app/reporting`, and `app/strategies`. This creates the physical folder structure without moving live scheduler behavior.
- First implementation ownership moved from `centaur/` into `app/`: runtime mode context, live guard, execution router, execution adapters, market-data adapters, canonical instruments, and storage layout now live under `app/`. The old `centaur/` modules are compatibility wrappers, and active pipeline imports use the new `app/` modules for these boundaries.

Not done yet:
- continue migrating implementation ownership from `centaur/` into the new `app/` modules where it is safe and useful; strategy engine, broader pipeline orchestration, reports, persistence repositories, and dashboard implementation still mainly live under `centaur/`
- cut over actual unattended paper/live jobs to their lane schemas/databases after the initialized `core`, `paper`, and `live` schemas are reviewed
- complete migration of every remaining strategy input and market-data snapshot to first-class `InstrumentRef` / canonical instrument objects instead of carrying canonical metadata beside raw vendor symbols
- complete market-data and execution-adapter implementations for non-Alpaca vendors, with broker-state/account adapters kept separate from execution mutation adapters
- keep `--adapter-inventory` current as new adapters move from not-implemented to scaffold or active

## Core Principle

Use this rule throughout the refactor:

```text
Do not duplicate the brain.
Separate the vendors, money, data, permissions, and runtime state.
```

Centaur should have:

```text
Shared core logic:
- instruments
- market snapshots
- signals
- proposals
- strategy evaluation
- fitness calculation
- risk checks
- slot logic
- order intents
- exit decisions
- reporting models

Vendor-specific adapters:
- market data adapters
- execution adapters
- broker/account adapters
- symbol mapping adapters

- core config/evidence
- paper config
- live config
- core database/schema for shared reviewed evidence
- paper database/schema
- live database/schema
- paper logs/evidence
- live logs/evidence
```

## Target Folder Structure

Use this structure or adapt the existing project toward it.

Current physical status: this tree now exists as facade modules. The current implementation still mainly lives in `centaur/runtime.py`, `centaur/execution_router.py`, `centaur/live_guard.py`, `centaur/instruments.py`, `centaur/market_data_adapters/`, `centaur/execution_adapters/`, and `centaur/storage_layout.py`; the `app/` modules provide stable architecture-facing imports while behavior is migrated gradually.

```text
project-centaur/
  README.md
  main.py
  pyproject.toml / requirements.txt

  app/
    core/
      __init__.py
      instruments.py
      market_data.py
      signals.py
      proposals.py
      orders.py
      positions.py
      outcomes.py
      risk_models.py
      enums.py

    engine/
      __init__.py
      candidate_engine.py
      strategy_engine.py
      prediction_engine.py
      fitness_engine.py
      risk_engine.py
      execution_planner.py
      exit_engine.py

    strategies/
      __init__.py
      base.py
      momentum_breakout.py
      mean_reversion.py
      volume_spike.py
      crypto_continuation.py

    adapters/
      __init__.py

      market_data/
        __init__.py
        base.py
        alpaca_data.py
        binance_data.py
        simulator_data.py

      execution/
        __init__.py
        base.py
        alpaca_paper.py
        alpaca_live.py
        simulator.py

      symbol_mapping/
        __init__.py
        registry.py
        alpaca_symbols.py
        binance_symbols.py

    runtime/
      __init__.py
      settings.py
      mode_context.py
      execution_router.py
      live_guard.py
      kill_switch.py
      service_container.py

    storage/
      __init__.py
      db.py
      migrations/
      repositories/
        __init__.py
        trades.py
        orders.py
        positions.py
        fitness.py
        evidence.py

    reporting/
      __init__.py
      dashboard_models.py
      why_no_trade.py
      fitness_report.py
      slot_usage_report.py

  configs/
    paper.yaml
    live.yaml

  deployments/
    paper/
      .env.example
      run_paper.sh

    live/
      .env.example
      run_live.sh

  storage/
    core/
      logs/
      evidence/
      exports/

    paper/
      logs/
      evidence/
      exports/

    live/
      logs/
      evidence/
      exports/

  tests/
    test_paper_cannot_call_live_broker.py
    test_live_requires_live_guard.py
    test_symbol_mapping.py
    test_fitness_environment_separation.py
    test_execution_router_modes.py
```

## Runtime Modes

Implement explicit runtime modes. Do not infer mode from branch name, API key name, folder name, or database name.

Supported modes:

```text
shadow
paper
live_dry
live
```

Meaning:

```text
shadow:
- generate signals/proposals
- record evidence
- never place broker orders

paper:
- generate signals/proposals
- place paper/simulated/paper-broker orders
- record paper trades and paper outcomes

live_dry:
- run live eligibility and risk checks
- produce intended live orders
- do not place real broker orders
- record what would have happened

live:
- may place real broker orders
- requires explicit live config
- requires LiveRiskGuard approval
- requires enabled strategy permission
- requires kill switch to be clear
```

## Config Files

Create separate config files.

Important: Project Centaur is PostgreSQL-only for scheduler-backed paper/live operation and monitoring. The settings below should point to PostgreSQL connection names/URLs or schema/database identifiers, not SQLite `.db` files. SQLite may exist only as explicit local/dev scaffolding when execution is disabled.

### configs/paper.yaml

```yaml
mode: paper
environment: paper
broker: alpaca
market_data_provider: alpaca
execution_provider: alpaca_paper

database: centaur_paper
log_dir: storage/paper/logs
evidence_dir: storage/paper/evidence

allow_live_trading: false
max_notional_per_trade: 10
base_slots: 10

enabled_strategies:
  - momentum_breakout
  - mean_reversion
  - volume_spike
  - crypto_continuation

live_enabled_strategies: []
```

### configs/live.yaml

```yaml
mode: live
environment: live
broker: alpaca
market_data_provider: alpaca
execution_provider: alpaca_live

database: centaur_live
log_dir: storage/live/logs
evidence_dir: storage/live/evidence

allow_live_trading: false
max_notional_per_trade: 10
base_slots: 10
max_live_open_positions: 10
max_daily_live_loss: 5

enabled_strategies:
  - mean_reversion.snapback
  - crypto_momentum.trend
  - momentum.volatility_breakout

live_enabled_strategies:
  - mean_reversion.snapback
  - crypto_momentum.trend
  - momentum.volatility_breakout
```

Important: `allow_live_trading` should default to `false`. Live trading should only happen after this is deliberately changed and all tests pass.

## Environment Files

Create separate deployment environment files.

### deployments/paper/.env.example

```env
CENTAUR_MODE=paper
CENTAUR_ENVIRONMENT=paper
CENTAUR_CONFIG=configs/paper.yaml
ALPACA_ACCOUNT_TYPE=paper
ALPACA_PAPER_API_KEY=
ALPACA_PAPER_SECRET_KEY=
ALLOW_LIVE_TRADING=false
```

### deployments/live/.env.example

```env
CENTAUR_MODE=live
CENTAUR_ENVIRONMENT=live
CENTAUR_CONFIG=configs/live.yaml
ALPACA_ACCOUNT_TYPE=live
ALPACA_LIVE_API_KEY=
ALPACA_LIVE_SECRET_KEY=
ALLOW_LIVE_TRADING=false
```

## Database Separation

Use PostgreSQL-backed paper/live separation. This may be implemented as two PostgreSQL databases or as separate PostgreSQL schemas with hard environment/mode metadata on every relevant row:

```text
centaur_paper
centaur_live
```

Do not mix paper trades into live trade tables.

Paper trade history may be used as evidence for live promotion, but it must remain clearly marked as paper-derived evidence.

Good:

```text
centaur_paper:
- paper orders
- paper trades
- paper positions
- paper strategy fitness
- paper shadow evidence

centaur_live:
- live orders
- live trades
- live positions
- live risk state
- imported paper fitness snapshots
- live strategy permissions
```

Bad:

```text
centaur_live.trades contains old paper trades as if they were live trades.
```

## Required Database Columns

Every order/trade/position/evidence/fitness row must include enough metadata to prevent ambiguity.

Minimum fields where relevant:

```text
run_id
environment              paper | live
mode                     shadow | paper | live_dry | live
source_environment       shadow | paper | live | backtest
broker                   alpaca | binance | simulator | etc.
data_provider            alpaca | binance | polygon | etc.
execution_provider       alpaca_paper | alpaca_live | simulator | etc.
asset_market             crypto | equity | etf | betfair_exchange | etc.
canonical_instrument_id
venue
venue_symbol
strategy_name
created_at
updated_at
```

## Fitness Separation

Fitness must not be grouped only by `market` and `strategy`.

Do not use this as the final model:

```text
strategy_name
market
fitness
```

Use this shape instead:

```text
strategy_name
canonical_instrument_id / asset_market
source_environment
mode
broker
data_provider
execution_provider
sample_size
win_rate
avg_win_pct
avg_loss_pct
expectancy_pct
max_drawdown_pct
first_seen_at
last_seen_at
```

Paper fitness can inform live decisions, but it should not automatically grant live permission.

Use three separate concepts:

```text
paper_fitness:
- says whether the strategy appears to work in paper/shadow testing

live_strategy_permissions:
- says whether the strategy is explicitly allowed to trade live

live_fitness:
- tracks whether the strategy is actually working with real money
```

## Instrument and Venue Model

Do not treat vendor symbols as the core truth.

BTC can exist on multiple venues:

```text
ALPACA:BTC/USD
BINANCE:BTCUSDT
COINBASE:BTC-USD
KRAKEN:XBT/USD
```

These may all relate to Bitcoin, but they are different venue listings.

Implement a symbol/instrument registry.

Suggested model:

```text
canonical_instruments
- canonical_instrument_id     e.g. BTC-USD-SPOT
- base_asset                  e.g. BTC
- quote_asset                 e.g. USD
- asset_class                 e.g. crypto
- instrument_type             e.g. spot

venue_symbol_map
- venue                       e.g. alpaca
- venue_symbol                e.g. BTC/USD
- canonical_instrument_id     e.g. BTC-USD-SPOT
- can_use_for_signals         true/false
- can_use_for_execution       true/false
- priority
```

Rule:

```text
Adapters convert vendor symbols into canonical Centaur instruments.
Strategies operate on canonical Centaur instruments.
Execution adapters convert Centaur order intents back into vendor symbols.
```

## Adapter Interfaces

Create base interfaces for market data and execution.

### Market Data Adapter

The market data adapter fetches vendor-specific data and normalizes it into Centaur models.

Example responsibilities:

```text
- get_latest_bar()
- get_latest_quote()
- get_historical_bars()
- get_candidate_universe()
- normalize vendor response into MarketBar / MarketQuote / MarketSnapshot
```

The strategy layer must not call Alpaca, Binance, or any vendor directly.

Bad:

```python
alpaca_client.get_bars(...)
```

inside a strategy.

Good:

```python
strategy.evaluate(market_snapshot)
```

### Execution Adapter

The execution adapter places orders and syncs positions/fills for a specific venue/account.

Example responsibilities:

```text
- place_order(order_intent)
- cancel_order(order_id)
- get_order(order_id)
- get_open_positions()
- get_account_status()
- normalize fills and positions into Centaur models
```

## Core Models

Use normalized internal objects.

Example:

```python
MarketBar(
    canonical_instrument_id="BTC-USD-SPOT",
    venue="alpaca",
    venue_symbol="BTC/USD",
    timestamp=...,
    open=...,
    high=...,
    low=...,
    close=...,
    volume=...,
    source="alpaca",
)
```

Example:

```python
Signal(
    canonical_instrument_id="BTC-USD-SPOT",
    strategy_name="crypto_continuation",
    direction="long",
    confidence=0.72,
    projected_gain_pct=1.4,
    reason="momentum continuation detected",
)
```

Example:

```python
OrderIntent(
    canonical_instrument_id="BTC-USD-SPOT",
    venue="alpaca",
    venue_symbol="BTC/USD",
    side="buy",
    notional=10.00,
    strategy_name="crypto_continuation",
    reason="risk-approved proposal",
)
```

## Execution Router

All order placement must go through one `ExecutionRouter`.

Strategies must never place orders.

Expected flow:

```text
market data adapter
→ normalized market data
→ strategy engine
→ signal
→ proposal
→ risk engine
→ order intent
→ execution router
→ shadow recorder / paper broker / live dry recorder / live broker
```

Conceptual behaviour:

```python
def route_order(order_intent, context):
    if context.mode == "shadow":
        return record_shadow_intent(order_intent)

    if context.mode == "paper":
        return paper_execution_adapter.place_order(order_intent)

    if context.mode == "live_dry":
        return record_live_dry_intent(order_intent)

    if context.mode == "live":
        live_guard.assert_allowed(order_intent, context)
        return live_execution_adapter.place_order(order_intent)
```

## LiveRiskGuard

Live trading needs a final mandatory guard immediately before any real order.

LiveRiskGuard must check:

```text
- mode == live
- environment == live
- allow_live_trading == true
- broker account type confirms live
- strategy is live-enabled
- instrument is live-enabled
- notional <= max_notional_per_trade
- live open positions <= max_live_open_positions
- daily live loss has not breached max_daily_live_loss
- no latest_bar_unavailable condition
- exit/position sync health is green
- kill switch is not active
```

If any condition fails, live order placement must be refused and logged.

## Kill Switch

Add a simple file-based kill switch.

Example:

```text
storage/live/KILL_LIVE_TRADING
```

If this file exists:

```text
- no new live orders may be placed
- existing position management may still run if safe
- dashboard should show live trading disabled
```

## Paper/Live Code Promotion

Use branches for code maturity, not for trading mode.

Suggested Git workflow:

```text
feature/*  -> individual Codex changes
develop    -> paper/research instance
main       -> live deployable code
```

Suggested instance mapping:

```text
centaur-paper runs develop or main
centaur-live runs main only
```

Do not create permanently diverging `paper` and `live` branches.

Runtime behaviour must be controlled by config/environment, not branch name.

Bad:

```python
if current_branch == "live":
    place_live_order()
```

Good:

```python
if settings.mode == "live" and settings.allow_live_trading:
    live_guard.assert_allowed(order_intent, context)
    live_execution_adapter.place_order(order_intent)
```

## Why No Trade Reporting

Add a daily/cycle-level funnel report to diagnose slot usage.

Record:

```text
candidates discovered
candidate symbols
raw signals generated
raw signal symbols and strategy names
shadow proposals generated
rejected proposals by reason
accepted paper/live trades
skipped trades by reason
open slots before cycle
open slots after cycle
positions blocking slots
exit skips
latest_bar_unavailable events
closed trades per day
```

Expose this in the dashboard as:

```text
Why No Trade?
```

and save JSON/CSV evidence files to:

```text
storage/paper/evidence/
storage/live/evidence/
```

## Tests Required

Add tests proving safety boundaries.

Required tests:

```text
1. Paper mode cannot call Alpaca live execution adapter.
2. Shadow mode never places broker orders.
3. Live_dry mode never places broker orders.
4. Live mode refuses orders when allow_live_trading=false.
5. Live mode refuses orders when kill switch exists.
6. Live mode refuses strategies that are not live_enabled.
7. Live mode refuses orders above max_notional_per_trade.
8. Fitness records are separated by source_environment/mode.
9. Paper trades do not appear as live trades.
10. Symbol mapper maps Alpaca BTC/USD and Binance BTCUSDT separately.
11. Strategy layer does not import vendor execution clients.
12. All orders/trades/positions include environment and mode metadata.
```

## Immediate Implementation Order

Do the refactor in this order.

### Phase 1 - Runtime Separation

```text
1. Add settings loader for configs/paper.yaml and configs/live.yaml.
2. Add ModeContext.
3. Add storage paths for paper/live.
4. Ensure PostgreSQL database/schema selection comes from config.
5. Ensure logs/evidence paths come from config.
```

### Phase 2 - Execution Safety

```text
1. Create ExecutionRouter.
2. Move all order placement behind ExecutionRouter.
3. Create AlpacaPaperExecutionAdapter.
4. Create AlpacaLiveExecutionAdapter.
5. Add LiveRiskGuard.
6. Add kill switch.
7. Add safety tests.
```

### Phase 3 - Adapter Boundary

```text
1. Create MarketDataAdapter base class.
2. Move Alpaca data reads into AlpacaDataAdapter.
3. Ensure strategies receive normalized data only.
4. Add symbol registry.
5. Add BinanceDataAdapter placeholder/stub, but do not use it live yet.
```

### Phase 4 - Fitness and Evidence

```text
1. Add environment/mode/source_environment to fitness records.
2. Separate paper fitness from live permissions.
3. Add imported paper fitness snapshot support for live.
4. Add Why No Trade report.
5. Add slot usage report.
```

### Phase 5 - Dashboard

```text
1. Show current mode: shadow/paper/live_dry/live.
2. Show current environment: paper/live.
3. Show active PostgreSQL database/schema.
4. Show broker account type.
5. Show live trading enabled/disabled.
6. Show kill switch state.
7. Show strategy permissions by mode.
8. Show Why No Trade funnel.
9. Show paper fitness and live fitness separately.
```

## Acceptance Criteria

The refactor is acceptable only when:

```text
- Centaur can run paper using configs/paper.yaml and a PostgreSQL-backed paper database/schema.
- Paper/live operation remains PostgreSQL-backed; SQLite is not used for live operation or scheduler-backed paper/live monitoring.
- Centaur can run live_dry using live config without placing real orders.
- Centaur cannot place live orders unless allow_live_trading=true.
- Centaur cannot place live orders when kill switch exists.
- Strategies do not import Alpaca/Binance execution clients.
- Alpaca-specific logic is contained in adapters.
- Paper and live use separate PostgreSQL databases or schemas, with explicit environment/mode metadata on relevant rows during migration.
- Paper fitness can be viewed/imported as evidence but is not mixed into live trades.
- Dashboard clearly shows mode, environment, PostgreSQL database/schema, broker/account type, and live guard status.
- Tests prove paper cannot accidentally hit the live broker.
```

## Non-Goals For This Refactor

Do not build full Binance live trading yet.

Do not build Betfair yet.

Do not change the $10 per-trade notional.

Do not loosen risk gates.

Do not promote new strategies to live.

Do not mix paper and live trades in one table without explicit environment separation.

Do not make branch name control trading mode.

## Final Instruction

Treat Alpaca as the first adapter, not the product.

Centaur is the product.

The product is:

```text
A market prediction, strategy fitness, risk, and execution engine with pluggable market-data and execution adapters.
```
