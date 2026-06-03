# Project Centaur Record

This file is the durable, chat-independent record of what Project Centaur is, what it is doing now, and why it exists.

If future conversations lose context, this file should be treated as the first place to recover project intent.

Last updated: 2026-05-31

## Purpose
Project Centaur is a trading research and automation system aimed at growing capital safely, legally, and repeatably through trading.

The project is intentionally being built in stages:
- first, collect data reliably
- then, generate and score shadow trades
- then, measure strategy fitness honestly
- then, allow tightly constrained micro paper execution
- real money comes last, not first

The goal is not "make money by any means possible." The goal is to discover whether we can build a real, repeatable edge under strict risk controls.

The current strategic growth target is documented in `docs/FIFTY_DOLLAR_DAY_PLAN.md`: reach a sustained, evidence-backed `$50/day` net profit pace. That target guides prioritization and reporting, but it does not authorize any risk widening, notional change, broker change, strategy-gate relaxation, slot expansion, or live-behavior change without explicit approval and reliability-stack updates.

## Prime Directives
- Grow capital safely, legally, and repeatably through trading.
- Maximize risk-adjusted returns, not raw profit at any cost.
- Preserve capital first.
- Keep all important decisions measurable and auditable.
- Treat strategy fitness as invalid if it depends on breaking risk rules.
- Connect every new learning/evidence capture feature to a runnable report or evidence surface so findings can be reviewed before behavior changes.
- Keep code, documentation, and persistence production-quality: safety-critical paths need docstrings/comments, and database changes need indexes/query discipline to avoid control-loop drag.
- Build toward a sustained, evidence-backed `$50/day` net profit pace by improving throughput, net expectancy, exit/data reliability, and staged slot/capital scaling without weakening capital-preservation rules.

## Why This Exists
The project exists for three reasons:
- to build a system that can discover and test trading ideas faster than manual work alone
- to create an honest feedback loop that separates promising ideas from bad ones
- to evolve rule-based strategies over time instead of relying on gut feel

## Current Architecture
- Architecture direction: multi-platform Centaur core with vendor-specific market-data, execution, broker/account, and symbol-mapping adapters; `centaur-codex-architecture-instructions.md` is the read-first guide for this refactor direction; Alpaca latest-bar and historical backfill fetches now run through `app.framework.adapters.market_data`
- Broker and market data today: Alpaca Paper/Live, Trading 212 Paper for its separate equity lane, disabled Trading 212 Live readiness wiring, and Alpaca market data for the shared US-equity/crypto scanner
- Execution architecture today: broker-adapter layer with active paper lanes for Alpaca Paper and approved Trading 212 equities, Alpaca Live approved only inside the recorded same-as-paper follower envelope, and IG scaffolded
- Order routing today: approved entries, managed exits, and stale-order cancellations pass through `ExecutionRouter`; live entry/exit/cancel actions receive immediate `LiveRiskGuard` re-checks before broker mutation, including live activation, kill switch, account/sync readiness, broker identity, same-paper-order validation, entry capacity, latest-bar availability, and instrument/venue permission checks where derivable. Do not add separate live-only trade-count or bar-age policy unless the operator explicitly asks for it; live should remain exactly same-as-paper, but live. `live_dry` records intended actions in tick state without calling the live broker adapter
- Reasoning layer: Gemini API adapter retained in the codebase, but the live runtime is currently operating in function-only mode with Gemini analysis disabled to control API spend
- Operations database: PostgreSQL; paper/live operation must not silently fall back to SQLite; the active runtime now routes execution/account rows into lane schemas (`paper`/`live`) and shared reviewed evidence into `core`, while still honoring explicit `POSTGRES_SCHEMA` overrides
- Storage layout: `core`, `paper`, and `live` lanes are explicit. `core` is the shared reviewed evidence and strategy-fitness lane; `paper` and `live` are execution/evidence lanes with PostgreSQL schemas and lazy file-output directories for migration and audit. The root `storage/` placeholder tree is not kept when empty.
- Config loading: `.env` is the single runtime config file, grouped into core, paper, and live sections so paper/live levers are visible without YAML indirection. Mirrored live execution levers match paper by default; named live differences must be listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES` or config load fails closed while live is armed.
- FX conversion for GBP reporting: ECB daily reference feed
- Runtime model: LangGraph-first orchestration with Pydantic-backed state/node contracts is now the target; the current ordered `ControlPipelineRunner` pipeline remains behaviour-preserving migration scaffolding, with `ModeContext` providing explicit `shadow`, `paper`, `live_dry`, and `live` mode boundaries; `live_dry` is live-environment but non-mutating
- Instrument model: initial canonical instrument registry exists so venue symbols such as Alpaca `BTC/USD` and Binance `BTCUSDT` can map to the same Centaur instrument while keeping venue/execution permissions distinct; the registry now exposes `InstrumentRef` for resolved venue identity; Alpaca market-data adapter payloads, broker order rows, and shadow evidence rows persist/carry canonical instrument id, venue, and venue symbol, with schema-bootstrap backfills where existing rows are derivable; new latest-bar, historical-backfill, and strategy-candidate-signal rows also carry canonical instrument metadata, and discovery candidates / strategy signals preserve a serialized `instrument_ref` for downstream evidence; large historical market-data/signal rows are not swept during normal control-loop bootstrap
- Adapter model: market-data fetches pass through `app.framework.adapters.market_data`, and order-request building plus order mutation pass through `app.framework.adapters.execution`; execution-adapter lookup currently resolves `alpaca_paper`, `alpaca_live`, `trading212_paper`, and disabled `trading212_live`, with unsupported providers failing closed. `.venv-mac/bin/python main.py --adapter-inventory` is the read-only inventory for active, bridged, disabled, scaffold-only, and not-implemented providers
- Folder status: the implementation now lives under `app/` across runtime, engine, adapters, storage, reporting, and strategies; the old `centaur/` package has been removed.

## Current Reality
As of 2026-05-31, Centaur is primarily a training and evaluation system with an active micro paper-execution path, an explicitly approved same-as-paper Alpaca Live follower lane, and a headless unattended `launchd` cadence currently targeted at `30` second starts with skip-if-busy wrapper protection. Runtime status/provenance now reports the existing armed live follower lane as `live/live` unless explicit `CENTAUR_MODE`/`CENTAUR_ENVIRONMENT` settings say otherwise, and runtime mode now acts as a live safety boundary through `ModeContext`: explicit paper mode skips Alpaca Live sync/order-mutation paths, while `live_dry` defaults to the live environment and can carry intended approvals without submitting broker orders. Execution-router intents are persisted in `execution_router_intents` and summarized by `.venv-mac/bin/python main.py --evidence-report`, so live-dry action review survives beyond the latest tick snapshot. The first canonical instrument registry is in place for adapter-first work, so future vendors can map venue symbols to Centaur instruments without making vendor symbols the core truth. Broker order rows, shadow proposals/outcomes, and strategy fitness snapshots still carry explicit provenance metadata (`environment`, `mode`, `source_environment`, provider/broker fields, and execution provider where relevant), and the active PostgreSQL layout now routes shared reviewed evidence into `core` while keeping execution/account mutations in the runtime lane schema (`paper` or `live`). `.venv-mac/bin/python main.py --storage-separation-report` is the bounded audit surface for this boundary; it now reports the shared-Postgres, lane-schema separation contract directly instead of treating it as a future migration. Alpaca Live is intended to remain exactly same-as-paper, but live; separate live-only trade-count or bar-age policy should not be added unless the operator explicitly asks. Equity paper execution now includes a no-weekend-carry guard: Friday equity entries are blocked in the final `60` minutes of the regular session and managed equity positions are flattened in the final `15` minutes so calendar-time `1d` backstops do not create Monday forced exits after a weekend. Managed max-hold exits for `profit_after_1h_else_1d` and `profit_capture_else_1d` now defer red positions with `max_hold_red_deferred` instead of selling solely because the timer elapsed; stops and profit exits remain active. A trailing drawdown/high-water observer now records counterfactual paper/live giveback data in tick snapshots and the dashboard, but it is evidence-only and does not affect entries, exits, orders, live following, or protection latches. Operations storage fails closed when PostgreSQL is configured, or when paper/live execution is enabled, so monitoring and control ticks do not silently continue against SQLite. The CLI status path is kept lightweight; dashboard-only visual datasets and the full threshold GA are reserved for dashboard snapshots or `.venv-mac/bin/python main.py --threshold-advice`. Broad report requests should start with `.venv-mac/bin/python main.py --evidence-report`, the repo's registry of shadow/counterfactual evidence streams. New evidence-capture features are now required to add or update a report surface, document interpretation guidance, and keep persistence/index/query design efficient enough for the control loop.

Alpaca Live API keys have now been added locally and funded read-only checks passed on 2026-05-29. The live account is `ACTIVE`, not blocked, has no positions, recent orders, or open orders, and shows `132.05` cash/equity/buying power. The `$132.05` balance does not widen the intended `$10 x 10` live envelope. The first-live plan is recorded as a same-as-paper follower lane by operator request: current paper strategies only, equities plus crypto, `$10` entries, `10` base slots, one order per tick, same-as-paper daily protector, shared paper/shadow strategy fitness, read-only live execution intelligence, and explicit rollback triggers. On 2026-05-29 at about 10:48 BST, after a final clean read-only check, the operator explicitly approved turning Alpaca Live on within that envelope. The first fully live-enabled observed tick, `20260529-105313`, completed `OK`; live CFO held because there was no submitted paper trade to follow, live execution submitted no orders, and the post-activation live account check still showed no live positions or orders.

It can:
- run a control tick manually and via a verified `launchd` wrapper on this Mac
- show a one-shot status summary via `.venv-mac/bin/python main.py --status`
- run a repeatable paper-exit post-mortem via `.venv-mac/bin/python main.py --paper-exit-review --strategy-id mean_reversion.snapback`
- fetch Alpaca paper account, clock, positions, recent orders, and latest bars
- collect stock and crypto market data
- continue collecting crypto and generating crypto shadow proposals outside US equity hours
- convert values into GBP for reporting
- discover candidates from a broader symbol universe
- run rule-based strategies against those candidates
- keep the Gemini analysis adapter available without requiring it for live operation
- create shadow trades instead of real trades
- evaluate shadow outcomes later at checkpoints like 15m, 1h, and 1d
- compute strategy fitness summaries
- run historical replay across stored bars to accelerate learning
- submit a very small Alpaca paper order when all paper-execution gates pass
- persist broker-tagged paper-order history so future multi-broker execution can stay separated in the operations store
- show an Alpaca Live readiness lane for a possible side-by-side paper/live go-live discussion
- show read-only live execution intelligence that compares future live follower entries against same-proposal paper entries for fill drift, status mismatch, unmatched live orders, and blockers

It does not yet:
- do meaningful portfolio sizing
- do full broker reconciliation beyond recent-order polling and persisted broker payloads
- expose a fully broker-separated account history view yet
- have a fully implemented genetic algorithm loop
- activate Alpaca Live entries or live order actions without the explicit go-live gates
- have proven live profitability

## How One Live Tick Works
Each `launchd` tick currently does this:
1. Check Alpaca paper account, clock, and positions.
2. Fetch recent Alpaca paper orders for broker-state awareness.
3. Fetch latest equity and crypto bars.
4. Update GBP reference conversion.
5. Evaluate older shadow checkpoints that are now due.
6. Recompute strategy fitness from accumulated outcomes.
7. Discover current candidates from the latest market data.

Current default crypto universe:
- crypto: `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `DOGE/USD`, `LTC/USD`, `BCH/USD`, `LINK/USD`, `AVAX/USD`, `UNI/USD`, `AAVE/USD`
8. Run deterministic strategy profiles on those candidates.
9. Optionally run Gemini analysis as commentary support when it is enabled; otherwise skip it and stay function-only.
10. Create new shadow proposals from strategy signals.
11. Run the CFO gate.
12. Before new entries, enforce the persisted daily equity-drawdown protector and reap stale untouched equity entry limits.
13. If and only if all paper-execution rules pass, submit tiny broker-labelled paper entry orders in the approved lanes; otherwise hold.
14. If a paper position is open, monitor the latest bar data and submit a managed exit order when the stop, target, or holding window is reached.

In practice, the shared Alpaca equity scanner follows US market hours while crypto can continue flowing during the overnight `crypto_only_window`. Trading 212 Paper has its own UK weekday session gate for lane approvals/status, and its adapter rejects entries unless the proposal is explicitly sourced from Trading 212-compatible market evidence.

Current micro paper mode rules:
- paper only, no live money
- equities and crypto
- equities require market open; crypto can trade during the overnight crypto window
- up to ten open positions or in-flight order slots at a time
- one order max per tick
- default size is `$10`
- allowed strategies are currently `mean_reversion.snapback`, `crypto_momentum.trend`, and `momentum.volatility_breakout`
- projected gain must be at least `1.5%` for equities and `2.0%` for crypto
- `crypto_momentum.trend` uses a `1.0%` stop by explicit operator override on 2026-06-01, reducing future `$10` stop losses from roughly `$0.30` to roughly `$0.10` while keeping crypto enabled
- paper entries and exits use marketable limit orders rather than raw market orders
- already allowed strategies may use the score-to-trade rule when raw `signal_score` is at or above the active configured dial (`PAPER_MIN_SIGNAL_SCORE_TO_TRADE` for paper, `LIVE_MIN_SIGNAL_SCORE_TO_TRADE` for live/live-dry; currently same-as-paper at `90.0`); those candidates survive fitness suppression so CFO/risk can evaluate them. This does not change notional, stops, projected-gain floors, broker routing, max orders, or same-as-paper live following
- paper managed exits may capture profit at `1.25%` for both equity and crypto positions while preserving the higher entry projected-gain gates
- shadow outcomes record a profit-target ladder of `1.25%`, `2%`, `3%`, `4%`, and `6%` so the project can learn whether waiting for higher exits would have worked without changing the actual paper capture rule
- `crypto_momentum.trend` paper exits use `profit_capture_else_1d`: stop, `1.25%` capture, and target remain active, with a finite `1d` max-hold backstop instead of the old `60m` forced time exit
- non-crypto paper orders use a `5` bps marketable-limit buffer, while paper crypto orders use a separate `25` bps buffer by explicit human override on 2026-05-28
- crypto managed exits normalize Alpaca symbols with and without slashes so positions such as `AAVEUSD` match entry plans and bars stored as `AAVE/USD`
- `mean_reversion.snapback` paper exits now use an explicit override: profitable positions may exit after `1` hour, while non-profitable positions continue under the same stop/target protection until a `1d` max-hold backstop
- equities now use the paper-only adaptive suppress-threshold lane anchored at `-5.60`, while crypto uses its own fixed suppress threshold `-6.90`
- the adaptive paper-only cliff governor now uses a dedicated `0.10` safety gap by explicit human override on 2026-05-27 so weak `mean_reversion.snapback` cliffs near `-6.77` are blocked again
- new paper entries are disabled for the session once the persisted equity drawdown reaches `$2.00`
- untouched equity entry limits older than `5` minutes are canceled by the in-pipeline stale-order reaper
- orders are logged into `paper_trade_orders`
- current broker routing is explicit:
  - US-equity primary lane -> `alpaca_paper`
  - Trading 212 paper equity lane -> `trading212_paper` when enabled, market-open, and backed by Trading 212-sourced proposal/data
  - crypto -> `alpaca_paper`
- Trading 212 paper symbols are a separate configured UK universe; venue tickers must come from Trading 212 proposal/instrument metadata or explicit overrides, not from guessed US ticker suffixes
- Trading 212 instrument metadata maps the 30-symbol UK universe to real venue tickers such as `VODl_EQ`, `SHELl_EQ`, and the explicit `LSEG:LSEl_EQ` alias. For the reset £100 demo account, the default seed basket is 20 symbols and Trading 212 managed paper entries are sized at `£5` native notional. `TRADING212_PAPER_MARKET_DATA_PROVIDER` defaults to `disabled` because the official public Trading 212 API does not currently expose a latest-price/latest-bar endpoint for unheld watchlist symbols. The supported API workaround is `positions_api`, which uses `/equity/positions` `currentPrice` for symbols already seeded/held in the Trading 212 paper account. `TRADING212_PAPER_PRICE_SEED_SYMBOLS` marks tiny demo holdings as price-feed seeds only; `.venv-mac/bin/python main.py --trading212-seed-prices --confirm-trading212-paper-seed` can place capped quantity-based Trading 212 paper seed orders, and those seeds do not consume strategy slots, block same-symbol entries, or trigger managed exits until Centaur has a filled managed buy for the same Trading 212 symbol
- Trading 212 latest-bar plumbing preserves Trading 212 venue ticker casing and converts GBX quote prices to GBP for fixed `£10` quantity sizing when a real API-derived price is available
- Trading 212 Live now has explicit `TRADING212_LIVE_*` configuration and adapter/readiness identity using the documented live API base URL, but `TRADING212_LIVE_EXECUTION_ENABLED=false` and live order validate/build/submit/cancel fail closed until separately approved
- Alpaca Live is approved for same-as-paper follower activation by explicit 2026-05-29 operator override and must not submit real-money entries outside those go-live gates
- Alpaca Live mirrors paper settings for equities plus crypto, the same three allowed strategies, `$10` notional, `10` base slots, one order per tick, `$2.00` persisted daily protector, `1.5%` equity projected-gain, `2.0%` crypto projected-gain, `5` bps equity buffer, and `25` bps crypto buffer; activation is authorized only inside this recorded envelope
- The recorded first-live policy is same-as-paper by operator request, but extra account funds above `$100` are launch buffer only and do not create additional first-live slots
- Alpaca Live protective mechanics now mirror paper readiness: guarded cancellation, stale equity-entry reaping, and stale/non-marketable managed sell-exit refresh are implemented for a future activated lane
- Live execution intelligence is separate from strategy intelligence: strategy scoring stays shared through shadow fitness, while live diagnostics monitor future live-vs-paper execution quality
- Safety-critical trading paths must now carry docstrings or compact nearby comments explaining the protected gate, capital-preservation intent, and audit trail
- IG is scaffold-only for now and is not active in live execution

First profitability check:
- when Centaur is not making profit, first check whether exits are too ambitious before changing entry logic
- for `$10` micro trades, a large percentage target can be unrealistic even when the dollar value looks small
- review whether trades were briefly up by a meaningful amount before later going flat or red
- use `--paper-exit-review`, `--holding-window-advice`, recent filled exit reasons, and shadow windows before loosening thresholds or widening risk
- the 2026-05-28 operating lesson is that the system may fail to compound because it waits for oversized exits, not because it needs weaker entries

Potential micro-edge breakthrough:
- Centaur's current paper lane should be judged as a micro system: `$10` entries, small profit capture, repeated attempts, and strict loss control
- big percentage targets belong to bigger trades, longer holds, or shadow learning; they should not be assumed suitable for `$10` paper scalps
- on 2026-05-28, after adding the paper-only high-score near-miss override and setting the real paper capture to `1.25%`, Centaur immediately began placing more intended micro trades and showed multiple small green positions
- the working hypothesis is that a hard fitness veto plus oversized targets had been suppressing or wasting the micro edge
- this is not treated as proof yet; validate it through win rate, average win/loss, stop frequency, profit-capture frequency, and shadow target-ladder results before increasing risk

Current discovery universe:
- equities: full Nasdaq-100 constituent list
- crypto: `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `DOGE/USD`, `LTC/USD`, `BCH/USD`, `LINK/USD`, `AVAX/USD`, `UNI/USD`, `AAVE/USD`

Current shadow-learning strategy set includes:
- `momentum.balanced`
- `momentum.strong`
- `momentum.volatility_breakout`
- `mean_reversion.snapback`
- `crypto_momentum.trend`
- `liquidity_probe.steady_flow`

The `momentum.volatility_breakout` profile is now allowlisted for micro paper execution by explicit human override. It uses a 20-bar breakout above the prior high, a 2.0x volume surge check, an ATR floor above 1 percent of price, and a conservative break-even trailing rule that only activates on the bar after the trigger is reached.

For unattended runs on this Mac, scheduler logs now live under the home directory rather than the external project volume:
- wrapper log: `~/centaur_control_wrapper.log`
- runtime tick log: `~/.centaur/runtime/control_tick.log`

After the 2026-05-01 Mac/SSD migration, the LaunchAgent wrapper was reinstalled and verified against `/Volumes/Bob/www/ghostfrog-centaur`. The wrapper now prefers the project-local `.venv-mac` Python 3.12 environment, which has `psycopg2-binary` installed, before falling back to any system Python. The first verified post-migration unattended tick was `20260501-133905`, and it exited successfully with `Operations store: postgres`.

Operational visibility now also includes:
- `.venv-mac/bin/python main.py --status` for a readable monitor view
- `https://ghostfrog-centaur.ddev.site` as the primary routed local dashboard through DDEV/OrbStack
- `.venv-mac/bin/python main.py --dashboard` for a direct Python-served fallback web view on `127.0.0.1:8788`
- `.venv-mac/bin/python main.py --dashboard-desktop` for the older local desktop monitor window on the Mac
- `scripts/centaur-agent.sh status` for launch agent details, tail logs, and the same summary
- `scripts/centaur-agent.sh dashboard` as a convenience launcher for the DDEV-routed dashboard
- explicit paper-execution alerts in status and dashboard output so broker failures are visible with reasons
- hourly one-way Slack liveness/status messages via `SLACK_HOURLY_STATUS_*`, deduped in `notification_events`; if those messages stop arriving, treat the scheduler/control loop as stale until proven healthy
- scheduled test monitoring via `.venv-mac/bin/python scripts/run_test_monitor.py`, which runs the unit suite and fails if the latest persisted control tick is missing, non-ok, or stale beyond `TEST_MONITOR_SCHEDULER_MAX_AGE_MINUTES`
- a read-only paper-exit post-mortem command that compares actual paper exits to stored `15m`, `1h`, and `1d` shadow outcomes for the same proposal ids
- strategy-coverage graphs so newly installed strategies can be seen even before they have fitness rows
- a ranked strategy leaderboard that orders all strategies by current best fitness and explains, in plain English, why the current leader is on top
- separate recent-window strategy counts from all-time training volume so the dashboard does not understate replay sample size
- open-position diagnostics showing unrealized PnL, stored stop/target, and current exit-monitor state
- an account panel showing Alpaca balance, cash, buying power, day change, and current open-position P/L
- a dedicated `Account` dashboard tab with balances, positions, and P/L plus a top-level day-P/L badge
- a second top-level day-P/L badge in GBP using the same ECB reference rate used elsewhere in the system
- a dedicated capital-envelope view showing max, committed, free, and slot usage under the current paper bankroll rule
- a return-comparison view that contrasts Centaur’s current paper pace with simple 5%, 10%, and 20% annual yardsticks on the same bankroll cap
- that return-comparison view now uses the last persisted account tick before the first paper order as its starting baseline, so later order-sync updates do not make the comparison silently reset itself
- trade diagnostics showing the primary blocker when Centaur does not place a paper order
- Centaur activity diagnostics showing scan volume, raw strategy-signal previews, fitness-suppressed signal previews, surviving signals, proposal counts, and CFO blocker reasons so quiet Alpaca periods are explainable
- a persisted per-tick blocker summary that records the primary stage blocker plus counted rejection and exit-skip reasons, so later trade drought diagnosis does not rely on manual database forensics
- a live-readiness section showing the disabled `alpaca_live` lane, its `$10 x 10 = $100` planned envelope, and the blockers preventing real-money execution
- a dedicated API cost view showing internal estimated spend, request volume, and whether provider pricing is configured well enough for those estimates to be trustworthy
- a one-shot `python3 main.py --backfill-api-costs` path that reprices older stored API events and refreshes cost rollups where request units were already recorded
- the standalone `Graphs` tab is temporarily disabled while we test whether its extra redraw work is what makes the Tk dashboard feel unresponsive
- the Tk dashboard is now temporarily running in a flat, single-view layout with no tabs while we test whether the tabbed UI itself contributes to sluggishness
- the runtime-log and wrapper-log tail panes are also temporarily disabled in that single-view layout so the monitor does less live text churn
- the recent-activity panel is also temporarily disabled there, leaving a very minimal core monitor view
- the dashboard now also uses a lighter snapshot path and reuses that same snapshot for its rendered summary, instead of taking a second full status snapshot every refresh
- the primary operator dashboard surface is now the DDEV/OrbStack-routed web app rather than the Tk window
- the DDEV dashboard now reads live status data through `/api/snapshot.php`, which proxies the host dashboard API instead of a repo-local snapshot file bridge; the Python dashboard API remains read-only and is intended to run as a separate unattended operator service

For this Mac-hosted setup, operations data should now be treated as `Postgres only`.
SQLite remains in the repo only as legacy bootstrap/fallback scaffolding and should not be relied on for live monitoring or scheduler-backed operation.

One current honesty gap is billing configuration:
- Centaur records API requests and can estimate cost
- but if provider pricing values are left at zero in `.env`, the internal dashboard will understate real spend
- provider billing consoles can therefore show real cost before Centaur’s internal estimate catches up

That gap has now been reduced by pinning the current Gemini configuration to `gemini-2.5-flash` pricing in `.env`, so new Gemini requests should start producing non-zero internal estimated cost instead of remaining at zero.

Centaur can now also backfill historical API cost estimates where possible:
- stored `api_request_events` are repriced from current provider pricing
- `api_daily_usage` is rebuilt from those repriced event rows
- `control_tick_runs` budget fields are refreshed so the status and dashboard surfaces stay aligned
- events without enough recorded units still remain best-effort rather than magically exact

This is intentional because the background scheduler could read the repo on `/Volumes/Bob/...` but could not reliably write runtime logs back into the external-drive project directory.

## Multi-Broker Refactor Status
Centaur has now started the transition away from a single hard-wired broker path.

What is true now:
- the existing Alpaca execution path has been moved behind a broker-adapter interface
- the live paper path still routes to Alpaca for both equities and crypto
- persisted paper-order rows now include `broker_id`
- an `Alpaca Live` adapter identity exists as a dormant readiness sidecar
- an `IG` spread-betting adapter scaffold exists in the codebase

What is not true yet:
- Alpaca Live is not active for execution
- Alpaca Live guarded order submission/cancellation code exists for readiness, but current configuration blocks live entries and leaves the activation acknowledgement empty
- IG is not active for execution
- there is not yet a dedicated broker-separated account-history view in the dashboard
- Centaur does not yet submit or cancel IG orders

The current intent of the Alpaca Live readiness lane is defensive:
- make side-by-side paper/live architecture explicit before any May 2026 go-live decision
- keep the default live envelope visible as `$10` x `10` slots = `$100`
- require a separate go-live override, activation acknowledgement, strategy choice, kill-switch rule, daily-loss rule, and rollback conditions before real-money entries can be activated

The current intent of the IG scaffold is defensive:
- reject any trade where the minimum bet-per-point would exceed the fixed `$10` notional limit
- reject any trade that would imply more than `1x` leverage
- keep the adapter in shadow/scaffold mode until the rest of the broker separation is complete

## Current Learning Model
Centaur currently learns in two ways:

### Live Learning
The weekday `launchd` tick keeps collecting fresh data and scoring shadow outcomes as time passes.

### Historical Replay
The replay runner reuses stored historical bars to generate many more shadow proposals and outcomes quickly, without extra API cost.

Shadow and replay scoring now apply configurable execution friction for spread and slippage, plus a fixed per-trade micro-friction floor, so the fitness layer no longer assumes perfect fills or ignore penny-scale drag on `$10` trades.

This matters because live scheduled ticks alone are too slow to build enough evidence.

On 2026-04-21, after a seven-day live flatline with 9,147 ticks, zero shadow proposals, and zero buy entries, the strategy-allocation suppress threshold was lowered from `-5.0` to `-5.25` by explicit human override.

On 2026-05-07, after continued trade drought concerns and an explicit human override, the threshold was lowered again from `-5.25` to `-5.50`. This remains a narrow calibration of the fitness allocator, not a notional, broker, allowlist, market-hours, projected-gain, max-slot, or daily-protection relaxation.

On 2026-05-11, after current `mean_reversion.snapback` signals were still being suppressed around `-5.669`, the threshold was lowered again from `-5.50` to `-5.70` by explicit human override. This is a deliberate fitness-allocator calibration only; `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, one-order-per-tick, and daily-protection rules remain unchanged.

On 2026-05-11, Centaur gained a recommendation-only genetic threshold adviser. It uses recent tick signal diagnostics and fitness-composite scores to evolve a suppress-threshold policy and report whether it would hold, loosen, or tighten the current threshold. It is advisory only and does not write `.env` or alter paper/live execution policy.

On 2026-05-13, after explicit human approval, that threshold learning was promoted to a guarded paper-only adaptive controller. The fixed `.env` threshold remains `-5.70`, while the persisted effective threshold may adapt by at most `0.10` per move, with at least `medium` GA confidence, at least `120` usable evidence ticks, and a `30` minute cooldown. The first adaptive state moved the effective threshold to `-5.80`; a controlled tick then used `allocation_suppress_threshold=-5.800`. On 2026-05-14, the controller changed from a fixed `-5.90` adaptive floor to a local `+/-0.10` cliff band with an absolute hard floor at `-6.10`, after the useful `mean_reversion.snapback` cliff drifted to roughly `-5.95`. The threshold GA is now trade-aware: it rewards thresholds that produce proposal-viable signals from paper-allowed strategies and penalizes thresholds that merely admit non-tradeable, disallowed, or very weak survivors. This does not alter `$10` notional, Alpaca Paper routing, strategy allowlists, live execution, max slots, market-hours, projected-gain, stale-order, daily-protection, or long-only rules.

On 2026-05-15, the threshold GA was hardened again after allowed `mean_reversion.snapback` signals clustered near `-6.073` and remained suppressed. The GA now seeds deterministic candidate genes down to the approved `-6.10` hard floor and applies a lighter extra weak-score penalty to proposal-viable, paper-allowed signals below `-6.00`, while keeping stronger penalties for disallowed and non-tradeable survivors. This made `main.py --threshold-advice` recommend `-6.10` with `medium` confidence. The adaptive controller can now take continued catch-up steps toward the same tradeable cliff without waiting for the cooldown, while still respecting the `0.10` max step and the `-6.10` hard floor. This does not change the paper risk envelope.

On 2026-05-18, the threshold adviser lookback was widened so quiet weekend/no-signal ticks do not crowd out usable raw-signal diagnostics. This makes the GA evidence gate count usable signal ticks more reliably after quiet periods, without changing broker routing, notional size, allowed strategies, live mode, projected-gain gate, max positions, stale-order reaper, or daily protector.

Later on 2026-05-18, after explicit human approval, the adaptive controller's absolute paper-only hard floor was widened from `-6.10` to `-6.50`. The reason was narrow: today's allowed `mean_reversion.snapback` signals clustered just beyond `-6.10`, while the weaker liquidity-probe band remained around `-6.86` and the weak momentum band remained around `-11`/`-12`. The GA confidence gate now treats a clean local cliff as `medium` only when enough evidence exists, the recent test window has tradeable survivors, and the recommended threshold admits no non-tradeable survivors. The controller still uses `0.10` maximum moves, the local `+/-0.10` cliff band, `medium` confidence, and evidence gates, and it still must not alter `$10` notional, Alpaca Paper routing, live execution, strategy allowlists, max slots, market-hours, projected-gain, stale-order, daily-protection, or long-only rules.

Also on 2026-05-18, Centaur gained a recommendation-only holding-window fitness adviser. It compares `mean_reversion.snapback` fixed-window outcomes at `15m`, `1h`, and `1d`, plus simple dynamic policies such as selling profitable `1h` trades and extending losing `1h` trades to the `1d` checkpoint. The adviser is visible through `main.py --holding-window-advice`, status output, and dashboard snapshots. It does not change managed exits automatically; changing the current `1h` paper exit rule still requires a separate explicit override and decision update.

On 2026-05-19, Centaur gained a current-tick cliff governor for the adaptive threshold controller. Before allocation, the pipeline now annotates the current raw strategy signals with their fitness scores, then the governor compares the nearest paper-allowed, proposal-viable cliff against the nearest blocked or disallowed cliff. It may step below the configured `-6.50` fallback floor only when a clean safety gap remains, only by the configured max step, and only far enough to admit the allowed cliff. This is intended to remove the daily manual-threshold problem without admitting weak liquidity-probe or momentum bands. It still does not change `$10` notional, Alpaca Paper routing, live execution, strategy allowlists, max slots, market-hours, projected-gain, stale-order, daily-protection, or long-only rules.

On 2026-05-27, after a new flatline with healthy scans but no surviving paper-allowed signals, an explicit human override reduced that cliff-governor safety gap from `0.10` to `0.05`. The narrow goal was to admit the current `mean_reversion.snapback` cliff around `-6.768817` without reopening the blocked `-6.859063` liquidity-probe band. The fallback floor, max step, `$10` notional, broker routing, strategy allowlist, projected-gain gate, and daily protector were all left unchanged.

On 2026-05-20, the Alpaca Live lane moved from pure scaffold to a dormant side-by-side follower path. It is still off by default and API keys alone are deliberately insufficient. The live lane can only consider trades that the paper CFO gate approved on the same tick, then it applies separate live account state, live daily-loss, live slot, live allowlist, kill-switch, activation acknowledgement, and broker-validation gates before any entry order submission. A dormant live managed-exit step also uses the same persisted entry plan fields as paper for future stop/target/holding-window exits. This prepares a future go-live review without changing the current paper-only operating posture.

Also on 2026-05-20, an explicit human override added earned-slot compounding to paper and the future live lane. Each full `$10` of tracked P/L above the broker lane's pre-first-order baseline adds one effective open-position slot, while per-order notional stays fixed at `$10`. This makes the current paper result of roughly `$13` translate into `11` effective paper slots instead of the base `10`; if tracked P/L falls below a full `$10` increment, that earned slot drops away.

On 2026-05-11, managed paper exits were hardened so Alpaca order polling cannot strip away Centaur's original exit plan. Existing order rows now preserve Centaur plan metadata where possible, and the exit monitor can recover missing stop, target, and holding-window rules from the matching shadow proposal. This fixed an NFLX paper position that had exceeded its planned `1h` holding window but was being skipped as `exit_not_due`.

## Current Truth About Trading
The project is promising infrastructure, not proven edge.

At the moment, we should assume:
- the system might eventually become useful
- the current strategy set is still experimental
- small samples can be misleading
- profitability is unproven until it survives much more testing

## Capital Reality
Small capital means small absolute returns, even with good percentage performance.

That means:
- a tiny stake is good for proof and discipline
- it is not enough by itself to create meaningful income
- if the system ever becomes good, scaling will still require more capital

## Source Of Truth Files
These files should be kept up to date when the project changes materially:
- `AGENTS.md`: read-first repo identity and task-handling rules
- `CONSTRAINTS.md`: hard guardrails and override rules
- `DECISION_LOG.md`: read-first decision entrypoint
- `SKILL.md`: reusable Centaur work playbooks
- `PROGRESS.txt`: current operating snapshot and next steps
- `docs/STRATEGY_SELECTION_CHECKLIST.md`: how to choose the current lead strategy without over-trusting sparse paper results
- `docs/GO_LIVE_CHECKLIST.md`: what must be true before even discussing a move from paper to live money
- `project.md`: high-level vision and intended architecture
- `docs/PROJECT_RECORD.md`: durable project intent and current operating reality
- `docs/DECISION_LOG.md`: canonical detailed decision history

## Immediate Next Stage
The next stage should be:
- keep broker routing explicit across approved lanes while the new broker-aware account snapshots and status surfaces bed in
- watch the first broker-separated account history build up in Postgres so Alpaca, Trading 212, and future IG reporting stay cleanly separated
- watch the first successful broker-labelled paper submissions and broker responses during their own market windows
- watch overnight crypto paper behavior now that crypto execution is enabled
- verify fills, simple-entry exit behavior, managed-exit recovery, and position reconciliation
- watch the first `momentum.volatility_breakout` paper proposals/orders closely because the strategy is newly allowlisted and still has a small live-paper sample
- watch the first paper proposals after the 2026-04-21 suppress-threshold calibration, especially whether `mean_reversion.snapback` resumes proposing without flooding the `$10` micro envelope
- use the `Centaur activity` diagnostics first whenever the broker dashboard looks idle, because the most likely explanation may be raw signals being suppressed before proposal creation
- keep micro size and hard limits in place until the broker loop looks boring and reliable

## Maintenance Rule
When a major project decision is made, update `docs/DECISION_LOG.md`.

When the system gains a major new capability or changes operating behavior, update this file.
