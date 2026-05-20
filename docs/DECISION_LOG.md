# Project Centaur Decision Log

This file records important decisions so the project does not depend on chat memory alone.

Last updated: 2026-05-20

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
- require a same-tick paper-approved trade before live can consider following it

Why:
- first production should use the same signal/fitness brain as paper rather than invent a separate live strategy
- live and paper account state may diverge, so live still needs separate position, order, slot, and drawdown checks
- API keys alone must not be enough to place real-money trades

Implementation notes:
- current `.env` keeps `LIVE_EXECUTION_ENABLED=false`, `LIVE_EXECUTION_KILL_SWITCH=true`, and an empty live allowlist
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
- keep Alpaca Live order submission and cancellation blocked in the adapter
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
