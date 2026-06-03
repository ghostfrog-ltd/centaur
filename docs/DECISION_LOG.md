# Project Centaur Decision Log

This file records important decisions so the project does not depend on chat memory alone.

Last updated: 2026-06-03

## 2026-06-03

### Raise paper/live daily drawdown protector to $2.00
Decision:
- by explicit operator override, raise `PAPER_EXECUTION_MAX_DAILY_DRAWDOWN_USD` from `$1.00` to `$2.00`
- keep Alpaca Live same-as-paper by raising `LIVE_EXECUTION_MAX_DAILY_DRAWDOWN_USD` from `$1.00` to `$2.00`
- apply the paper setting to all paper execution lanes that read the shared paper protector, including Alpaca Paper and Trading 212 Paper

Why:
- the active `$10` micro-trade, 10-slot paper lane has shown normal open-P/L noise around `$1.35-$1.80`
- the `$1.00` protector can halt new entries before enough throughput is observed for a low-margin strategy test
- `$2.00` is the smallest tested step that covered the observed session-start drawdown noise in the available sample; `$3.00` is not yet justified by evidence

Implementation notes:
- this widens only the daily entry-protection latch
- it does not widen per-trade notional, slot count, broker routing, live independence, strategy allowlists, projected-gain floors, order frequency, stale-order rules, or long-only policy
- existing positions and managed exits remain governed by their existing stop/target/exit rules

## 2026-06-02

### Replace near-miss fitness override with 90+ score-to-trade rule
Decision:
- by explicit operator override, make `PAPER_MIN_SIGNAL_SCORE_TO_TRADE=90.0` the main entry dial
- keep live matched with `LIVE_MIN_SIGNAL_SCORE_TO_TRADE=90.0`; live remains same-as-paper and follows only submitted paper orders
- for already approved strategies, raw setup score at or above this dial survives fitness suppression and proceeds to proposal/CFO/risk review
- keep fitness as ranking/reporting evidence for these 90+ candidates rather than a hard entry blocker

Why:
- a 90+ current setup should be allowed to reach the capital gates in the micro paper lane
- the prior near-miss fitness-cliff rule made the system too complex and could suppress high-quality current setups before CFO/risk could evaluate them

Implementation notes:
- hard safety rails remain: `$10` notional, long-only, market/session gates, daily drawdown protector, slots, one order per tick, duplicate position/order checks, approved strategies, projected-gain floor, and valid instrument/price requirements
- this does not create independent live strategy decisions; live remains downstream of same-tick submitted paper orders

### Lower paper/live daily drawdown protector to $1.00
Decision:
- by explicit operator override, lower `PAPER_EXECUTION_MAX_DAILY_DRAWDOWN_USD` from `$5.00` to `$1.00`
- keep Alpaca Live same-as-paper by lowering `LIVE_EXECUTION_MAX_DAILY_DRAWDOWN_USD` from `$5.00` to `$1.00`

Why:
- the active micro lane targets small daily gains, and a `$5.00` loss allowance is too large relative to observed daily upside and `$10` entries
- the operator wants one simple loss guard rather than layered soft/hard loss controls

Implementation notes:
- this is a stricter capital-preservation change only
- it does not widen notional, slots, broker routing, live independence, strategy allowlists, projected-gain floors, or order frequency

## 2026-06-01

### Make LangGraph and Pydantic the orchestration target
Decision:
- tighten the architecture constraint from "pipeline-first, LangGraph-compatible" to LangGraph-first orchestration with Pydantic-backed state and node contracts
- treat the current `ControlPipelineRunner`/`StepDefinition` pipeline as behaviour-preserving migration scaffolding, not the desired end state
- require new orchestration work to add typed LangGraph/Pydantic structure or explicitly document why it is a temporary migration bridge
- require graph visualization/export updates when nodes or edges change

Why:
- the proof-of-concept pipeline now has enough moving parts that untyped dict flow is becoming hard to understand, audit, and visualize
- the original system intent was explicit graph orchestration with visible node boundaries, especially around market, signal, fitness, CFO, execution, and live-follower gates
- Pydantic contracts should make state transitions easier to inspect and safer to refactor without weakening capital-preservation rules

Implementation notes:
- this decision changes architecture direction and documentation discipline only
- it does not approve changes to notional, thresholds, broker routing, paper/live behaviour, strategy allowlists, or risk gates
- current visualization scaffolding lives in `TICK_DECISION_FLOW.md`, `docs/VISUALIZATION.md`, and `docs/visuals/`

### Use most protective stop for aggregated managed positions
Decision:
- when Alpaca aggregates multiple same-symbol managed lots into one long position, choose the highest stop-loss among still-open managed entry lots for the full-position managed exit
- keep FIFO matching in the plan selector so closed older lots do not keep controlling new positions
- preserve unmanaged/manual holdings as `missing_entry_plan` rather than inventing a stop

Why:
- today's LINK/USD paper loss showed that using the latest same-symbol entry plan can let an older open lot drift below its own persisted stop
- Centaur cannot sell a broker-sub-position by lot through Alpaca fractional position state, so the capital-preserving behavior is to exit the whole aggregated position on the most protective still-open stop
- this tightens managed exits without changing notional, slots, broker scope, strategy allowlist, live independence, or entry gates

Implementation notes:
- paper and live managed exit lookup now FIFO-matches recent same-symbol fills and selects the most protective still-open managed entry plan
- tests cover multiple open LINK lots, closed older lots, and unmanaged AMZN/XEL-style holdings

### Split crypto momentum tuning by paper/live lane
Decision:
- replace operator-facing global `CRYPTO_MOMENTUM_*` settings with `PAPER_CRYPTO_MOMENTUM_*` and `LIVE_CRYPTO_MOMENTUM_*`
- keep legacy `CRYPTO_MOMENTUM_*` names as fallback inputs only, so older environments continue to load
- default live crypto momentum values to paper values and include them in the same-as-paper validator; armed live rejects unnamed differences unless they are listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES`

Why:
- paper needs to test alternate crypto momentum approaches without making live changes look accidental or global
- live remains a real-money follower lane, so live-vs-paper drift still needs explicit review and audit labeling

Implementation notes:
- `.env`, `.env.example`, README, glossary, compact context, and constraints now document lane-scoped crypto momentum keys
- active runtime strategy values are selected from paper settings in paper/shadow environments and live settings in live/live_dry environments

### Reduce crypto momentum stop to one percent
Decision:
- by explicit operator override, keep `crypto_momentum.trend` enabled but reduce `CRYPTO_MOMENTUM_STOP_LOSS_PCT` from `0.03` to `0.01`
- lower the strategy-level minimum crypto stop floor from `2.0%` to `1.0%` so the runtime config is actually honored
- keep `$10` notional, one order per tick, slot caps, projected-gain floors, broker routing, live same-as-paper following, and profit capture unchanged

Why:
- the LINK/USD stop showed that a `3.0%` loss on a `$10` trade is roughly `$0.30`, too large relative to an overall daily micro-profit target around `$0.50`
- recent crypto evidence did not support needing a `70%+` win rate implied by `+1.25%` profit capture against a `-3.0%` stop
- the operator explicitly asked not to stop crypto, only to reduce the loss number

Implementation notes:
- `.env`, `.env.example`, runtime defaults, and the crypto strategy profile floor now use `1.0%`
- existing open positions retain their persisted entry plans; the new stop applies to future crypto momentum proposals

## 2026-05-31

### Simplify runtime configuration to `.env` only
Decision:
- remove the paper/live YAML runtime defaults and the `configs/` folder
- make `.env` the single runtime configuration source
- group `.env` and `.env.example` into core, paper, and live sections with operator-facing safety notes
- mirror paper/live execution levers in `.env`; while live is armed, unlisted drift fails closed and reviewed named differences must be listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES`

Why:
- paper/live YAML defaults were not active unless a separate environment pointer was set
- the duplicate path made database and execution levers harder to audit
- a single sectioned `.env` is easier to inspect before paper or live operation
- same-as-paper live operation should be obvious in config, while small reviewed differences need an explicit operator lever and runtime validation

### Add runtime context, execution router, live guard, and instrument registry foundations
Decision:
- add a `ModeContext` runtime model that centralizes mode/environment normalization and live-broker permission checks
- treat `live_dry` as a live-environment mode that may read live broker state for eligibility/risk review but must not mutate live broker state
- update live pipeline boundaries to use `ModeContext` instead of ad hoc mode string checks
- add an `ExecutionRouter` for approved entry orders, managed exit submissions, and stale-order cancellations so paper/live order actions have one broker-adapter choke point
- add a `LiveRiskGuard` immediately before live entry, exit, and cancel actions to re-check runtime mode, live enablement, kill switch, activation acknowledgement, live broker id, strategy permission where relevant, live account/sync readiness, live entry capacity, latest-bar availability, live instrument/venue permission where derivable, same-paper-order validation where relevant, and entry notional
- add an initial instrument registry that separates canonical Centaur instruments from venue symbols, including separate venue mappings for `ALPACA:BTC/USD`, `BINANCE:BTCUSDT`, and `COINBASE:BTC-USD`
- add a first-class `InstrumentRef` resolved identity object to the registry and use it at persistence boundaries when deriving canonical instrument metadata
- persist `canonical_instrument_id`, `venue`, and `venue_symbol` on broker order rows and shadow proposal/outcome evidence rows, including schema-bootstrap backfills for existing rows where the instrument can be derived
- persist `asset_class`, `canonical_instrument_id`, `venue`, and `venue_symbol` on new market-data latest-bar rows, new historical-bar rows, and new strategy-candidate signal rows
- preserve canonical instrument metadata through discovery ranked candidates and strategy signal dicts when that metadata is present on the source market-data row
- preserve a serialized first-class `instrument_ref` through discovery ranked candidates and strategy signal dicts when canonical metadata is present on the source market-data row
- add an initial market-data adapter boundary under `centaur.market_data_adapters`; current Alpaca equity/crypto latest-bar fetches and historical equity/crypto backfill fetches now go through `AlpacaMarketDataAdapter`
- make `AlpacaMarketDataAdapter` enrich latest and historical bar payloads with canonical instrument metadata before pipeline persistence/discovery consumes them
- add an initial execution-adapter boundary under `centaur.execution_adapters`; entry/exit order-request building and `ExecutionRouter` submit/cancel now use the narrower execution planning/mutation interface, currently bridged to existing broker adapters
- explicitly allowlist the execution-adapter registry to `alpaca_paper` and `alpaca_live`, so scaffold-only/future providers fail at lookup before order planning or mutation
- add `.venv-mac/bin/python main.py --storage-separation-report`, a bounded read-only report that samples recent broker-order, shadow-proposal, and strategy-fitness rows to show paper/live/evidence provenance and the current physical-split status
- remove the separate live-only threshold report/config path after operator clarification; diagnostics should focus on whether live matched the same paper-approved order, not on a separate live policy
- honor optional `POSTGRES_SCHEMA` in `UsageLedger`; when set, the PostgreSQL backend creates/uses that schema and reports it in backend detail, while unset keeps the current shared-schema behavior
- add an explicit core/paper/live storage layout model so reviewed evidence and strategy fitness can remain shared in `core` while paper/live execution evidence has separate lane schemas and directories
- make storage lane directories lazy with `StorageLayout.ensure_directories()` and remove the empty root `storage/` placeholder tree because it contained only `.gitkeep` files
- add `scripts/bootstrap_storage_lanes.py` to initialize the configured PostgreSQL `core`, `paper`, and `live` schemas/tables before any active scheduler cutover
- add `.venv-mac/bin/python main.py --adapter-inventory`, a read-only inventory of active, bridged, scaffold-only, and not-implemented market-data/execution/broker-account adapters
- surface the canonical instrument id in recent broker-order and shadow-proposal status lines
- keep paper/live lane settings visible in the runtime environment instead of splitting active defaults across multiple config formats
- create the target physical `app/` architecture tree as facade modules over the current `centaur/` implementation, covering `core`, `engine`, `adapters`, `runtime`, `storage`, `reporting`, and `strategies`
- move the first implementation slice into `app/`: runtime mode context, live guard, execution router, execution adapters, market-data adapters, canonical instruments, and storage layout
- keep the old `centaur/` files for those moved boundaries as compatibility wrappers and switch active pipeline imports to the `app/` modules
- add an import test proving the new `app/` architecture facades resolve to the current implementation

Why:
- the adapter-first architecture requires mode/environment to be a hard safety boundary, not scattered string logic
- `live_dry` is only useful if it can exercise live-readiness paths without creating an order-mutation path
- strategies and future adapters need a canonical instrument layer so vendor symbols do not become the core truth
- config examples should reflect the intended paper/live separation without implying SQLite-backed live operation

Implementation notes:
- this is architecture scaffolding and boundary hardening only
- the router and live guard now cover entry submission, managed exit submission, and stale-order cancellation
- live entry/exit order requests with explicit venue metadata that conflicts with the live broker venue are blocked before adapter calls; known registry mappings that are not executable on the broker venue are also blocked
- live entry/exit submission now re-checks that the live account/positions/orders sync exists, the live account is active and unblocked, the relevant latest bar exists, and live entry capacity has not already been consumed before any adapter call
- by operator clarification on 2026-05-31, do not configure separate live-only trade-count or bar-age policy unless explicitly requested; Alpaca Live should be exactly the paper lane, but live
- no separate live-guard threshold report or live-only threshold config remains after the same-as-paper clarification; diagnostics should review whether live matched the approved paper action
- live-dry exit/cancel intent evidence is still minimal and should get a fuller report model before relying on it operationally
- PostgreSQL status smoke verified the instrument metadata backfill: recent older broker-order and shadow-proposal rows now show canonical instrument ids where derivable
- PostgreSQL status smoke also verified new latest-bar rows carrying canonical instrument ids such as `AAVE-USD-SPOT`, `BTC-USD-SPOT`, and `LINK-USD-SPOT`
- a first attempt at bootstrapping latest-bar historical metadata used a full-table update and was canceled because it blocked dashboard/status/control startup; normal schema bootstrap now adds columns/indexes and writes metadata for new rows without sweeping large market-data/signal history
- historical backfill rows now also write canonical instrument metadata for new bars, with a supporting `(canonical_instrument_id, timeframe, bar_timestamp)` index and no historical sweep in normal schema bootstrap
- `InstrumentRef` is a migration foundation only; strategy scoring and market-data selection still use current symbol fields while carrying canonical metadata forward for evidence and routing
- the market-data adapter boundary is a no-behavior-change wrapper around the current Alpaca client; direct Alpaca data transport calls now live inside the Alpaca market-data adapter, while future non-Alpaca providers still need concrete adapters and symbol-normalization tests before activation
- adapter-side instrument metadata enriches payloads only; it does not alter bar prices, ranking inputs, symbol lists, risk gates, or order routing
- the execution-adapter boundary is also a no-behavior-change wrapper for now; it separates order planning and mutation dependencies from broader broker account/state adapters, while concrete non-Alpaca execution adapters still require separate implementation and tests
- IG remains account-scaffold-only and is not resolvable as an execution adapter
- the adapter inventory is an operator/reporting surface only; it does not instantiate non-Alpaca providers or make them eligible for trading
- the new `app/` package is now both a physical folder/import boundary and the implementation owner for the first migrated boundary slice; broader pipeline orchestration, persistence repositories, reports, strategies, and dashboards still need staged migration
- compatibility wrappers in `centaur/` are deliberate so older imports and scheduler paths keep working during the migration
- strategy scoring still uses the same symbol/asset-class fields and numeric inputs; canonical metadata is carried for downstream evidence/routing and does not alter ranking or signal logic
- the storage-separation report verified PostgreSQL row-level provenance on recent samples: broker orders, shadow proposals, and strategy fitness rows had required `environment`, `mode`, and `source_environment` values; physical paper/live database or schema separation remains pending
- schema-level separation is now scaffolded, but the active local runtime remains on its configured current schema unless `POSTGRES_SCHEMA` is explicitly set; moving production paper/live lanes requires a separate migration/checklist
- storage layout reporting now distinguishes the shared core brain lane from paper/live execution lanes; the split must not be implemented by duplicating strategy fitness or letting live outcome rows masquerade as paper evidence
- root storage cleanup removes unused placeholder folders only; configured lane paths still exist as logical paths and can be recreated lazily for file output
- lane schema bootstrapping is non-destructive readiness work only; switching unattended jobs to lane schemas remains a separate operational cutover step
- no notional, strategy allowlist, projected-gain floor, slot policy, daily protection, broker routing, live activation rule, or managed-exit policy changed
- regression tests now cover runtime context permissions, `live_dry` environment defaulting, venue-specific symbol mapping, live-dry router behavior, live guard pre-submit blocking, live exit guard blocking, live cancel guard blocking, and paper cancel routing

### Record live-dry order-action intents
Decision:
- make `ExecutionRouter` append live-dry entry, exit, and cancel intents into tick state under `execution_router_intents`
- let live-dry stale-order reaping produce intended cancellation records without calling the live broker adapter or marking the order canceled
- let live-dry managed exits produce intended exit and refresh-cancel records without calling the live broker adapter or persisting live broker responses
- persist router intents in an `execution_router_intents` audit table with runtime mode, lane, action, broker, status, strategy, symbol/order id, canonical instrument metadata, and the intended order payload
- summarize recent router intents in `.venv-mac/bin/python main.py --evidence-report`
- keep explicit paper mode blocked from live broker sync and live order-action paths

Why:
- `live_dry` should be useful for reviewing what Centaur would have done in the live lane
- intended live actions must be auditable without creating real broker mutations
- the architecture doc calls for `live_dry` to produce intended live orders, not merely skip the live lane
- tick-state evidence alone is too ephemeral for operator review after a later tick has replaced the latest state

Implementation notes:
- this is observability and dry-run evidence only
- no paper/live notional, strategy allowlist, projected-gain floor, broker routing, activation gate, kill switch, daily protection, managed-exit rule, or real order behavior changed
- a PostgreSQL status smoke check initially caught a normal-runtime bug from the refactor (`intended_refresh_cancellations` referenced in paper exit management); it was fixed immediately, tests passed, and the next scheduler tick completed `ok`

### Persist shadow evidence provenance
Decision:
- add explicit provenance columns to `shadow_trade_proposals` and `shadow_trade_outcomes`: `environment`, `mode`, `source_environment`, `data_provider`, and `execution_provider`
- make new shadow proposals inherit runtime environment/mode and record `source_environment=shadow`, `execution_provider=shadow`
- make pending outcome checkpoints inherit metadata from their parent proposal
- carry that metadata through evaluated outcome rows

Why:
- shadow proposals/outcomes are evidence rows that may later inform live decisions
- live must be able to consume that evidence without it becoming indistinguishable from live outcome history
- fitness snapshots are downstream of shadow outcomes, so the raw evidence layer also needs provenance

Implementation notes:
- this is persistence/auditability work only
- no strategy selection, paper/live order submission, broker routing, notional, slot policy, projected-gain floors, daily protection, live follower gates, or managed exits changed
- regression tests now cover proposal/outcome provenance in addition to order and fitness provenance

### Add runtime live-boundary guards
Decision:
- make explicit `CENTAUR_MODE=paper` skip Alpaca Live broker sync and live order mutation paths
- allow `live_dry` to carry intended live approvals but keep `execution_live` from submitting broker orders
- keep live broker order mutation restricted to runtime `live`
- add regression tests proving paper mode does not touch the live broker sync adapter and live_dry does not submit live orders

Why:
- the architecture refactor requires runtime mode to be an actual safety boundary, not just a label
- paper changes should be testable without accidentally touching live broker APIs
- live_dry should be useful for eligibility/risk review without real order placement

Implementation notes:
- the already-approved same-as-paper live follower remains active because legacy activation flags resolve runtime mode to `live`
- explicit `CENTAUR_MODE` still takes precedence, so an operator can force paper-only mode
- this does not change notional, strategy allowlists, projected-gain floors, daily protection, broker routing, or live activation requirements

### Make legacy live runtime labels honest
Decision:
- keep `CENTAUR_MODE` and `CENTAUR_ENVIRONMENT` as the explicit runtime source when they are configured
- for older `.env` files that predate these fields, report runtime `live/live` when the already-approved live activation flags are armed: `LIVE_EXECUTION_ENABLED=true`, `LIVE_EXECUTION_KILL_SWITCH=false`, and `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`
- leave unarmed or non-live configurations reporting `paper/paper` by default

Why:
- the current same-as-paper live follower lane was activated before the new runtime-mode settings existed
- showing `mode=paper` while Alpaca Live is armed is misleading for operators and for new evidence/provenance rows
- this keeps status truthful during the migration toward fully explicit runtime modes

Implementation notes:
- this is a transitional compatibility shim for existing configuration files
- explicit `CENTAUR_MODE`/`CENTAUR_ENVIRONMENT` still override the fallback
- this does not change paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits

### Persist broker order ledger provenance
Decision:
- add explicit provenance columns to `paper_trade_orders`: `environment`, `mode`, `source_environment`, `data_provider`, and `execution_provider`
- infer new order provenance from `broker_id` and proposal linkage: paper broker rows are `paper/paper`, live broker rows are `live/live`, live follower entries with proposal ids use `source_environment=paper`, and paper proposal-derived entries use `source_environment=shadow`
- backfill existing `*_live` broker rows as live rows
- show order `env` and `mode` in the status recent-order ledger

Why:
- the current order audit table contains both paper and Alpaca Live follower orders while the broader PostgreSQL paper/live separation is still being built
- live should be able to follow paper without order-history ambiguity
- future separation by database/schema will be safer if every order row already carries its runtime provenance

Implementation notes:
- this is persistence/auditability work only
- no paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits changed
- the table name remains legacy for now; the new metadata makes its mixed paper/live ledger role explicit until a later storage split/rename is safe

### Persist strategy fitness evidence-origin metadata
Decision:
- add explicit evidence-origin columns to `strategy_fitness_snapshots`: `environment`, `mode`, `source_environment`, `broker_id`, `data_provider`, and `execution_provider`
- add matching SQLite dev and PostgreSQL schema migration/index support
- label status, strategy-health, and crypto-health fitness output with the evidence source/environment
- keep current production fitness as shared shadow-derived strategy evidence unless a future explicit live-fitness lane is implemented

Why:
- separating paper/live databases or schemas must not make live blind, but live also must not mistake paper or shadow evidence for real-money outcomes
- the same Centaur strategy brain can consume reviewed paper/shadow/backtest evidence if every row remains auditable by origin
- future live promotion needs three distinct concepts: paper/shadow fitness evidence, explicit live strategy permission, and true live fitness from live fills/outcomes

Implementation notes:
- current runtime snapshots default to `source_environment=shadow` and `execution_provider=shadow`
- replay fitness snapshots record `source_environment=backtest`, `broker_id=simulator`, and `execution_provider=simulator`
- this does not change paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits

### Add adapter-first architecture instructions to the read-first stack
Decision:
- make `centaur-codex-architecture-instructions.md` part of the repo read-first stack
- record the target direction: Centaur core should own instruments, market snapshots, signals, proposals, strategy evaluation, fitness, risk, slot logic, order intents, exits, and reporting models
- put vendor market data, execution, broker/account, and symbol-mapping behavior behind adapters
- require explicit runtime modes (`shadow`, `paper`, `live_dry`, `live`) and separated paper/live configuration, persistence, evidence, permissions, logs, and runtime state
- align the architecture examples with the existing PostgreSQL-only rule for scheduler-backed paper/live operation and monitoring

Why:
- the operator wants to improve paper/research safely without accidental live impact
- future vendors such as Alpaca, Binance, Coinbase, Betfair, or Polygon should not require duplicating the strategy/risk/fitness brain
- the initial architecture draft used `.db` examples, but repo constraints already require PostgreSQL for live operation and fail-closed behavior when paper/live execution is enabled

Implementation notes:
- this is architecture/documentation guidance only
- no paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits changed
- SQLite remains only explicit local/dev scaffolding when execution is disabled; it must not become a scheduler-backed paper/live operations source

### Record the $50/day strategic growth target
Decision:
- document a strategic target of reaching a sustained, evidence-backed `$50/day` net profit pace
- expose the scaling report as `docs/FIFTY_DOLLAR_DAY_PLAN.md` and as a downloadable file from the root slot-compounding page
- make the target part of the project directives as a prioritization goal only

Why:
- the operator wants the project oriented around a concrete growth target instead of a vague "improve returns" mandate
- the current math shows `$50/day` requires more valid throughput, better net expectancy, cleaner exit/data reliability, and staged capital/slot scaling
- the target needs to be visible in future work without weakening the existing risk framework

Implementation notes:
- this does not change paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits
- any execution-envelope change still requires explicit approval and reliability-stack updates

### Make slot-compounding defaults use actual closed-trade metrics
Decision:
- add read-only `paper_trade_outcome_metrics` to the dashboard snapshot from closed Alpaca Paper round trips
- default the slot-compounding page from observed win rate, average winning-trade percent, average losing-trade percent, observed trade-throughput/slot-fill pace, and account-level tracked P/L
- show the implied loss rate as the remainder of win rate so lowering wins visibly raises losses

Why:
- the previous page mixed real account P/L with synthetic `100%` win-rate and `0%` loss defaults
- those placeholders made the projection look cleaner than the actual paper history
- the operator needs a realistic starting point before experimenting with alternate assumptions

Implementation notes:
- metrics are grouped from filled `alpaca_paper` buy/sell orders by proposal id
- this is an observability/projection change only
- it does not change paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits

### Refresh dashboard snapshots outside the control tick
Decision:
- keep `CONTROL_REFRESH_DASHBOARD_SNAPSHOT=false` so the normal 30-second control tick does not wait on dashboard/report snapshot work
- add a separate macOS `launchd` agent, `com.ghostfrog.centaur.dashboard-snapshot`, that runs `scripts/write_dashboard_snapshot.sh` every `300` seconds
- install the snapshot wrapper under `~/.centaur/write_dashboard_snapshot.sh` and log to `~/.centaur/runtime/dashboard_snapshot.log`
- use a lock directory so overlapping snapshot refreshes skip instead of stacking

Why:
- the browser dashboard and slot-compounding page read the saved `var/dashboard_snapshot.json`; refreshing the browser does not query Alpaca or PostgreSQL directly
- manual-only snapshot refresh made the dashboard look current while showing stale numbers
- separating dashboard freshness from the trading tick keeps operator data reasonably fresh without adding avoidable drag to the safety-critical control loop

Implementation notes:
- this is an observability/data-freshness change only
- it does not change paper/live order submission, broker routing, notional, slot policy, strategy allowlists, projected-gain floors, daily protection, live follower gates, or managed exits
- the snapshot file remains an operator surface; PostgreSQL remains the live operations source

### Tighten status and dashboard honesty labels
Decision:
- update status and web-dashboard wording so paper account values, live readiness, live execution intelligence, broker-order ledger rows, latest-tick activity, recent samples, all-time evidence, shadow-only recommendations, and observe-only risk evidence are clearly separated
- label crypto-only windows as such instead of showing a generic closed market card
- keep this as presentation and auditability cleanup only; do not alter paper/live execution gates, notional, exits, broker routing, strategy allowlists, or risk policy

Why:
- the same operator surfaces now carry paper execution state, live same-as-paper follower monitoring, shadow evidence, and observe-only risk observations
- ambiguous labels can make read-only intelligence look like active policy, or make broker-aware order history look paper-only
- the operator needs to read the dashboard quickly without confusing latest tick facts with broader evidence windows

Implementation notes:
- status now calls recent order rows `Recent broker orders (paper/live ledger, latest 5)` and includes `broker_id` in each rendered order line
- dashboard cards now distinguish `Paper day P/L`, `Paper positions`, `Paper CFO`, `Equity market gate`, and `Paper peak giveback`
- holding-window advice is labeled recommendation-only/shadow evidence, and live execution intelligence remains explicitly read-only
- the web build label is `2026-05-31-honest-status-labels`

### Add report/control-loop query indexes
Decision:
- add narrow operations-store indexes for regular status, dashboard, evidence, strategy-health, paper-exit, and holding-window query paths
- cover tick usage rollups, FX reference lookup by source, latest-bar windows, candidate-signal counts, paper-order activity, per-strategy paper-order review, proposal/order joins, and evaluated shadow outcomes
- keep this as a performance and auditability cleanup only; do not alter paper/live execution gates, notional, exits, broker routing, strategy allowlists, or risk policy

Why:
- Project rules now require database changes to be shaped so status/report paths do not drag on the control loop
- the operator is increasingly using evidence reports before changing behavior, so those reports need predictable query paths as data grows
- recent paper/live monitoring depends on distinguishing real activity from missing or slow evidence surfaces

Implementation notes:
- the new indexes are created in both SQLite dev schema and PostgreSQL operations schema so local/dev reports stay comparable to live operations behavior
- PostgreSQL schema bootstrap takes a transaction-scoped advisory lock so concurrent status/report starts cannot race each other while creating new indexes
- `paper_trade_orders` now has activity, broker-activity, strategy/side/status, and proposal/side/submitted indexes for recent-order, first-order, strategy-health, and paper-exit review paths
- `shadow_trade_outcomes` now has an evaluated-outcome partial index for strategy fitness and holding-window review joins
- `market_data_latest_bars`, `strategy_candidate_signals`, `api_request_events`, and `fx_reference_rates` gained indexes matching their bounded status/report lookups

### Fail closed on PostgreSQL operations-store loss
Decision:
- require `UsageLedger` to fail closed when PostgreSQL is configured but unavailable
- also require PostgreSQL when paper or live execution is enabled, even if a local SQLite path exists
- keep SQLite available only as an explicit local/dev path when execution is not enabled
- add an index shaped for the trailing high-water query: broker id plus equity descending plus capture time
- keep `main.py --status` on a lightweight heartbeat path: no dashboard-only visual datasets, and a bounded threshold-advice sample instead of the full GA

Why:
- live operation and monitoring must not silently read or write the wrong store
- a status surface backed by an empty fallback SQLite file can make the system look quiet when the real operations history is unavailable
- the trailing drawdown observer reads account snapshots on every tick, so its high-water lookup needs a matching index rather than a cleanup task later
- the full threshold GA is useful on demand but too expensive for routine status checks

Implementation notes:
- `UsageLedger` now raises when PostgreSQL is required but unavailable instead of falling back to SQLite
- `idx_broker_account_snapshots_high_water` supports the per-broker high-water lookup used by `trailing_drawdown_observer`
- additional indexes support recent tick, broker snapshot, and shadow proposal status/report queries
- `.venv-mac/bin/python main.py --threshold-advice` remains the full recommendation workflow

### Add evidence-reporting and database-quality directives
Decision:
- make evidence review a core project rule: any new feature that captures learning data must also add or update a runnable report, dashboard/status surface, or documented query path
- require the report surface to explain how the data should be interpreted before it is used to change trading behavior
- make high-quality code/documentation explicit: safety-critical logic and persistence paths need docstrings or compact comments that explain the risk boundary, audit trail, and operational intent
- make database performance part of feature completeness: new persistent/high-volume paths must consider indexes, bounded lookbacks, query shape, and control-loop impact

Why:
- the operator wants accumulating shadow/counterfactual data to become actionable evidence rather than forgotten telemetry
- reportable evidence makes it easier to decide when to promote an observe-only idea into active policy
- database drag can silently damage the trading loop, so persistence quality must be handled while the feature is built

Implementation notes:
- `AGENTS.md` now carries the directive at the project-instruction level
- `CONSTRAINTS.md` now blocks new evidence capture without a review surface and adds database-performance constraints
- `SKILL.md` now has an `Evidence Capture And Reporting` workflow
- broad report requests should start with `.venv-mac/bin/python main.py --evidence-report`

### Add observe-only trailing drawdown evidence
Decision:
- add a `risk.trailing_drawdown_observer` pipeline step that records high-water equity giveback by broker for the current market session
- keep it strictly observe-only: no CFO gate changes, no order cancellation, no forced exits, no live follower behavior changes, and no protection latch
- default the counterfactual thresholds to `$2.00` giveback for paper and `$2.00` giveback for live, with percent thresholds disabled at `0.00`
- expose the result in persisted tick snapshots, status output, trade diagnostics, and the web dashboard peak-giveback card
- add `.venv-mac/bin/python main.py --evidence-report` as the broad report entrypoint for listing all shadow/counterfactual streams before deciding actions

Why:
- the operator noticed a visible peak followed by a drop and asked whether Centaur could minimize loss with a high-water rule
- paper and live share the same codebase, and the system is showing early green shoots, so an active blocker would be premature
- observe-only data lets the project answer “would this have helped or made things worse?” before promoting anything into execution policy

Implementation notes:
- config flags: `TRAILING_DRAWDOWN_OBSERVER_ENABLED`, `TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_USD`, `TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_PCT`, `TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_USD`, and `TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_PCT`
- high-water evidence comes from `broker_account_snapshots`, so no new live operations source or SQLite fallback is introduced
- the evidence report currently indexes shadow checkpoints, profit-target ladder, holding-window advice, threshold advice, signal visibility, crypto health, live execution intelligence, trailing drawdown observer, and special exit reasons
- a future active guard would require a separate explicit human override and reliability-stack update

### Defer red max-hold managed exits
Decision:
- stop allowing `max_holding_window_elapsed` to be the sole reason to sell a red managed position for `profit_after_1h_else_1d` and `profit_capture_else_1d`
- when the max-hold point is reached and the current reference price is below entry, defer the exit with skip reason `max_hold_red_deferred`
- keep stop loss, profit capture, take profit, and Friday equity no-weekend-carry exits active
- keep notional, broker routing, strategy allowlist, projected-gain floors, one-order-per-tick discipline, slot caps, and daily drawdown protection unchanged

Why:
- a `LINK/USD` paper position and the same-as-paper live follower sold at a small loss solely because the `1d` max-hold timer elapsed
- the operator objected that this was bad behavior when the trade had not hit its stop
- the max-hold rule should not convert a modest unrealized loss into a realized loss by itself; deterministic protective exits should remain responsible for actual loss exits

Implementation notes:
- `profit_after_1h_else_1d` still sells after one hour when profitable and still sells at max hold when not red
- `profit_capture_else_1d` still sells at profit capture, target, stop, or a non-red max-hold exit
- red deferrals should be monitored because they can tie up slots; future work can add a read-only report for open `max_hold_red_deferred` positions and compare later outcomes

### Add equity no-weekend-carry guard
Decision:
- keep Friday equity trading available for most of the regular session
- block new equity paper entries in the final `60` minutes of the regular Friday session
- flatten managed equity paper positions in the final `15` minutes of the regular Friday session with exit reason `friday_no_weekend_carry`
- leave crypto unchanged because crypto can trade through the weekend
- keep `$10` notional, broker routing, strategy allowlist, stop loss, profit capture, projected-gain floors, one-order-per-tick discipline, slot caps, and daily drawdown protection unchanged

Why:
- a calendar `1d` backstop can expire on Saturday for Friday equity entries, creating Monday forced exits that are driven by timing rather than a fresh thesis check
- banning all Friday equity trading would discard about one trading day per week
- a Friday intraday/no-weekend-carry rule reduces weekend gap exposure while preserving most Friday opportunity

Implementation notes:
- config flags: `PAPER_EXECUTION_EQUITY_NO_WEEKEND_CARRY_ENABLED=true`, `PAPER_EXECUTION_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE=60`, and `PAPER_EXECUTION_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE=15`
- the CFO gate rejects late-Friday equity entries with `friday_entry_cutoff_no_weekend_carry`
- managed exits check stop loss, profit capture, and take profit before the Friday flatten reason, so protective/profit exits keep their more specific audit reason when they trigger
- live follower entry selection inherits the same late-Friday equity entry cutoff because live can only follow paper-approved/submitted orders; live managed exits use the same managed-exit helper and therefore share the flatten reason after activation gates
- this is a capital-preservation rule, not evidence that weekend carry is always bad; future review should compare `friday_no_weekend_carry` outcomes with Monday-open and Monday-close counterfactuals before loosening it

## 2026-05-29

### Activate Alpaca Live by explicit operator override
Decision:
- accept the operator's explicit 2026-05-29 go-live instruction to turn on Alpaca Live
- activate only the already recorded same-as-paper follower lane
- flip only the three activation controls: `LIVE_EXECUTION_ENABLED=true`, `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`, and `LIVE_EXECUTION_KILL_SWITCH=false`
- keep all other first-live controls unchanged: `$10` entries, `10` base slots, one order per tick, `$5.00` live daily protector, equities plus crypto, current paper strategy allowlist, same-tick submitted-paper-order follow rule, shared paper/shadow strategy fitness, and read-only live execution intelligence

Why:
- the remaining blocker was not technical readiness; it was explicit operator authorization
- the operator provided that authorization in plain language after the account was funded and the first-live policy was recorded
- the small fixed envelope keeps first live bounded while still matching the paper lane as requested

Pre-activation read-only check:
- checked at about `2026-05-29 10:48 BST`
- Alpaca Live status: `ACTIVE`
- trading blocked: `false`
- account blocked: `false`
- user trade suspended: `false`
- cash/equity/buying power: `132.05`
- live positions: `0`
- recent live orders: `0`
- open live orders: `0`
- live daily protection: `active`
- live daily-protection baseline: `132.05`
- live daily drawdown: `0.0`
- local guard before activation: blocked with `live_execution_disabled`
- latest scheduler control tick before activation: `OK`

Rollback rule:
- immediately set `LIVE_EXECUTION_KILL_SWITCH=true` if any live behavior is surprising
- set `LIVE_EXECUTION_ENABLED=false` as the hard rollback if needed
- do not widen notional, slots, strategy allowlist, asset classes, projected-gain floors, or daily loss limits without a separate explicit override

### Record first-live activation plan
Decision:
- record the first-live policy before any live flags are changed
- use a same-as-paper Alpaca Live follower lane by operator request, rather than the safer generic one-strategy default
- allow only the current paper execution strategies for first live: `mean_reversion.snapback`, `crypto_momentum.trend`, and `momentum.volatility_breakout`
- keep the live lane dependent on same-tick paper approval and same-proposal paper order submission
- treat the observed `132.05` account balance as funding readiness, while keeping the launch operating envelope at `$10 x 10 = $100`

Why:
- the operator explicitly wants live to be "same as paper" once enabled
- the repo needs the difference between "ready for the final switch" and "live trading enabled" to be auditable
- same-as-paper is acceptable only because the hard capital envelope remains small and live can only follow paper-submitted orders

Implementation notes:
- first-live asset classes: equities and crypto
- first-live notional: `$10`
- first-live base slots: `10`
- first-live max orders per tick: `1`
- first-live daily live drawdown protector: `$5.00`
- first-live projected-gain floors: `1.5%` equities and `2.0%` crypto
- first-live limit buffers: `5` bps equities and `25` bps crypto
- extra funds above `$100` are buffer only and do not create additional launch slots
- rollback triggers include unexpected live positions/orders, account blocks or suspensions, unmatched live-vs-paper orders, surprising fill/status drift, stale live orders that cannot be refreshed, unavailable account equity, the `$5.00` protector triggering, or operator discomfort
- rollback action is to set `LIVE_EXECUTION_KILL_SWITCH=true`, set `LIVE_EXECUTION_ENABLED=false` if needed, stop new entries, inspect/manage positions deliberately, and record the reason
- this records readiness for a final explicit go-live override; it does not enable live trading, clear the kill switch, or set `LIVE_EXECUTION_ACTIVATION_ACK`

Post-activation observation:
- first fully live-enabled observed tick: `20260529-105313`
- tick status: `OK`
- live sync still showed `0` positions and `0` open orders with `132.050` equity/cash
- live CFO decision was `hold` with reason `no_paper_approved_trade_to_follow`
- live execution submitted `0` orders and saved `0` orders
- post-activation read-only check still showed `0` live positions, `0` recent live orders, and `0` open live orders

### Record Alpaca Live funded read-only check
Decision:
- record that the initial Alpaca Live funds are visible and read-only funded checks passed
- keep all live execution gates closed until an explicit go-live override records strategy policy, limits, and rollback rules
- preserve the intended `$10 x 10` envelope even though the live balance is now above `$100`

Why:
- funded account visibility is the final external prerequisite before a go-live decision, but it is not itself permission to trade
- the actual credited balance is slightly above the planned bankroll model, so the docs must state that it does not widen risk

Implementation notes:
- Alpaca Live account status is `ACTIVE`, not trading-blocked, not account-blocked, and not user-suspended
- cash, equity, and buying power are `132.05`
- read-only positions/orders checks returned `0` positions, `0` recent orders, and `0` open orders
- the local live adapter guard still blocks a test buy with `live_execution_disabled`
- `alpaca_live.sync` completed in read-only mode; live daily protection is `active` with baseline equity `132.05`, drawdown `0.0`, and max daily drawdown `5.0`
- this does not enable live execution, clear the kill switch, set the activation acknowledgement, or approve live-money trading

### Record Alpaca Live read-only key check
Decision:
- record that Alpaca Live API keys have been added locally and passed the first read-only checks
- keep all live execution gates closed while waiting for funds to appear
- treat valid keys and an active account as connectivity/readiness only, not go-live approval

Why:
- live API access is a real boundary, so the exact read-only result should be auditable before any future activation discussion
- the account currently has no funds, positions, or orders, which is the expected safe state before the initial deposit credits

Implementation notes:
- config detects Alpaca Live credentials
- read-only Alpaca Live account check returned `ACTIVE`, not trading-blocked, not account-blocked, and not user-suspended
- read-only positions/orders checks returned `0` positions, `0` recent orders, and `0` open orders
- cash, equity, and buying power were `0.0`, so the next external wait is funds crediting
- the local live adapter guard still blocks a test buy with `live_execution_disabled`
- the `alpaca_live.sync` pipeline step completed in read-only mode and live daily protection remained blocked with `live_equity_unavailable`
- this does not enable live execution, clear the kill switch, set the activation acknowledgement, or approve live-money trading

### Record Alpaca Live account-approval waiting state
Decision:
- record that Centaur is waiting for Alpaca Live account approval before any live-money go-live
- treat account approval as a prerequisite only, not as permission to trade live
- preserve the dormant live settings until read-only live key/account checks and an explicit go-live override are recorded

Why:
- the live readiness lane is now mechanically prepared, so the remaining human/process steps need to be written down before account approval arrives
- account approval can create a false sense of readiness even though API keys, read-only validation, first-live limits, rollback rules, and reliability-stack updates still need to happen

Implementation notes:
- `docs/GO_LIVE_CHECKLIST.md` now includes a current waiting state and ordered next steps after account approval
- `PROGRESS.txt` and `docs/PROJECT_RECORD.md` now record that account approval is the current external wait
- this does not add live credentials, enable live execution, clear the kill switch, set the activation acknowledgement, or approve live-money trading

### Require doc blocks for safety-critical trading paths
Decision:
- make docstrings or compact nearby comments mandatory for safety-critical trading paths
- require those notes to explain the gate, capital-protection reason, and audit trail for live execution, broker adapters, risk gates, daily protection, stale-order handling, managed exits, and persistence writes

Why:
- the operator wants the system ready enough that live-vs-paper behavior can be audited without guessing intent from code shape alone
- trading code ages badly when the reason for a guard is separated from the guard itself
- comments should protect capital by explaining non-obvious boundaries, not cluttering obvious assignments

Implementation notes:
- `CONSTRAINTS.md` now contains a documentation and auditability rule
- `SKILL.md` now reminds future work to keep safety-path doc blocks aligned
- live readiness hardening functions now carry focused docstrings/comments around activation gates, cancellation, stale-order reaping, daily protection, and submitted-paper-order following
- this changes documentation discipline only; it does not enable live trading or alter risk settings

### Harden Alpaca Live mechanics to match paper while keeping gates closed
Decision:
- add the missing live-side protective mechanics so the dormant lane can be called operationally same-as-paper once deliberately activated
- keep live entries blocked by default with `LIVE_EXECUTION_ENABLED=false`, `LIVE_EXECUTION_KILL_SWITCH=true`, missing credentials, and empty activation acknowledgement
- require live entries to follow only same-tick paper approvals that paper execution actually submitted

Why:
- API keys and a future enable flag should not expose a weaker live lane than paper
- cancellation, stale-entry reaping, managed exit refresh, live account readiness, and durable daily protection are protective controls, not optional conveniences
- live should share the same strategy/fitness brain as paper at first while keeping its own broker/account/order safeguards

Implementation notes:
- Alpaca Live cancellation is now guarded instead of scaffold-blocked, requiring credentials, live enablement, and `LIVE_TRADING_APPROVED`
- live buy entries remain blocked while the live kill switch is on; guarded sell exits can still be submitted after activation so protective exits are not blocked by the entry kill switch
- live daily protection now persists and latches by broker/session in `broker_daily_protection_state`
- the default pipeline now runs `maintenance.live_stale_orders` for stale live equity entry limits
- live managed exits now cancel and replace stale or non-marketable open sell exits like paper
- the live CFO gate checks the live account's own trade-ready state and follows only paper orders that were actually submitted on the same tick
- this does not add live credentials, enable live execution, clear the kill switch, set the activation acknowledgement, or approve live-money trading

### Add read-only live execution intelligence
Decision:
- add a separate live execution intelligence surface to status snapshots and the web dashboard
- keep strategy intelligence shared through the existing shadow-fitness scorecard instead of giving live its own independent strategy scorer
- compare future `alpaca_live` entry orders against same-proposal paper entry orders by `proposal_id`
- report recent paper/live entry sample counts, matched live followups, unmatched live entries, status mismatches, average absolute fill drift in bps, example fill pairs, and current live blockers

Why:
- live and paper should use the same market data and strategy decision brain at first
- the live lane still needs its own execution intelligence because real fills, rejects, partial fills, and account state can diverge from paper
- surfacing divergence is safer than letting live learn independently from a tiny and noisy real-money sample

Implementation notes:
- `StatusReporter.snapshot()` now includes `live_execution_intelligence`
- CLI status renders a `Live execution intelligence` section
- the web dashboard renders the same read-only monitor
- this is observability only; it does not activate live trading, score independent live strategy fitness, change broker routing, or loosen any risk gate

### Prepare Alpaca Live readiness to mirror paper while keeping real orders blocked
Decision:
- configure the dormant Alpaca Live readiness envelope to mirror the current paper envelope where live has matching controls
- set live readiness to equities plus crypto, the same paper strategy allowlist, `$10` notional, `10` base slots, one order per tick, `$5.00` daily drawdown protector, `1.5%` equity projected-gain floor, `2.0%` crypto projected-gain floor, `5` bps equity marketable-limit buffer, and `25` bps crypto marketable-limit buffer
- add live-specific crypto projected-gain and crypto limit-buffer config fields so the live readiness lane can actually match paper crypto settings instead of using the equity defaults
- keep live order submission blocked by default with `LIVE_EXECUTION_ENABLED=false`, `LIVE_EXECUTION_KILL_SWITCH=true`, missing Alpaca Live credentials, and empty `LIVE_EXECUTION_ACTIVATION_ACK`

Why:
- the operator wants the live lane prepared so only the protected go-live controls remain after live API credentials are added
- readiness should match the proven paper envelope rather than accidentally using weaker crypto admission or fill settings
- API keys and the enable flag alone must still be insufficient because the repo requires an explicit go-live override and rollback record before live-money submission

Implementation notes:
- `.env` and `.env.example` now expose `LIVE_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT=0.02` and `LIVE_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS=25.0`
- `_build_live_trade_approval()` now uses the crypto-specific live projected-gain floor for crypto proposals
- live managed exits now use the crypto-specific live limit buffer for crypto positions
- status readiness output includes the live crypto projected-gain and limit-buffer fields
- this does not turn on live trading, lower the live kill switch, add live credentials, set the live activation acknowledgement, or remove the same-tick paper-approved-trade requirement

## 2026-05-28

### Potential breakthrough: treat paper as a micro system
Decision:
- record the 2026-05-28 operating hypothesis as a potential breakthrough, not a proven edge
- evaluate the paper lane as `$10` micro entries with small exits and many repetitions
- keep larger targets in shadow/counterfactual learning unless later evidence supports using them for real paper exits

Why:
- the operator clarified the intended model: "we only do big profit when we do big trades"
- the system had been mixing a micro trade size with entry/exit behavior that often acted as though it needed larger-trade moves
- once high-score near-miss entries were allowed and `1.25%` profit capture was active, the system resumed placing paper trades and showed visible small green P/L
- the suspected failure mode is that hard fitness suppression and oversized exits had been preventing the micro edge from expressing itself

Validation plan:
- measure how often `1.25%` profit capture fires
- compare average win, average loss, and stop-hit frequency
- use the profit-target ladder to see whether `2%`, `3%`, `4%`, or `6%` would have hit after the actual small capture
- do not raise notional, widen live execution, or remove stops based on this observation alone

### Record profit-target ladder counterfactuals
Decision:
- record a shadow profit-target ladder for each evaluated checkpoint using `SHADOW_PROFIT_TARGET_LADDER_PCT=1.25,2,3,4,6`
- keep the actual paper managed exit at `1.25%`
- surface target-hit counts in the paper-exit review so the operator can see whether higher exits would have worked

Why:
- taking the small profit is the operating rule, but the system must learn whether waiting for `3%`, `4%`, or the old larger target would have been better
- this gives that answer without risking open paper positions or changing broker behavior

Implementation notes:
- `evaluate_shadow_checkpoint()` now stores `profit_target_ladder` in `shadow_trade_outcomes.raw_json`
- `PaperExitReview` now reads those ladder outcomes and reports `target_hits`

### Add paper-only high-score near-miss override
Decision:
- by explicit human override, allow already approved paper strategies with raw `signal_score >= 90.0` to survive fitness suppression when their composite fitness is within `0.25` of the active suppress threshold
- keep `$10` notional, one-order-per-tick, stop requirements, projected-gain floors, broker routing, the paper strategy allowlist, daily protection, and live execution unchanged
- keep disallowed strategies blocked even when their signal score is high

Why:
- the current `$10` micro-trade plan is to take small paper entries and bank a `1.25%` profit capture, but the fitness gate was still vetoing high-scoring near misses before CFO could size them
- on 2026-05-28, a `mean_reversion.snapback` signal scored `92` but was suppressed because fitness `-6.889` was only slightly below the active `-6.800` threshold
- this treats fitness as a guardrail for near misses rather than a total veto when the current setup score is strong

Implementation notes:
- `PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED=true`
- `PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE=90.0`
- `PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN=0.25`
- the allocator records `allocation_status=high_score_override` and counts `high_score_overrides` for status visibility

### Extend crypto paper exits to a 1d backstop
Decision:
- by explicit human override, change `crypto_momentum.trend` paper managed exits from the prior `60m` time exit to `profit_capture_else_1d`
- keep the `1.25%` profit capture, existing stop loss, existing larger target, `$10` notional, Alpaca Paper routing, one-order-per-tick cap, strategy allowlist, daily protector, and live safe-off policy unchanged
- allow crypto positions that hit neither stop, profit capture, nor target to remain open until a `1d` max-hold backstop

Why:
- the 2026-05-28 SOL trade exited slightly down with `holding_window_elapsed` after the old `60m` crypto window, even though the new operating theory is to take small wins but avoid forcing otherwise intact crypto trades out too early
- if the stop is still valid and the position has not hit the profit capture, a `60m` forced exit can realize noise instead of giving the trade room under the defined risk plan
- this aligns crypto with the same capital-preservation spirit as `mean_reversion.snapback`: bank profits when available, keep stops active, and use a finite `1d` backstop rather than an open-ended hold

Implementation notes:
- `_paper_managed_exit_policy()` now returns `profit_capture_else_1d` for `crypto_momentum.trend`
- `_paper_exit_policy_holding_window_minutes()` and `_paper_max_hold_window_minutes()` now return `1440` minutes for `crypto_momentum.trend`
- entry approval, notional, projected-gain floors, and live execution policy are unchanged

### First profitability check: exits before entries
Decision:
- make exit-target and holding-window review the first profitability diagnosis when Centaur is not compounding
- before loosening entries, suppress thresholds, strategy allowlists, discovery knobs, or broker behavior, inspect whether paper trades are giving back small meaningful wins because the configured target is too high or the hold is too long
- use actual paper exits, `--paper-exit-review`, `--holding-window-advice`, and filled exit reasons to answer this before changing entry rules

Why:
- live crypto observation on 2026-05-28 showed AAVE was meaningfully up well before the old `~6%` crypto target
- recent non-crypto `mean_reversion.snapback` review showed several cases where `15m` shadow outcomes were better than later outcomes
- this means weak profitability can come from exit design even when entry scanning, broker routing, and CFO approval are functioning
- changing entry thresholds first can admit weaker trades while leaving the real leak untouched

Implementation notes:
- the immediate runtime change from this diagnosis is the `1.25%` paper profit capture
- the durable operating habit is broader: review exit realism first whenever paper P/L looks poor or idle trading is followed by small wins fading away
- this note is intentionally prominent so future diagnostics start at the right layer

### Add a 1.25 percent paper profit capture
Decision:
- by explicit human override, set `PAPER_EXECUTION_PROFIT_CAPTURE_PCT=0.0125`
- allow paper managed exits for both equities and crypto to sell when the latest bar reaches `1.25%` above the filled/average entry reference
- keep entry projected-gain floors unchanged: equities still require `1.5%` projected gain and crypto still requires `2.0%` projected gain before entry approval
- preserve notional, stops, broker routing, strategy allowlists, slot caps, daily protection, and live execution policy

Why:
- operator review of the live crypto positions showed small meaningful gains, such as roughly `+1.15%` on AAVE, could appear well before the old `~6%` crypto target
- recent non-crypto snapback review also showed evidence that some early positive moves later faded or stopped out
- a `1.25%` capture is above the micro-friction floor and lets Centaur bank a meaningful `$10`-scale win without changing the entry gate into a lower-quality trade filter

Implementation notes:
- `RuntimeConfig` now exposes `paper_execution_profit_capture_pct`
- `_build_exit_order_request()` checks the configured capture level before the larger strategy target
- submitted exit audit payloads persist `planned_profit_capture_pct` and `planned_profit_capture_price`

### Normalize crypto symbols for managed exits
Decision:
- normalize Alpaca crypto symbols in paper managed-exit lookups
- allow slashless position symbols such as `AAVEUSD` and `SOLUSD` to match stored entry plans and latest bars keyed as `AAVE/USD` and `SOL/USD`
- keep the existing crypto stop, target, and `60` minute time-exit policy unchanged

Why:
- live diagnosis found filled crypto paper positions were being reported by Alpaca without slashes while Centaur's entry plans and bars retained slash-separated symbols
- the paper exit monitor therefore skipped at least one crypto position with `missing_entry_plan`
- capital preservation requires managed exits to find their original stop/target/time plan reliably

Implementation notes:
- `_latest_bars_by_symbol()` now indexes both exact and normalized symbols
- `_find_latest_managed_entry_order()` compares normalized symbols
- paper and dormant live exit paths use normalized symbols when checking open exits and latest bars

### Split paper crypto limit buffer to 25 bps
Decision:
- by explicit human override, add `PAPER_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS=25.0` for paper crypto marketable-limit orders
- keep the shared `PAPER_EXECUTION_LIMIT_BUFFER_BPS=5.0` for non-crypto paper orders
- preserve `$10` notional, Alpaca Paper routing, one order per tick, slot caps, strategy allowlists, projected-gain floors, daily protection, and all live-execution gates

Why:
- same-day diagnosis found that Centaur approved and submitted three paper crypto IOC buy orders, but Alpaca Paper canceled each one with `filled_qty=0`
- widening only the crypto limit buffer makes those IOC limits more marketable while keeping the actual order size and risk envelope unchanged
- equities were not given this wider buffer because their current blocker is shadow-fitness suppression, not IOC fillability

Implementation notes:
- `RuntimeConfig` now exposes `paper_execution_crypto_limit_buffer_bps`
- paper entry approval uses the crypto buffer only when `asset_class=crypto`; equities continue to use the shared buffer
- paper managed exits also resolve the paper buffer by asset class, so any future crypto paper exit can use the crypto-specific marketable-limit buffer while live exits remain unchanged

### Lower the crypto-only discovery floor to 2.5
Decision:
- by explicit human override, lower `CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE` from `4.5` to `2.5`
- keep the rest of the crypto-specific lane unchanged: stop loss `3.0%`, target multiple `2.0`, min signal score `60`, min movement `0.15%`, min trade count `2`, crypto suppress threshold `-6.90`, and the crypto-specific projected-gain floor `2.0%`

Why:
- overnight diagnosis showed crypto was scanning normally across the widened `11`-pair universe and selecting candidates, but `strategy.signals` kept ending with `signals_generated=0` and `signals_suppressed=0`
- that meant the crypto candidates were dying inside `crypto_momentum.trend` before suppression or CFO review
- recent overnight top discovery scores around `1.3` to `3.0` were consistently below the prior `4.5` floor, so loosening the crypto discovery gate was the cleanest direct way to allow more candidates to reach actual signal generation

Implementation notes:
- `.env` and `.env.example` now expose `CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE=2.5`
- no strategy code change was required because `crypto_momentum.trend` already reads that value from runtime config
- this is a crypto-only entry-rule relaxation; it does not widen equity rules, notional, broker routing, or the paper/live risk envelope

## 2026-05-27

### Tighten the unattended cadence to thirty seconds with busy-skip locking
Decision:
- by explicit human override, change the unattended `launchd` interval from `60` seconds to `30` seconds
- ensure the installed wrapper takes a lock and exits cleanly when a previous control tick is still running
- keep dashboard snapshot refresh off the critical path so the faster scheduler is spending its time on trading, not UI work

Why:
- once the dashboard snapshot work was removed from the control path, the real trading pipeline was measuring around `22` to `25` seconds, which made a `30` second scheduler a reasonable next experiment
- a faster schedule is only safe if overlapping launches do not stack, so the wrapper needs an explicit skip-if-busy guard
- this change increases how often Centaur can look without widening order size, risk limits, or strategy allowlists

Implementation notes:
- `.env` and `.env.example` now set `CONTROL_TICK_INTERVAL_SECONDS=30`
- `ops/com.ghostfrog.centaur.control.plist` now uses `StartInterval=30`
- `scripts/install_launch_agent.sh` now installs a wrapper that creates a lock directory and skips if another tick is already running
- the live launch agent must be reinstalled/restarted so the active wrapper and plist pick up the new cadence

### Disable automatic dashboard snapshot refresh during headless trading
Decision:
- by explicit human override, disable automatic `var/dashboard_snapshot.json` refresh after each normal control tick in the current headless trading mode
- keep `write_dashboard_snapshot()` and `scripts/dashboard_snapshot.py` available as manual or separately scheduled operator actions

Why:
- recent runtime investigation showed the trading pipeline itself was finishing in roughly `22` to `25` seconds, while the full process was taking much longer to exit
- the post-tick snapshot path rebuilds a large `StatusReporter().snapshot()` payload and was the clearest non-trading candidate for stretching the effective cadence beyond the intended `60` seconds
- when Centaur is simply being left to trade, operator-surface refresh should not block the control loop and risk missing faster opportunities

Implementation notes:
- `.env`, `.env.example`, and `RuntimeConfig` now expose `CONTROL_REFRESH_DASHBOARD_SNAPSHOT=false`
- `main.py` now guards the `write_dashboard_snapshot()` call behind that config flag
- the manual snapshot script remains in place for on-demand dashboard refreshes

### Split the suppress threshold by asset class
Decision:
- by explicit human override, keep the existing adaptive suppress-threshold lane for equities
- add a separate fixed crypto suppress threshold and loosen it to `STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD=-6.90`
- keep the same `$10` notional, one-order-per-tick cap, broker routing, daily protector, and crypto-specific entry knobs

Why:
- crypto had gained its own entry filters and projected-gain floor, but it was still being judged against the same global suppress line as equities
- overnight checks confirmed the widened crypto universe was live and fetching bars, but crypto still rarely surfaced and remained suppressed
- after the split was added, the current `crypto_momentum.trend` fitness still sat around `-6.85`, so the first crypto-specific line at `-6.20` was still too strict to admit the current lane
- loosening the crypto threshold to `-6.90` is the narrowest simple change that should let the current crypto fitness band survive without touching equity thresholds

Implementation notes:
- `.env`, `.env.example`, and `RuntimeConfig` now expose `STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD=-6.90`
- the allocator now accepts per-asset-class suppress thresholds
- equities still use the current adaptive effective threshold, while crypto now uses the fixed crypto-specific threshold
- status/adaptive diagnostics now show the separate crypto suppress threshold so the split is visible to the operator

### Add a single-command overnight crypto health report
Decision:
- add a read-only `main.py --crypto-health` command
- make it summarize recent `crypto_only_window` ticks, crypto bar-fetch activity, raw-vs-suppressed crypto strategy visibility, selected overnight crypto candidate symbols, and the latest crypto fitness snapshot
- keep it observability-only; it must not change runtime behavior or any paper/live policy

Why:
- the operator now needs a fast answer to "is Centaur actually seeing crypto overnight?" without repeating ad hoc PostgreSQL checks
- overnight crypto questions are different from the broader strategy-health report because they depend on market-window behavior, bar fetches, candidate flow, and suppression patterns
- a single command gives a stable operator workflow for checking whether widened crypto coverage is translating into real signal flow

Implementation notes:
- the report lives in `centaur/crypto_health_report.py`
- it is exposed through `main.py --crypto-health`
- it reports the configured crypto universe, recent overnight tick counts, crypto bar-fetch counts, raw/suppressed crypto preview symbol counts, selected overnight candidate symbols, and the latest crypto fitness rows

### Widen the crypto universe from five to eleven USD pairs
Decision:
- by explicit human override, expand both the Alpaca crypto list and the live discovery list from `5` to `11` USD pairs
- add `LTC/USD`, `BCH/USD`, `LINK/USD`, `AVAX/USD`, `UNI/USD`, and `AAVE/USD` to the existing `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, and `DOGE/USD`
- keep the same paper envelope: `$10` notional, `1` order per tick, the daily protector, broker routing, and the stricter crypto-specific knobs all stay unchanged

Why:
- the current crypto universe was genuinely capped at five pairs, which limits how many opportunities `crypto_momentum.trend` can even see
- expanding the universe is a reasonable way to give crypto more chances without changing size or loosening risk gates
- this should be treated as an opportunity-set expansion, not as proof that the current crypto strategy is suddenly good; its stored fitness still needs to improve

Implementation notes:
- `.env`, `.env.example`, and the runtime default in `centaur/config.py` now all list the same `11` USD pairs
- the market scan and crypto bar-fetch paths already read `discovery_crypto_symbols`, so no new execution logic was needed
- this change widens observability and candidate generation only; whether a crypto trade reaches paper execution still depends on fitness, projected-gain, and the existing CFO gate

### Split crypto_momentum.trend onto its own conservative runtime knobs
Decision:
- by explicit human override, give `crypto_momentum.trend` its own config knobs instead of relying only on the shared shadow defaults
- keep the shared paper envelope unchanged: `$10` notional, `1` order per tick, shared suppress-threshold rails, broker routing, and the `$5.00` daily protector all stay in place
- add a crypto-specific paper projected-gain floor of `2.0%` while leaving the equity floor at `1.5%`

Why:
- crypto does not trade on the same market-hours rhythm or microstructure as the equity strategies, so it deserves its own entry-quality controls even if it remains under the same capital-preservation envelope
- recent evidence showed `crypto_momentum.trend` was weak and fully suppressed, so the right first step is to make its lane configurable and conservative rather than silently loosening it
- separate knobs let future tuning happen without distorting the equity strategy defaults

Implementation notes:
- `.env` now exposes `CRYPTO_MOMENTUM_STOP_LOSS_PCT=0.03`
- `.env` now exposes `CRYPTO_MOMENTUM_TARGET_MULTIPLE=2.0`
- `.env` now exposes `CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE=60.0`
- `.env` now exposes `CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT=0.15`
- `.env` now exposes `CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE=4.5`
- `.env` now exposes `CRYPTO_MOMENTUM_MIN_TRADE_COUNT=2`
- `.env` now exposes `PAPER_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT=0.02`
- `crypto_momentum.trend` now reads those dedicated settings from `RuntimeConfig`
- paper trade approval and the threshold adviser now both use the crypto-specific projected-gain floor for crypto proposals so observability and runtime approval stay aligned

### Add a single-command strategy health report for operator diagnosis
Decision:
- add a read-only `main.py --strategy-health --strategy-id <strategy>` command
- make it bundle actual paper P/L by strategy, recent closed-trade drift, exit-reason damage, proposal counts, signal visibility, the paper-exit post-mortem, and holding-window advice
- keep it observability-only; it must not change runtime behavior or paper/live policy

Why:
- the operator kept needing the same cluster of answers: who actually made the money, whether `snapback` is weakening, whether exits are the problem, and whether other strategies are absent or suppressed
- running several separate commands and ad hoc SQL checks is too fragile for routine use
- a single deterministic report lowers the friction to diagnose future red stretches quickly and consistently

Implementation notes:
- the report lives in `centaur/strategy_health_report.py`
- it is exposed through `main.py --strategy-health --strategy-id <strategy>`
- the command reuses the existing paper-exit and holding-window advisers and adds direct ledger summaries for paper P/L, proposals, candidate signals, and recent tick-preview activity

### Tighten the paper-only threshold rails after the recent red drift
Decision:
- by explicit human override, raise the fixed suppress threshold from `-5.70` to `-5.60`
- raise the adaptive fallback floor from `-6.50` to `-6.40`
- restore the adaptive cliff-governor safety gap from `0.05` to `0.10`
- keep `$10` notional, broker routing, allowed strategies, projected-gain gate, stop loss, target logic, and managed exit policy unchanged

Why:
- recent paper weakness was driven more by weak newly admitted `mean_reversion.snapback` entries hitting stop loss than by obviously bad exit timing
- the current weak tradeable cliff was clustering around composite fitness `-6.77`, which had only become admissible after the same-day relaxation to the `0.05` cliff gap
- the operator wants Centaur to keep trading, but not by continuing to admit the weakest recent band

Implementation notes:
- `.env` now sets `STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD=-5.60`
- `.env` now sets `STRATEGY_THRESHOLD_ADAPTIVE_FLOOR=-6.40`
- `.env` now sets `STRATEGY_THRESHOLD_ADAPTIVE_CEILING=-5.60` to keep the adaptive ceiling aligned with the fixed suppress threshold
- `.env` now sets `STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP=0.10`
- this is an entry-selection tightening only; it does not change exit timing or any paper/live capital rules

### Add a default 7d shadow checkpoint for longer-hold post-mortems
Decision:
- extend the default shadow checkpoint trail from `15m,1h,1d` to `15m,1h,1d,7d`
- surface the `7d` outcome in the read-only paper-exit post-mortem and holding-window advice outputs
- keep this change observability-only; it must not alter live paper exits, notional, broker routing, or CFO approval rules

Why:
- the operator needs a durable answer to "what if we had held longer?" before changing exit policy
- recent review showed that `1d` sometimes improves on `1h`, but that still does not tell us whether a longer recovery window would have helped
- recording a default `7d` checkpoint gives that evidence without widening risk or silently changing behavior

Implementation notes:
- `.env` and the runtime default now include `SHADOW_CHECKPOINT_WINDOWS=15m,1h,1d,7d`
- the shadow evaluator already supports day-based checkpoints, so this adds no new live execution path
- status, the web dashboard summary, and `main.py --paper-exit-review` now surface the longer checkpoint when enough data exists

### Reduce the adaptive cliff-governor safety gap to restart paper entries
Decision:
- by explicit human override, reduce the paper-only adaptive cliff-governor safety gap from `0.10` to `0.05`
- keep the current `-6.50` fallback floor, `0.10` max step, `$10` notional, broker routing, strategy allowlist, projected-gain gate, and daily protector unchanged
- leave the GA confidence gate and cooldown unchanged

Why:
- on 2026-05-26, live market-open ticks were still scanning the full equity universe and generating raw signals, but every current proposal-viable `mean_reversion.snapback` signal was being suppressed around composite fitness `-6.768817`
- the cliff governor refused to loosen because the nearest blocked cliff was `-6.859063`, and the old `0.10` safety-gap rule required a minimum safe threshold of `-6.75`
- reducing the gap to `0.05` is the narrowest policy relaxation that can admit the current allowed cliff without reopening the much weaker `-11` / `-12` momentum bands

Implementation notes:
- the adaptive controller now reads a dedicated `STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP` setting instead of implicitly tying the cliff-governor gap to the local band width
- the configured value on this Mac is now `0.05`
- status output now shows the active cliff-gap setting alongside the other adaptive-threshold rails

## 2026-05-26

### Replace the blunt 1h paper exit for mean_reversion.snapback
Decision:
- by explicit human override, replace the old `holding_window_elapsed` paper exit for `mean_reversion.snapback`
- keep the current stop-loss and target logic unchanged
- allow profitable positions to exit after `1` hour
- allow non-profitable positions to continue until the `1d` max-hold backstop

Why:
- dumping purely because one hour elapsed is too blunt and was no longer trusted
- recent review suggested the old `1h` timeout was not clearly defensible as the main exit reason
- this changes only managed exit timing for one already-allowed paper strategy; it does not widen notional, broker routing, or entry approval rules

Implementation notes:
- the managed paper exit plan is now persisted as `profit_after_1h_else_1d` for new `mean_reversion.snapback` entries
- status and the web dashboard now show the active managed-exit policy for open positions
- the one-day backstop remains in place, so this is not an open-ended hold override

### Refresh stale managed paper exits
Decision:
- allow paper managed exits to cancel and replace an open sell exit when its limit is no longer marketable or has gone stale
- persist the cancellation and replacement in the paper-order audit trail

Why:
- an old sell limit can hold the fractional quantity and cause the exit monitor to skip with `exit_order_already_open`
- if price moves below that sell limit, the order no longer gets us out of the position
- capital preservation needs the managed exit to keep trying with a fresh marketable limit rather than silently waiting

Implementation notes:
- this applies to paper sell exits only
- it does not change entry approvals, notional, broker routing, stop/target rules, or live activation
- status now reports refreshed exit count in the trade diagnostics path

### Add a repeatable paper-exit post-mortem command
Decision:
- add an on-demand CLI review that compares actual paper exits with stored `15m` / `1h` / `1d` shadow outcomes for the same proposal ids
- keep the review read-only and recommendation-only
- reuse the existing `--strategy-id` selector so the same operator flow works for any strategy with enough history

Why:
- recent exit-quality review was useful, but ad hoc SQL is too fragile for normal operations
- the operator needs a deterministic way to separate entry quality, exit timing, and execution drift
- exit review should be easy to rerun without changing live paper behavior or widening risk

Implementation notes:
- `python3 main.py --paper-exit-review --strategy-id mean_reversion.snapback` now renders recent and all-time summaries plus recent example trades
- the review joins filled paper entries, the latest persisted paper exit per proposal, and stored shadow checkpoint returns
- this is observability and learning only; it does not alter the current `1h` managed paper exit rule

## 2026-05-20

### Add earned-slot compounding for paper and future live lanes
Decision:
- add one effective open-position slot for each full `$10` of tracked P/L above that broker lane's pre-first-order baseline
- keep per-order notional fixed at `$10`
- make the earned slots dynamic, so the extra slot disappears if tracked P/L falls below the full `$10` increment

Why:
- the paper account has made roughly `$13` while operating with a base `10 x $10` capital envelope
- the operator wants profit to expand capacity by whole `$10` slots rather than increasing individual trade size
- dynamic slots preserve the "earned capital only" idea more cleanly than manually changing `.env`

Implementation notes:
- the paper CFO gate now uses effective slots instead of the static configured max
- the dormant live CFO gate uses the same rule once live has its own first-order baseline and P/L
- this changes capacity only; it does not change `$10` notional, broker routing, strategy allowlists, projected-gain, daily-protection, stale-order, market-hours, long-only policy, or live activation gates

### Prepare a dormant same-signal Alpaca Live follower lane
Decision:
- add live account/order sync, live daily-loss checking, live CFO gating, and live execution steps to the default pipeline
- add a dormant live managed-exit step that reuses the persisted entry plan for stop/target/holding-window exits
- keep the lane disabled by default and require multiple explicit activation gates before any real-money order submission
- require a same-tick paper-approved trade before live can consider following it; this was later hardened to require a submitted paper order on that same tick

Why:
- first production should use the same signal/fitness brain as paper rather than invent a separate live strategy
- live and paper account state may diverge, so live still needs separate position, order, slot, and drawdown checks
- API keys alone must not be enough to place real-money trades

Implementation notes:
- at that time, `.env` kept `LIVE_EXECUTION_ENABLED=false`, `LIVE_EXECUTION_KILL_SWITCH=true`, and an empty live allowlist
- live order submission also requires `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`
- this does not activate live trading, change paper notional, alter paper broker routing, or widen strategy/risk policy

## 2026-04-16

### Surface the Centaur activity trail when no paper order is placed
Decision:
- expose raw strategy-signal previews, fitness-suppressed signal previews, surviving signals, proposal counts, and CFO blocker reasons in the status and lightweight dashboard surfaces

Why:
- a quiet Alpaca dashboard can mean the system is correctly filtering weak or unsafe signals, not that the scheduler is idle
- the operator needs to see the difference between "no scan", "no raw signals", "raw signals suppressed by fitness", "proposals blocked by CFO", and "orders submitted"
- the visibility layer should explain decisions without changing trade behavior, broker routing, notional size, or risk gates

Implementation notes:
- the strategy allocation step now keeps capped diagnostic previews for raw and suppressed signals in the persisted tick snapshot
- `python3 main.py --status` renders a `Centaur activity` section from the latest tick
- the stripped-down Tk dashboard also includes that same activity trail in the quick diagnostics panel
- this is observability only; it does not make suppressed signals trade

## 2026-04-09

### Start the multi-broker refactor with Alpaca first
Decision:
- introduce a broker-adapter layer, but move the existing Alpaca path behind it first before activating any second broker

Why:
- the current Alpaca paper loop is already working and should not be broken just to make the architecture prettier
- we need a boring, stable base interface before adding IG specifics
- this lets us refactor safely without interrupting the live paper/shadow flow

Implementation notes:
- Alpaca account, clock, positions, orders, submit, and cancel behavior now route through an `AlpacaBrokerAdapter`
- the pipeline still keeps its current Alpaca-shaped state keys so status/dashboard surfaces do not have to be rewritten all at once
- live routing remains explicitly set to Alpaca for both equities and crypto

### Scaffold IG as a veto-first adapter
Decision:
- add an `IG` adapter scaffold, but keep it inactive for execution

Why:
- the whole reason for adding IG is to explore GBP-native execution without USD conversion friction
- but the repo’s `$10` cap and capital-preservation rules mean most spread-bet sizing may simply be too large to allow
- the system must reject unsafe IG trades before it ever tries to place them

Implementation notes:
- the scaffold includes:
  - ticker-to-EPIC resolution hooks
  - a simple bet-per-point sizing estimate
  - veto logic for minimum bet size exceeding the fixed notional cap
  - veto logic for implied exposure above `1x` leverage
- order placement and account sync for IG remain intentionally disabled

### Persist broker identity on paper trades
Decision:
- add `broker_id` to persisted paper-trade records

Why:
- once there is more than one broker, mixed trade history becomes misleading
- we need broker-separated execution audit trails before we add a second execution target
- this is the smallest safe database seam for the refactor

Implementation notes:
- `paper_trade_orders` now stores `broker_id`
- existing Alpaca rows default to `alpaca_paper`
- newly submitted or polled orders carry their broker identity into persistence

## 2026-04-01

### Allow Gemini analysis to be disabled while keeping the adapter
Decision:
- add a config flag so the Gemini analysis stage can be turned off without removing the Gemini client code
- switch the live runtime into function-only mode for now

Why:
- Google API cost was mounting up faster than the operator wanted
- Gemini is already outside the critical path for strategy generation and paper execution
- keeping the adapter lets us re-enable cloud or local LLM commentary later without rebuilding the integration from scratch

Implementation notes:
- `GEMINI_ANALYSIS_ENABLED=false` now disables the live Gemini stage cleanly
- the pipeline still runs, but `analysis.gemini` reports `disabled` instead of calling the API
- status and runtime logs now state that Gemini analysis is disabled so the cost change is visible

### Temporarily disable the standalone Graphs tab
Decision:
- hide the dedicated `Graphs` tab in the Tk dashboard for now while debugging UI sluggishness

Why:
- the extra redraw work for those charts may be contributing to the app feeling unresponsive
- removing that tab is a low-risk way to isolate whether it is the culprit
- the account, fitness, costs, and document tabs still provide the core monitoring surfaces

Implementation notes:
- the chart-drawing code for the standalone `Graphs` tab is skipped for now
- the other chart panels inside `Account`, `Fitness`, and `Costs` remain active

### Temporarily disable all dashboard tabs
Decision:
- hide the remaining dashboard tabs as well and run the Tk monitor in a single flat view

Why:
- the operator still saw the GUI becoming unresponsive
- removing the entire tabbed surface is a cleaner isolation step than disabling one tab at a time
- a single text-first monitor keeps the system observable while reducing UI complexity

Implementation notes:
- the dashboard now shows the alert banner, full status summary, diagnostics, recent activity, and runtime/wrapper log tails in one view
- the tab-specific account, fitness, cost, and document panes are temporarily not mounted

### Temporarily disable dashboard log tails
Decision:
- stop rendering the runtime-log and wrapper-log tail panes inside the Tk monitor for now

Why:
- those panes rewrite a lot of text every refresh
- removing them is another low-risk way to test whether UI churn is what makes the dashboard feel sluggish
- scheduler visibility still exists through the status summary and external log files if needed

Implementation notes:
- the single-view monitor now keeps alerts, the full status summary, diagnostics, and recent activity
- the two live log-tail text widgets are temporarily not mounted or updated

### Temporarily disable dashboard recent activity
Decision:
- stop rendering the recent-activity panel inside the Tk monitor for now

Why:
- even more live-updating text is being removed to isolate the cause of sluggishness
- the operator wants to see whether a more minimal monitor feels better
- alerts plus the full status summary still preserve the important operational truth

Implementation notes:
- the single-view monitor now keeps only the alert banner, the full status summary, and the diagnostics panel

### Stop taking two full status snapshots per dashboard refresh
Decision:
- make the Tk dashboard reuse one lighter snapshot per refresh instead of calling the full status pipeline twice

Why:
- hidden duplicate work can still make the GUI feel sluggish even after panels are removed
- the dashboard only needs a subset of the full status surface in its current stripped-down mode
- eliminating duplicate snapshot work is a direct way to reduce refresh latency

Implementation notes:
- the dashboard now calls `snapshot(include_visuals=False, include_logs=False)` for its own refresh loop
- the rendered summary text is produced from that same snapshot instead of calling `render()` with a second fresh snapshot

## 2026-03-26

### Use Gemini API as the current LLM layer
Decision:
- Gemini API is the only LLM in the stack for now.

Why:
- there is no local LLM available yet
- an adapter boundary lets us swap models later without rewriting trading logic

### Build the system as pipelines, not one monolithic agent
Decision:
- the system should be split into clear pipelines with LangGraph-compatible orchestration.

Why:
- responsibilities stay isolated and testable
- risk gates become easier to reason about
- the system remains auditable

### Do not log raw chain-of-thought
Decision:
- audit logs should store structured summaries, scores, and rule checks rather than raw chain-of-thought

Why:
- safer operationally
- easier to query and review
- avoids over-collecting sensitive or low-value reasoning text

### Use an external scheduler for ticks
Decision:
- run one control tick per scheduler invocation instead of a permanent in-process heartbeat loop

Why:
- more reliable if a run crashes
- cleaner state boundaries
- easier to debug and test
- simpler to control overlap

### Use cron for the current Mac-hosted scheduler
Decision:
- install a cron job that runs the control tick every minute on weekdays

Why:
- simple and already available
- enough for the current proof-of-concept

Notes:
- the machine must remain awake
- lock screen is fine, sleep is not

### Use Postgres as the operations store
Decision:
- persist operational data in PostgreSQL, with SQLite only as a local fallback

Why:
- central source of truth
- better fit for accumulating market, shadow, and fitness data

### Record API usage and estimated cost
Decision:
- every provider call should be recorded with source, request counts, and estimated cost

Why:
- spending must stay visible
- provider usage should be auditable
- it helps catch accidental cost creep early

### Start with shadow trading before paper execution
Decision:
- generate pretend trades first and score them later before sending any paper orders

Why:
- safer
- lets us build labeled outcomes
- gives the fitness layer real data to work with

### Keep Gemini out of the critical path for shadow proposals
Decision:
- the shadow proposal engine should be rule-based, not dependent on Gemini

Why:
- deterministic logic is cheaper and easier to trust
- strategy evaluation and fitness should be auditable
- the AI layer should help interpretation, not own the core trading engine

### Treat strategies and profiles as pluggable strategy-pattern components
Decision:
- create reusable strategy families with tunable profiles

Why:
- easier to compare variants side by side
- good fit for later GA mutation and selection
- avoids hard-coding one trading idea forever

### Use historical replay to accelerate training
Decision:
- reuse stored historical bars to generate many more shadow outcomes without waiting on live cron

Why:
- live collection alone is too slow
- replay gives scale at zero extra API cost
- the system needs far more outcomes before any profitability claim is meaningful

### Add chunked replay execution
Decision:
- run replay in date chunks so larger ranges can be processed safely and repeatably

Why:
- easier to run big training batches
- cleaner failure recovery
- avoids manual replay commands over and over

### Keep the CFO gate on hold for now
Decision:
- no paper orders should be submitted yet

Why:
- execution plumbing is not complete
- strategy quality is still being established
- safety should stay ahead of ambition

## 2026-03-27

### Prefer launchd over cron on this Mac
Decision:
- use a macOS `launchd` agent as the primary unattended scheduler for the control tick

Why:
- cron did not prove reliable enough overnight in this environment
- `launchd` is the native scheduler on macOS
- it is better suited to long-lived local automation on a Mac Mini

Status:
- preferred direction, but still not fully verified in this environment yet

### Allow crypto collection and scanning outside US equity hours
Decision:
- decouple crypto collection from the stock-market gate so crypto bars and crypto shadow proposals can continue overnight

Why:
- crypto trades 24/7
- tying it to the US equity clock was causing us to miss useful overnight data
- the system should keep learning from crypto even when stocks are closed

### Keep unattended runtime logs off the external project volume
Decision:
- write scheduler wrapper logs and unattended runtime logs to the home directory instead of the external-drive repo path

Why:
- the background scheduler could read the repo on `/Volumes/Bob/...`
- but it could not reliably write runtime log files into the repo from the unattended launch context
- moving runtime logs local fixed unattended launchd execution while keeping the repo itself on the external drive

### Enable micro paper execution with hard gates
Decision:
- allow a very small Alpaca Paper execution path, but only under strict limits

Why:
- we now need to learn broker behavior, not just shadow outcomes
- seeing real paper orders, statuses, and fills is the next practical feedback loop
- keeping it tiny reduces risk while still letting the system exercise the execution path

Current guardrails:
- paper only
- equities only
- market open required
- one open slot at a time across positions and in-flight orders
- one order max per tick
- `$10` default notional target
- only `mean_reversion.snapback` is currently allowed

Implementation notes:
- recent Alpaca orders are now polled each tick
- broker responses are persisted in `paper_trade_orders`
- if the market is closed or no eligible proposal passes the CFO gate, Centaur still holds

### Add a dedicated status command
Decision:
- add a one-shot status view instead of relying on raw logs alone

Why:
- it is much easier to tell whether Centaur is healthy, armed, and active from one readable summary
- broker visibility matters more now that paper execution is enabled
- it reduces the need to inspect Postgres and log files manually for routine checks

### Add a local desktop monitor
Decision:
- add a lightweight Tkinter desktop dashboard for the Mac instead of waiting for a full native app bundle

Why:
- `tkinter` is already available with the local Python install
- it gives an immediate visual monitor with no extra dependencies
- it is enough to watch ticks, CFO state, shadow proposals, paper orders, and log tails while we keep the core trading system simple

### Switch this Mac setup to Postgres-only operations
Decision:
- require PostgreSQL for live ticks, status views, and the desktop dashboard on this machine

Why:
- silent fallback to SQLite created confusing stale-monitor behavior
- the live scheduler and operations data are already established in Postgres
- clear failure is better than quietly showing the wrong dataset

### Replace fractional bracket entries with simple managed paper orders
Decision:
- stop submitting fractional bracket entries to Alpaca Paper
- submit simple market entry orders instead
- manage exits inside Centaur using latest bars plus the planned stop, target, and holding window

Why:
- Alpaca Paper rejected the old order shape with `fractional orders must be simple orders`
- the `$10` micro-size mode naturally produces fractional equity quantities
- keeping the size tiny matters more right now than broker-native bracket support
- a managed exit loop preserves the intended risk plan without raising position size

### Surface paper-execution failures as first-class alerts
Decision:
- show recent paper-order failures and their broker error messages directly in `--status` and the dashboard

Why:
- execution problems were too easy to miss in raw logs
- the operator needs to know whether Centaur is failing because of strategy scarcity or broker rejection
- historical errors should stay visible until replaced by a newer submission outcome

### Add a deterministic volatility-breakout strategy in shadow mode
Decision:
- add `momentum.volatility_breakout` as a rule-based strategy before allowing any LLM involvement or paper execution for it

Why:
- this setup is fully deterministic and auditable, which makes it a better fit for shadow learning and fitness scoring
- the project needed a genuine breakout profile instead of only momentum, mean-reversion, and liquidity variants
- the ATR-based stop, target, and break-even logic can be evaluated consistently in replay and live shadow mode

Implementation notes:
- the signal requires a 20-bar breakout above the prior high, 2.0x average volume, and ATR above 1 percent of price
- it is currently evaluated across the enriched candidate set every tick, not only the top selected watchlist subset
- the break-even trailing rule is modeled conservatively as `break_even_next_bar` to avoid intrabar ambiguity with bar-level data
- proposal metadata for ATR, volume ratio, breakout level, and break-even trigger is now persisted in the operations store

### Make the dashboard show untrained strategies explicitly
Decision:
- extend the dashboard graphs so every registered strategy appears, even when it has no proposals or fitness rows yet

Why:
- otherwise a new strategy looks invisible until it happens to generate enough history to reach the top-fitness chart
- the operator needs to distinguish between `not installed`, `installed but idle`, and `installed with poor performance`

Implementation notes:
- the graphs tab now includes strategy coverage, proposal counts by strategy, and a dedicated `momentum.volatility_breakout` activity view
- `0` values are now a meaningful state, not missing visibility

### Split recent strategy activity from all-time training volume
Decision:
- show recent `7d` proposal counts separately from all-time proposal and outcome totals in the dashboard

Why:
- recent-window charts were being mistaken for the full training sample size
- replay writes historical proposal timestamps, so a strong all-time strategy can still look quiet in a recent slice
- the operator needs to see both freshness and total evidence at the same time

### Add a ranked strategy leaderboard with explanation
Decision:
- rank strategies in the dashboard by their current best fitness row and explain in plain English why the current leader is on top

Why:
- operators were correctly reading the charts as ambiguous about what “best” actually meant
- sample size matters, so the dashboard should show both ranking and evidence strength together
- a plain-language explanation is more useful than forcing the operator to infer the ranking from multiple separate charts

### Backfill the root reliability-stack files
Decision:
- create root-level `AGENTS.md`, `CONSTRAINTS.md`, `DECISION_LOG.md`, `SKILL.md`, and `PROGRESS.txt`

Why:
- the repo needed a read-first reliability stack instead of relying on chat memory and scattered docs
- the operator explicitly wants those files to steer future work
- the root-level files make constraints and current state visible before any task begins

## 2026-03-28

### Score shadow and replay outcomes with execution friction
Decision:
- apply configurable spread and slippage assumptions to shadow and replay outcome scoring instead of assuming perfect fills

Why:
- perfect fills were overstating the apparent quality of strategies
- the project needs more honest fitness numbers before trusting replay results
- this improves realism without widening the live paper-trading envelope

Implementation notes:
- added `SHADOW_EXECUTION_SPREAD_BPS`
- added `SHADOW_ENTRY_SLIPPAGE_BPS`
- added `SHADOW_EXIT_SLIPPAGE_BPS`
- the evaluator now stores gross and friction-adjusted return details in the outcome payload

### Add operator-facing open-position and trade diagnostics
Decision:
- expand `--status` and the dashboard with an open-position view and a dedicated trade-diagnostics view

Why:
- the operator needs to see why Centaur is idle without reading raw logs
- paper positions need a visible summary of unrealized PnL, stored stop/target, and exit state
- broker behavior is easier to trust when the current blocker is explicit

Implementation notes:
- diagnostics now show the primary CFO blocker, flow counts, capacity, and exit-monitor status
- open positions now show stop, target, unrealized PnL, and the current exit-monitor reason

### Surface Alpaca account day-change and balance data
Decision:
- add an account summary to status and the dashboard using the live Alpaca paper account snapshot

Why:
- the operator wants the same simple “am I up?” answer they can already see in Alpaca

## 2026-03-31

### Show day P/L in GBP as well as USD
Decision:
- add a second dashboard header badge for day P/L in GBP using the stored ECB USD/GBP reference rate

Why:
- the operator is in the UK and wants the same quick top-level read in local currency
- the dashboard should not force a mental conversion from dollars every time
- using the same FX source as the rest of Centaur keeps the number consistent and auditable

### Surface the paper capital envelope directly
Decision:
- show the current paper bankroll envelope directly in status and the Account tab

Why:
- the operator thinks about the paper bankroll as `$10` notional times `10` slots, or roughly `$100`
- that limit should be visible as `max / committed / free`, not hidden behind separate account fields
- making the envelope explicit makes the planned production bankroll easier to reason about

### Add a paper pace versus investing comparison view
Decision:
- add a small comparison panel that contrasts Centaur’s current paper-trading pace with simple 5%, 10%, and 20% annual investing yardsticks on the same bankroll cap

Why:
- the operator wants to understand how active trading differs from stable long-term investing
- a bankroll-relative comparison is more intuitive than Alpaca’s giant default paper account size
- the panel should educate without implying that a short paper streak proves durable outperformance

Implementation note:
- anchor the panel to the last persisted account tick before the first paper order, not the mutable paper-order row's current tick identifier
- this keeps later Alpaca order polling from silently rewriting the comparison baseline

## 2026-03-30

### Widen the paper envelope by explicit human override
Decision:
- accept an explicit human override to widen the paper-trading envelope
- raise the max open paper-position slots from `1` to `10`
- enable crypto paper execution
- swap equity discovery from the curated list to the full Nasdaq-100 universe

Why:
- the operator wants more paper activity than a single-slot equity-only loop can realistically produce
- crypto trades outside US market hours and gives the system more live execution opportunities
- a full Nasdaq-100 discovery set is a cleaner broad equity universe than the earlier hand-picked starter list

Implementation notes:
- `$10` default notional remains unchanged
- max orders per tick remains `1`
- `momentum.volatility_breakout` initially remained shadow-only after this override
- paper allowlist was widened only to `mean_reversion.snapback` and `crypto_momentum.trend`
- equities still require market-open approval, while crypto can be approved during the `crypto_only_window`
- balance and day-change numbers are easier to grasp quickly than raw position metadata alone
- the account summary belongs next to the existing open-position and diagnostics panels

Implementation notes:
- show equity, last equity, day change, cash, buying power, position value, and open-position P/L
- derive day change from Alpaca `equity` and `last_equity` fields in the stored account snapshot

### Give the account view its own dashboard tab
Decision:
- move the account/balance focus into a dedicated `Account` tab and add a small day-P/L badge in the dashboard header

Why:
- the operator wants balance and position profit/loss to be easier to find than a buried panel inside `Status`
- a dedicated account area keeps `Status` focused on system health while still making P/L obvious
- the day-P/L badge provides the same quick “am I up?” signal the Alpaca UI gives

### Add written strategy-selection and go-live checklists
Decision:
- create explicit checklists for strategy selection and any future paper-to-live decision
- expose both documents as readable dashboard tabs

Why:
- the operator asked for a concrete standard instead of deciding by feel
- sparse live paper frequency should not force fuzzy judgment
- the go-live boundary is important enough to deserve written, reviewable criteria

Implementation notes:
- `docs/STRATEGY_SELECTION_CHECKLIST.md`
- `docs/GO_LIVE_CHECKLIST.md`
- both are available as dashboard document tabs

### Preserve managed exit plans after Alpaca order polling
Decision:
- treat persisted stop/target columns as a valid managed entry plan even if the latest broker `raw_json` no longer carries the original planned fields

Why:
- order polling can overwrite the raw broker payload
- previously opened paper positions were at risk of looking unmanaged even though the plan had been persisted
- the managed exit loop should rely on durable stored metadata, not only the freshest broker JSON

### Add an API cost visibility tab and flag incomplete pricing
Decision:
- add a dedicated API cost view to status and the dashboard
- explicitly warn when internal provider pricing is unset so the displayed cost estimate is known to be incomplete

Why:
- the operator needs to see project spend clearly now that Gemini usage is real
- internal request counts alone are not enough when the provider billing console shows non-zero spend
- a visible warning is better than silently presenting `$0.00` as if it were final truth

### Pin Gemini pricing to a concrete official model
Decision:
- stop leaving Gemini pricing at zero in the environment
- pin the current config to `gemini-2.5-flash` with official Developer API token pricing

Why:
- the internal cost dashboard needs real rates to produce meaningful estimates
- `gemini-flash-latest` is an alias, which makes cost accounting fuzzy
- pinning the model and rates makes the budget view much more honest

Implementation notes:
- `GEMINI_MODEL=gemini-2.5-flash`
- `GEMINI_INPUT_COST_PER_MILLION_TOKENS_USD=0.30`
- `GEMINI_OUTPUT_COST_PER_MILLION_TOKENS_USD=2.50`

### Add a one-shot historical API cost repricing pass
Decision:
- support a one-shot command that recalculates stored API costs from current provider pricing and rebuilds the dependent rollups

Why:
- earlier Gemini usage rows were recorded before pricing was configured, so the internal dashboard understated real spend
- the repo already stores request counts and Gemini token units, which makes a best-effort repricing pass feasible
- status and dashboard views should stay internally consistent after repricing, not show fixed daily totals with stale per-tick budget fields

Implementation notes:
- `python3 main.py --backfill-api-costs`
- reprices `api_request_events` from current provider pricing
- rebuilds `api_daily_usage`
- refreshes `control_tick_runs.tick_estimated_cost_usd`, `daily_estimated_cost_usd`, and `budget_status`
- remains best-effort because events without recorded units cannot be retroactively made exact

### Harden micro-trade economics for the `$10` paper regime
Decision:
- add a fixed per-trade friction floor to shadow and replay scoring
- reject paper proposals whose projected gain is too thin for the micro notional
- replace raw market paper orders with marketable limit orders that respect Alpaca's supported fractional-order rules

Why:
- on `$10` trades, a few cents of drag matter materially to the monthly outcome
- the existing spread/slippage model was directionally useful but still too forgiving for micro-account economics
- raw market orders were the least defensive execution style available in the paper path
- Alpaca supports fractional equity limit orders, but not `IOC` time-in-force for fractional equities, so the broker-valid implementation has to distinguish equities from crypto

Implementation notes:
- `SHADOW_FIXED_ROUND_TRIP_COST_USD=0.03` adds a configurable pessimistic round-trip drag in shadow and replay scoring
- `PAPER_EXECUTION_MIN_PROJECTED_GAIN_PCT=0.015` blocks proposals below a `1.5%` projected gain
- paper buys and sells now build `limit` orders
- fractional equities use `DAY` limit orders
- crypto uses `IOC` limit orders
- the execution reference price is still bar-based, because Centaur does not yet maintain a live order-book or quote stream

### Add a persisted daily drawdown protector and stale-order reaper
Decision:
- persist a daily equity baseline in Postgres keyed to the active market session
- block new paper entries once the session drawdown reaches `$5.00`
- add an in-pipeline stale-order reaper for untouched equity buy limits older than `5` minutes

Why:
- a micro account can still die by many individually small cuts
- using open-equity drawdown is safer than realized-only loss
- fractional equity `DAY` limits need a second line of defense so old entry intents do not fill hours later in a changed market
- keeping both protections inside the main control pipeline preserves the existing `launchd` cadence, lock, and audit trail

Implementation notes:
- `daily_protection_state` is now persisted in Postgres
- the market-session baseline is anchored to the most recent `09:30 ET` business-session boundary
- the protector latches to `protected` for the session once triggered
- the CFO gate now holds new entries when protection is active
- the stale-order reaper only targets untouched open equity buy limit orders

### Persist broker account snapshots before activating multi-broker execution
Decision:
- persist live account state by `broker_id` in `broker_account_snapshots`
- use that persisted broker-aware view in status and dashboard surfaces
- keep IG visible only as scaffold status until explicit activation, rather than faking live account data

Why:
- multi-broker reporting gets messy fast if account history is still implicitly "the Alpaca account"
- separating account state now lets us add IG later without polluting Alpaca summaries or paper-history interpretation
- the operator needs to see which broker a balance belongs to before any execution routing becomes broker-aware

Implementation notes:
- live Alpaca ticks now write broker-tagged account snapshots to Postgres
- status renders both the active Alpaca account summary and a broker-separated account section
- `ig_spreadbet` appears as scaffold-only when no live account snapshot exists yet

### Preserve exact fractional exit quantities for Alpaca managed exits
Decision:
- use the broker-reported position quantity string for managed exits
- format Alpaca exit quantities to 9 decimal places with `ROUND_DOWN`
- skip quantities that would floor to zero instead of sending a zero-quantity sell

Why:
- the old 6-decimal formatting rounded some fractional positions up, so Alpaca rejected exits as `insufficient qty available`
- some tiny fractional remnants formatted to zero, so Alpaca rejected exits as `qty must be > 0`
- for closing a broker-reported position, exact-or-down is safer than any rounding that can increase the requested sell quantity

Implementation notes:
- Alpaca managed exits now pass the raw position `qty` string into the adapter
- the Alpaca adapter performs Decimal-based down-rounding at 9 fractional decimals
- this does not widen risk or change the active broker; it only prevents invalid exit payloads

### Enable `momentum.volatility_breakout` for micro paper execution
Decision:
- add `momentum.volatility_breakout` to `PAPER_EXECUTION_ALLOWED_STRATEGIES`
- keep Alpaca Paper as the active broker for equities and crypto
- keep `$10` notional, one order per tick, max ten slots, the `1.5%` projected-gain floor, and the `$5.00` daily protector unchanged

Why:
- after the April 14 managed exits, Centaur had free slots but no allowed-strategy proposals
- `momentum.volatility_breakout` was the top current fitness strategy, but could not be used for paper execution while shadow-only
- enabling it is a deliberate, narrow test of a promising strategy rather than a broad relaxation of CFO rules

Implementation notes:
- this was done by explicit human override on 2026-04-15
- the strategy remains experimental; replay evidence is not treated as proven live edge
- the first paper proposals/orders from this strategy should be watched closely

### Lower the strategy-allocation suppress threshold after a seven-day flatline
Decision:
- set `STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD=-5.25`
- keep `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, and daily-protection rules unchanged

Why:
- from 2026-04-14 to 2026-04-21, Centaur recorded 9,147 ticks, zero shadow proposals, zero approved trades, and zero buy entries
- raw signals were being generated, but every recent raw signal was suppressed before the shadow-proposal stage
- `mean_reversion.snapback` is already paper-allowed, but its relevant fitness was sitting just below the previous `-5.0` suppress threshold
- a threshold of `-5.25` is a narrow calibration rather than a broad risk-envelope expansion

Implementation notes:
- this was done by explicit human override on 2026-04-21

## 2026-04-22

### Prepare Alpaca Live as a scaffold-only sidecar lane
Decision:
- add an `alpaca_live` broker adapter identity and config surface for a possible May 2026 go-live discussion
- keep Alpaca Paper as the only active execution broker
- keep Alpaca Live order submission and cancellation blocked in the adapter at that stage; this was later superseded by guarded live cancellation/readiness plumbing while live entries stayed disabled by default
- expose live-readiness state in status/dashboard output without polling or trading the live account by default

Why:
- paper and live should run side by side if the project ever goes live, rather than silently swapping the existing paper endpoint to real money
- live history, credentials, kill switches, and risk limits must be visibly separate from paper
- preparing the lane now reduces last-minute go-live risk while preserving the current `No live-money trading` constraint

Implementation notes:
- live config defaults to `LIVE_EXECUTION_ENABLED=false` and `LIVE_EXECUTION_KILL_SWITCH=true`
- live defaults mirror the planned micro bankroll model of `$10` x `10` slots = `$100`
- the live strategy allowlist defaults to empty
- status now shows `Live readiness` with blockers such as disabled mode, kill switch, missing credentials, missing activation ack, and scaffold-only order pipeline
- a future activation must update `CONSTRAINTS.md`, this decision log, and `docs/GO_LIVE_CHECKLIST.md` before any real-money order path can be enabled
- this does not change broker routing, notional size, strategy allowlist, market-hours requirements, max orders per tick, max open positions, the `1.5%` projected-gain gate, or the `$5.00` daily drawdown protector
- future paper entries after this change should be treated as evidence-gathering, not proof that the strategy has live edge

## 2026-05-05

### Lower the strategy-allocation suppress threshold after the second flatline
Decision:
- set `STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD=-5.50`
- keep `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, and daily-protection rules unchanged

Why:
- live `launchd` ticks, Postgres persistence, market gating, and broker connectivity were all healthy, so the flatline was not an infrastructure failure
- recent raw signals were still being suppressed before proposal creation
- `mean_reversion.snapback` was repeatedly landing just below the previous `-5.25` suppress threshold at roughly `-5.409`
- a threshold of `-5.50` is a deliberate loosening of the fitness allocator, but it still leaves clearly weaker scores such as `-6.859` and `-11.232` suppressed

Implementation notes:
- this was done by explicit human override on 2026-05-07
- this does not change broker routing, notional size, strategy allowlist, market-hours requirements, max orders per tick, max open positions, the `1.5%` projected-gain gate, or the `$5.00` daily drawdown protector

## 2026-05-07

### Move the default dashboard path to a local web server
Decision:
- add a lightweight local web dashboard server that renders the existing `StatusReporter` snapshot into a browser-friendly operator view
- repoint `main.py --dashboard` at that web server and keep the older Tk monitor behind an explicit `--dashboard-desktop` flag
- keep that direct Python web server as a fallback surface, not the primary routed dashboard

Why:
- the Tk dashboard proved brittle enough that it no longer made sense as the main operator surface
- the status snapshot was already the right source of truth, so the cleanest change was to swap the presentation layer rather than rewrite monitoring logic
- this improves usability without touching trading, broker, risk, or policy behavior

Implementation notes:
- the web dashboard stays on the same Python runtime and reads the same persisted Postgres-backed snapshot data
- the Tk dashboard code remains in the repo as a legacy fallback, but it is no longer the default path

### Move the primary dashboard route to DDEV/OrbStack
Decision:
- serve the main operator dashboard from DDEV/OrbStack at `https://ghostfrog-centaur.ddev.site`
- have the host Python runtime refresh `var/dashboard_snapshot.json` after each control tick
- let the routed dashboard read that snapshot file instead of trying to make the DDEV container talk directly to the Mac-local Postgres instance

Why:
- proper routing and a normal browser URL were the actual goal, not another localhost process
- the host tick already has the right Postgres access, while the DDEV container should stay focused on presentation
- using a snapshot-file bridge avoids brittle host-database networking tricks inside OrbStack while preserving the same source-of-truth status data

Implementation notes:
- `web/index.php` is the routed dashboard surface and `web/api/snapshot.php` serves the latest stored snapshot
- `main.py` now refreshes the dashboard snapshot file after each normal control tick as a best-effort operator-surface update
- the direct Python web server and Tk monitor remain in the repo as fallbacks, but the DDEV route is now the primary operator path

### Persist a compact per-tick blocker summary
Decision:
- persist a `tick_blockers` summary inside each tick snapshot
- surface that summary in status alongside the existing activity trail

Why:
- recent trade-drought diagnosis required stitching together market gating, suppressed-signal counts, proposal counts, CFO reasons, and exit skip reasons across multiple tables
- the system needed a truthful per-tick explanation for why it did not buy or sell, not just a single top-level `hold` reason

Implementation notes:
- the summary records the primary stage blocker, market reason, CFO reason, rejection-reason counts, and exit-skip counts
- this does not change trading policy or broker behavior; it only improves auditability and operator visibility

## 2026-05-14

### Replace the fixed adaptive floor with a local cliff band and absolute hard floor
Decision:
- set `STRATEGY_THRESHOLD_ADAPTIVE_FLOOR=-6.10`
- add `STRATEGY_THRESHOLD_ADAPTIVE_BAND_WIDTH=0.10`
- keep the adaptive ceiling at `-5.70`, max adjustment at `0.10`, minimum confidence at `medium`, minimum evidence at `120` ticks, and cooldown at `30` minutes

Why:
- the first adaptive controller still required manual help when the useful `mean_reversion.snapback` cliff drifted from roughly `-5.80` to roughly `-5.95`
- a fixed `-5.90` adaptive floor solved one day of flatlining but recreated the same daily manual-edit problem when the cliff moved again
- a local band around the GA-recommended cliff lets Centaur follow the current day's tradeable band, while an absolute `-6.10` floor prevents it from chasing the clearly weak momentum scores around `-11`/`-12`

Implementation notes:
- the change remains paper-only
- the GA remains trade-aware and rewards proposal-viable signals from paper-allowed strategies
- this does not change `$10` notional, Alpaca Paper routing, max positions, one-order-per-tick, market-hours, projected-gain, stale-order, daily-protection, long-only, live execution, or the paper strategy allowlist

## 2026-05-15

### Seed the GA with hard-floor cliff candidates
Decision:
- seed the threshold GA with deterministic candidate genes down to the approved `-6.10` hard floor
- reduce the extra weak-score penalty for proposal-viable, paper-allowed signals below `-6.00`, while keeping stronger penalties for disallowed or non-tradeable survivors
- allow catch-up threshold moves to continue without waiting for the cooldown when the GA is moving toward the same tradeable local cliff, confidence/evidence gates are met, and no non-tradeable survivors are admitted

Why:
- today's allowed `mean_reversion.snapback` signals clustered around `-6.073`
- the controller's `-5.95` effective threshold and the old GA search were still leaving all such signals suppressed
- relying only on random evolution made the GA too slow to evaluate the approved hard-floor edge directly
- the prior cooldown made the local min/max band move correctly but left the effective threshold lagging behind the learned cliff

Implementation notes:
- this keeps the absolute adaptive hard floor at `-6.10`
- this keeps `$10` notional, Alpaca Paper routing, max positions, one-order-per-tick, market-hours, projected-gain, stale-order, daily-protection, long-only, live execution, and the paper strategy allowlist unchanged
- after the change, `main.py --threshold-advice` recommended `-6.10` with `medium` confidence over 172 usable ticks
- the effective threshold caught up from `-6.05` to `-6.10`; a controlled tick then used `allocation_suppress_threshold=-6.100`

## 2026-05-18

### Make GA evidence count usable signal ticks after quiet periods
Decision:
- expand the raw tick-row lookback used by the threshold adviser and trim after collecting usable signal ticks

Why:
- after a quiet weekend, the previous fixed row lookback could contain many no-signal ticks and leave the adviser with too few usable raw-signal diagnostics
- on 2026-05-18, the latest tick showed only 17 usable signal ticks before this change, even though older usable evidence existed

Implementation notes:
- this changes adviser evidence gathering only
- it does not change broker routing, notional size, allowed strategies, live mode, projected-gain gate, max positions, stale-order reaper, or daily protector

### Widen the adaptive hard floor after explicit approval
Decision:
- set `STRATEGY_THRESHOLD_ADAPTIVE_FLOOR=-6.50`
- keep the fixed `.env` suppress threshold at `-5.70`
- keep the adaptive ceiling at `-5.70`, local band width at `0.10`, max adjustment at `0.10`, minimum confidence at `medium`, minimum evidence at `120` ticks, and the `30` minute cooldown/catch-up guard

Why:
- on 2026-05-18, the current allowed `mean_reversion.snapback` signals clustered around `-6.112`
- the previous `-6.10` absolute floor was close enough to see the cliff but still strict enough to suppress every current allowed signal
- a floor at `-6.50` gives the adaptive controller room to follow the current tradeable cliff while still blocking the weaker current `liquidity_probe.steady_flow` band around `-6.86` and the very weak momentum band around `-11`/`-12`
- the GA could identify the right threshold but still label confidence as `low` because the recent test score remained damaged by the preceding flatline; the confidence gate now treats a clean local cliff as `medium` only when enough evidence exists, the test window has tradeable survivors, and the recommended threshold admits no non-tradeable survivors

Implementation notes:
- this change was made only after explicit human approval
- this remains paper-only
- this does not change `$10` notional, Alpaca Paper routing, max positions, one-order-per-tick, market-hours, projected-gain, stale-order, daily-protection, long-only, live execution, or the paper strategy allowlist
- the controller must continue to persist effective threshold state in PostgreSQL rather than rewriting `.env` on each move

### Add a recommendation-only holding-window fitness adviser
Decision:
- add `main.py --holding-window-advice`
- score `mean_reversion.snapback` fixed-window outcomes at `15m`, `1h`, and `1d`
- score simple dynamic policies, including `take_1h_profit_else_1d`
- surface the advice in status and dashboard snapshots
- keep it recommendation-only

Why:
- the `mean_reversion.snapback` profile uses a `1h` holding window, but the repo does not contain a durable decision proving that one hour is optimal
- recent paper exits showed that the `1h` time exit can realize avoidable losses on some trades
- existing shadow outcomes already measure `15m`, `1h`, and `1d`, so the system can test the assumption before any live paper exit behavior changes

Implementation notes:
- this does not change managed paper exits, stop loss, take profit, notional, broker routing, live execution, max slots, projected-gain, market-hours, daily protection, stale-order reaping, long-only policy, or strategy allowlists
- changing the actual `1h` managed-exit rule still requires a separate explicit override and reliability-stack update

## 2026-05-19

### Add a current-tick cliff governor to the adaptive threshold controller
Decision:
- annotate the current tick's raw strategy signals with fitness before threshold allocation
- let the adaptive controller inspect that current signal preview before applying the old GA-only decision path
- allow a paper-only cliff-governor step below the configured `-6.50` fallback floor when a clean allowed cliff is visible and the nearest blocked/disallowed cliff remains at least `0.10` lower
- persist the governor move in `strategy_threshold_adaptive_state` with the allowed cliff, nearest blocked cliff, and reason

Why:
- the operator's goal is for Centaur to diagnose and unstick itself, not require a daily human threshold edit
- on 2026-05-19, current `mean_reversion.snapback` signals were clustered at `-6.549756`, just below the `-6.50` fallback floor, while the nearest blocked `liquidity_probe.steady_flow` signals were still down at `-6.859063`
- a fixed floor recreated the manual-threshold problem even though the current tick clearly showed a safe gap between the allowed cliff and the blocked cliff

Implementation notes:
- this remains paper-only
- this does not change `$10` notional, Alpaca Paper routing, max positions, one-order-per-tick, market-hours, projected-gain, stale-order, daily-protection, long-only, live execution, or the paper strategy allowlist
- the governor does not admit blocked/disallowed signals; if the allowed cliff is too close to a blocked cliff, it holds
- the governor still moves by at most the configured adaptive max step per decision

## 2026-05-13

### Enable a guarded paper-only adaptive threshold controller
Decision:
- enable `STRATEGY_THRESHOLD_ADAPTIVE_ENABLED=true`
- keep the fixed `.env` suppress threshold at the human-approved `-5.70`
- allow the runtime effective threshold to adapt only inside `-5.70` to `-5.90`
- limit each automatic adjustment to `0.10`, require at least `medium` GA confidence, require at least `120` evidence ticks, and enforce a `30` minute cooldown
- persist the effective threshold and reason in PostgreSQL instead of rewriting `.env`

Why:
- the system has repeatedly flatlined because the current fitness distribution moved just below the fixed suppress threshold
- manual changes from `-5.00` to `-5.25`, `-5.50`, and `-5.70` showed that the threshold is acting like a moving cliff
- a small adaptive band lets Centaur follow that cliff when recent evidence supports it, without changing broker risk, order size, live readiness, strategy allowlists, or daily protection

Implementation notes:
- the first adaptive move on 2026-05-13 changed the effective paper threshold from `-5.70` to `-5.80` after the GA adviser returned a `medium` confidence loosen recommendation over 165 usable signal ticks
- the next controlled tick used `allocation_suppress_threshold=-5.800`
- that tick still produced zero proposals because the two raw signals were `liquidity_probe.steady_flow` at roughly `-6.859`, outside the adaptive rail and outside the paper strategy allowlist
- the GA threshold evaluation is now trade-aware: it rewards thresholds that produce proposal-viable signals from paper-allowed strategies and penalizes thresholds that merely admit non-tradeable, disallowed, or very weak survivors
- subsequent scheduler ticks at the learned effective threshold produced `mean_reversion.snapback` paper buys for `CEG` and `INTC`, confirming the adaptive cliff was opening the intended allowed-strategy path rather than chasing weaker disallowed signals
- this does not change `$10` notional, Alpaca Paper routing, max positions, one-order-per-tick, market-hours, projected-gain, stale-order, daily-protection, long-only, live execution, or the paper strategy allowlist

## 2026-05-11

### Add a recommendation-only genetic threshold adviser
Decision:
- add a deterministic GA adviser that searches for a strategy-allocation suppress-threshold policy from recent raw signal diagnostics
- expose the advice through `main.py --threshold-advice`, status output, and the DDEV dashboard snapshot
- keep the adviser recommendation-only; it must not write `.env`, change paper execution, change live readiness, or override the current human-approved threshold

Why:
- repeated manual threshold changes show that a fixed suppress threshold can starve the paper system in one regime and become too loose in another
- an adaptive policy needs evidence before it is trusted, and a GA can test candidate policies against stored tick/signal history without submitting trades
- the safest first step is to evolve and display recommendations, then compare them with actual outcomes before allowing any automatic paper-only adjustment

Implementation notes:
- the first GA uses recent tick snapshots, raw/suppressed signal previews, and strategy fitness-composite scores as the evidence surface
- the output includes train/test tick counts, confidence, evolved policy parameters, hard rails, and a recommendation reason
- hard rails are `-5.00` to `-6.00`
- this does not change notional size, broker routing, strategy allowlist, live execution, max slots, one-order-per-tick, projected-gain, stale-order, or daily-protection rules

### Lower the strategy-allocation suppress threshold after continued suppressed signals
Decision:
- set `STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD=-5.70`
- keep `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, one-order-per-tick, and daily-protection rules unchanged

Why:
- live ticks, Postgres persistence, market gating, broker connectivity, and paper capacity were healthy
- the current trade blocker was still `all_signals_suppressed`, not a scheduler or broker failure
- recent `mean_reversion.snapback` candidates were repeatedly landing around `-5.669`, just below the prior explicitly approved `-5.50` threshold
- this calibration is intended to let the near-miss `mean_reversion.snapback` signals reach proposal/risk checks without changing order size, broker, strategy allowlist, or daily loss rules

Implementation notes:
- this was done by explicit human override on 2026-05-11
- clearly weaker scores such as roughly `-6.859`, `-11.232`, and `-12.566` should remain suppressed by this threshold
- the next paper entries should be watched closely because this is a deliberate loosening of the fitness allocator

### Preserve managed-exit plans across broker order refreshes
Decision:
- keep Centaur's entry-plan metadata when Alpaca paper-order polling refreshes an existing order row
- let managed exits recover missing stop, target, break-even, trailing-stop, and holding-window fields from the matching shadow proposal when an older entry order no longer has the original Centaur plan payload

Why:
- a live NFLX paper position had exceeded its planned `1h` holding window but was still being skipped as `exit_not_due`
- the entry order had been refreshed with the broker's order payload, which no longer contained Centaur's `planned_holding_window_minutes`
- stop and target values were already recoverable from persisted columns, but the holding-window rule was not, so the age-based exit path could fail silently
- exit decisions must stay deterministic and auditable after broker syncs mutate order payloads

Implementation notes:
- this does not change notional size, broker routing, strategy allowlist, suppression threshold, projected-gain gate, max positions, max orders per tick, or daily protection
- a controlled tick on 2026-05-11 submitted the NFLX managed exit with reason `holding_window_elapsed`
- the subsequent status check showed the latest NFLX sell as filled

## 2026-05-01

### Prefer the project virtualenv for launchd ticks on the migrated Mac
Decision:
- make the `launchd` wrapper prefer `/Volumes/Bob/www/ghostfrog-centaur/.venv-mac/bin/python`
- keep Homebrew/system Python paths only as fallback interpreters

Why:
- the migrated Mac only exposed Apple Python 3.9 as `python3`, which is too old for the current code
- the live operations store is PostgreSQL, so the unattended interpreter must have `psycopg2` available
- using the project-local environment keeps the scheduler tied to the same dependency surface as manual operation

Status:
- verified on 2026-05-01 with tick id `20260501-133905`
- the verified tick used PostgreSQL and exited with status `0`
