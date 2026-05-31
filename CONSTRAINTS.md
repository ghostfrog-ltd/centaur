# Project Centaur Constraints

## Hard Nos
- No use of the `$50/day` target as a reason to bypass risk controls, widen notional, add slots, loosen strategy gates, change brokers, or alter live behavior without explicit human approval and matching reliability-stack updates.
- No live-money trading outside the explicit 2026-05-29 Alpaca Live go-live override and its recorded same-as-paper micro envelope.
- No Alpaca Live entry submission unless the explicit go-live override is recorded, the live enable flag is set, the entry kill switch is clear, credentials are configured, the activation acknowledgement is set, and the go-live record remains current.
- No paper trade bigger than `$10` notional without explicit human override.
- No silent broker switch away from the currently configured execution broker ids.
- No non-equity paper execution while `PAPER_EXECUTION_EQUITY_ONLY=true`.
- No paper order when the paper kill switch is on.
- No new paper entry after the daily equity drawdown protector has triggered.
- No paper equity order outside market hours when `paper_execution_require_market_open=true`.
- No new paper order if earned max open position / open order slots are already occupied.
- No unsupported direction changes. Current paper execution is long-only.
- No silent fallback from PostgreSQL to SQLite for live operation or monitoring.
- No raw chain-of-thought logging.
- No logic changes that contradict this file or the decision log without asking first.
- No safety-critical trading path without docstrings or nearby comments explaining its gating, capital-protection intent, and audit trail. This applies especially to live execution, broker adapters, risk gates, daily protection, stale-order handling, managed exits, and persistence writes.
- No new learning/evidence data capture without a runnable report, dashboard/status surface, or documented query path that lets the operator assess the evidence later.
- No new persistent high-volume table/query path without considering indexes, query shape, and control-loop impact.

## CFO Gate
The CFO gate must hold unless all of the following are true:
- paper execution is enabled
- paper kill switch is off
- account is trade-ready
- market is open if market-open requirement is enabled
- at least one shadow proposal exists
- available slots remain under the open-position limit
- the proposal passes `_build_paper_trade_approval()`
- the selected `broker_id` accepts the trade under its own safety rules
- the strategy is in `paper_execution_allowed_strategies`

Current paper approval rules from the live code:
- equities still require US market hours when `paper_execution_require_market_open=true`
- crypto is allowed when `PAPER_EXECUTION_EQUITY_ONLY=false` and the crypto scan window is available
- long only
- no duplicate symbol if a position is already open
- no duplicate symbol if an open order already exists
- valid entry price
- valid stop loss
- valid target above entry
- projected gain must be at least `1.5%` of entry price for equities and `2.0%` for crypto
- daily equity drawdown must remain under the configured `$5.00` protector
- notional is exactly the configured micro size, currently `$10`
- the selected broker adapter must be able to build the order without widening size or leverage

## Broker Routing
- Execution now runs through a broker-adapter layer instead of hard-wiring Alpaca into every execution path.
- Current active routing:
  - equities -> `alpaca_paper`
  - crypto -> `alpaca_paper`
- `Alpaca Live` exists as a dormant readiness lane; entry submission remains blocked by default, while guarded cancellation and managed sell-exit plumbing are prepared for a future go-live so the lane can be operated with the same protective mechanics as paper.
- `IG` is scaffold-only for now and is not active for execution.
- No IG trade may pass if the minimum spread-bet size would exceed the fixed `$10` notional cap.
- No IG trade may pass if the implied exposure would exceed `1x` leverage.

## Current Paper Execution Envelope
- Strategic target: grow toward a sustained, evidence-backed `$50/day` net profit pace by improving valid trade throughput, average net expectancy, exit/data reliability, and staged slot/capital scaling. This is a research and prioritization target only; current execution limits remain in force until explicitly changed.
- Execution architecture: broker-adapter layer
- Active broker: Alpaca Paper
- IG status: scaffold-only / shadow-only preparation
- Entry type: marketable limit order
- Exit management: internal managed exits
- Fractional equities use `DAY` limit orders because Alpaca does not support `IOC` for fractional equity orders
- Crypto entries and exits may use `IOC` limit orders
- By explicit human override on 2026-05-28, paper crypto marketable-limit orders use a separate `25` bps buffer via `PAPER_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS=25.0`; equities keep the shared `PAPER_EXECUTION_LIMIT_BUFFER_BPS=5.0`, and notional, broker routing, strategy allowlist, projected-gain floors, max orders, slots, daily protector, and live execution remain unchanged
- By explicit human override on 2026-05-28, paper managed exits may capture profit at `1.25%` via `PAPER_EXECUTION_PROFIT_CAPTURE_PCT=0.0125` for both equity and crypto positions; this does not lower the paper entry projected-gain floors or change notional, broker routing, stops, strategy allowlist, slot caps, or live execution
- Shadow outcomes must record the profit-target ladder configured by `SHADOW_PROFIT_TARGET_LADDER_PCT` so Centaur can learn whether waiting for `2%`, `3%`, `4%`, or `6%` would have worked while still taking the live paper `1.25%` capture
- By explicit human override on 2026-05-28, `crypto_momentum.trend` paper managed exits now use `profit_capture_else_1d`: stop loss, profit capture, and target remain active, and positions that hit none of those may hold until a `1d` max-hold backstop instead of being forced out after `60` minutes
- By explicit human override on 2026-05-31, managed max-hold exits must not sell red positions solely because time elapsed for `profit_after_1h_else_1d` or `profit_capture_else_1d`; if the max hold is reached while the reference price is below entry, the exit is deferred as `max_hold_red_deferred` while stop loss, profit capture, take profit, and Friday equity no-weekend-carry exits remain active
- By explicit human override on 2026-05-31, equity paper execution has a no-weekend-carry guard: new equity entries are blocked in the final `60` minutes of the regular Friday session, and managed equity positions still open in the final `15` minutes are flattened with exit reason `friday_no_weekend_carry`; crypto is unchanged because it trades through the weekend
- By explicit human override on 2026-05-28, paper allocation may override a near-miss fitness suppression only for already allowed paper strategies when the raw signal score is at least `90.0` and composite fitness is within `0.25` of the active suppress threshold; this remains paper-only and does not change notional, stops, projected-gain floors, broker routing, max orders, strategy allowlist, daily protector, or live execution
- Daily equity drawdown protector: `$5.00`
- Trailing drawdown observer: observe-only, records per-broker high-water giveback and whether a future guard would block new entries; it must not block paper/live entries, sell positions, cancel orders, or latch protection without a separate explicit human override
- Stale unfilled equity entry orders are reaped after `5` minutes
- Max orders per tick: `1`
- Base max open positions: `10`
- Earned-slot compounding rule: by explicit human override on 2026-05-20, paper may add `1` effective open-position slot for each full `$10` of tracked P/L above the pre-first-order baseline; `$13` tracked P/L therefore allows `11` effective slots while keeping each entry at `$10`
- Earned slots are dynamic and can fall away if tracked P/L drops below a full `$10` increment
- Default notional: `$10`
- Allowed paper strategies at time of writing: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`
- Asset classes currently allowed for paper execution: equities and crypto
- By explicit human override on 2026-05-28, `crypto_momentum.trend` keeps its crypto-only runtime knobs but lowers `CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE` from `4.5` to `2.5` so overnight crypto candidates with decent movement can qualify for signal generation more often; stop loss stays `3.0%`, target multiple `2.0`, min signal score `60`, min movement `0.15%`, min trade count `2`, and the crypto-specific paper projected-gain floor stays `2.0%`
- By explicit human override on 2026-05-27, the crypto discovery universe was widened from `5` to `11` USD pairs: `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `DOGE/USD`, `LTC/USD`, `BCH/USD`, `LINK/USD`, `AVAX/USD`, `UNI/USD`, and `AAVE/USD`, while keeping the same `$10` notional, one-order-per-tick cap, broker routing, and stricter crypto entry knobs
- Strategy-allocation suppress threshold in `.env`: `-5.60`; last manually tightened by explicit human override on 2026-05-27 to reduce weak `mean_reversion.snapback` entries while keeping paper execution active
- By explicit human override on 2026-05-27, crypto now has its own fixed suppress threshold of `-6.90` via `STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD`, while equities continue to use the existing paper-only adaptive suppress threshold rails
- Adaptive paper-only strategy threshold controller: enabled by explicit human override on 2026-05-13
- Adaptive controller rails: the default effective threshold may move from `-5.60` down to the configured fallback floor `-6.40`, at no more than `0.10` per adjustment, with at least `medium` GA confidence, at least `120` evidence ticks, and a `30` minute cooldown
- By explicit human override on 2026-05-27, the adaptive cliff-governor safety gap was restored from `0.05` to `0.10`, the fixed suppress threshold was tightened to `-5.60`, and the fallback floor was tightened to `-6.40` so paper stays active but the recent weak `mean_reversion.snapback` cliff near `-6.77` is no longer admitted
- Adaptive cliff governor: when the current tick has a clean paper-allowed, proposal-viable strategy cliff just below the configured fallback floor, the controller may step below `-6.40` only far enough to admit that allowed cliff, only by the configured max step, and only if the nearest blocked/disallowed cliff remains at least the configured `0.10` safety gap lower
- Adaptive controller band: the trade-aware GA tracks a local cliff band of `+/-0.10` around the current recommended threshold, while the cliff governor prevents chasing very weak `-11`/`-12` style signals and keeps the current `-6.86` liquidity-probe band blocked
- Adaptive catch-up: when the GA has already met the confidence/evidence gates and is moving toward the same tradeable local cliff with no non-tradeable survivors, it may continue taking `0.10` catch-up steps without waiting for the cooldown; the configured fallback floor still applies unless the current-tick cliff governor has a clean allowed-vs-blocked safety gap
- Adaptive controller state is persisted in PostgreSQL and must not mutate `.env`, notional, broker routing, live readiness, max slots, projected-gain, daily-protection, stale-order, market-hours, long-only, or strategy-allowlist policy
- The adaptive controller remains the equity suppress-threshold controller; it does not mutate the separate fixed crypto suppress threshold
- GA threshold advice outside those adaptive rails remains recommendation-only and must not change paper/live execution policy without a separate explicit human override
- Holding-window fitness advice is recommendation-only; it may compare `15m`, `1h`, `1d`, `7d`, and simple dynamic policies from shadow outcomes, but it must not change managed paper exits without a separate explicit human override
- By explicit human override on 2026-05-26, `mean_reversion.snapback` paper managed exits now use `profit_after_1h_else_1d`: stop loss and target remain active as before, profitable positions may be sold after `1` hour, and non-profitable positions may continue until the `1d` max-hold backstop
- Open paper sell exits may be canceled and refreshed when the limit is no longer marketable or has gone stale, so a protective/managed exit cannot silently strand a losing position behind an old unfilled limit
- Paper managed exits normalize Alpaca crypto symbols with and without slashes, e.g. `AAVEUSD` positions can match `AAVE/USD` entry plans and bars, so crypto stop/target/time exits are not skipped as `missing_entry_plan`
- By explicit human override on 2026-05-27, automatic `var/dashboard_snapshot.json` refresh after each control tick is disabled in the current headless trading mode; snapshot generation remains available as a separate manual operator action and must not slow the trade loop
- By explicit human override on 2026-05-27, the unattended `launchd` schedule is tightened from `60` seconds to `30` seconds, with a wrapper-level lock so overlapping launches skip cleanly instead of stacking

## Current Live Execution Lane
- Alpaca Live broker id: `alpaca_live`
- Status after explicit 2026-05-29 operator override: approved for activation as a same-as-paper follower lane
- Prepared bankroll model: `$10` x `10` slots = `$100`
- Current observed Alpaca Live balance after funding check: `$132.05`; this does not widen the prepared `$10 x 10` envelope or the `$5.00` daily protector
- First-live plan has been recorded as a same-as-paper follower lane, by operator request, rather than the safer generic one-strategy launch default
- First-live operating bankroll is `$100` from the observed `$132.05` account; the extra `$32.05` is launch buffer only and does not create more slots
- Prepared live strategy allowlist now mirrors paper for readiness only: `mean_reversion.snapback`, `crypto_momentum.trend`, and `momentum.volatility_breakout`
- Prepared live asset classes now mirror paper for readiness only: equities and crypto
- Prepared live entry economics mirror paper: `$10` notional, `1` order per tick, `10` base slots, `$5.00` daily drawdown protector, `1.5%` equity projected-gain floor, `2.0%` crypto projected-gain floor, `5` bps equity limit buffer, and `25` bps crypto limit buffer
- The equity no-weekend-carry guard mirrors paper for the same-as-paper live follower lane: late-Friday equity entries are blocked by paper before live can follow them, and activated live managed exits use the same Friday flatten reason for managed equity positions
- The trailing drawdown observer may record Alpaca Live high-water giveback evidence, but observe-only output cannot create an independent live blocker or widen/alter the same-as-paper follower rule
- Earned-slot compounding mirrors paper for live once live has its own baseline and P/L, but API keys alone still cannot activate live trading
- Live entry submission is allowed only while all recorded live go-live gates pass
- Live cancellation, stale-entry reaping, and managed sell exits are guarded by credentials plus activation acknowledgement, and are prepared so a future live lane can refresh stale/non-marketable orders instead of stranding positions
- API keys plus `LIVE_EXECUTION_ENABLED=true` alone must not activate live trading
- Live may only follow a trade that the paper CFO gate approved and the paper execution step actually submitted on the same tick
- Required live entry activation gates: live execution enabled, kill switch off, Alpaca Live credentials configured, `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`, at least one live allowed strategy, available live slots, live daily drawdown below the configured limit, and broker validation success
- Live strategy intelligence remains shared with paper/shadow fitness; the separate live intelligence lane is read-only execution monitoring for fill drift, status mismatch, and unmatched-order diagnostics, not an independent live strategy scorer
- The first-live plan records strategy policy, starting slot count, daily loss limit, kill-switch rule, and rollback conditions; the 2026-05-29 explicit operator override authorizes flipping the activation flags within that envelope only
- First-live rollback triggers include unexpected live positions/orders, account blocks or suspensions, live orders that do not match same-proposal submitted paper orders, abnormal live-vs-paper fill/status drift, stale live orders that cannot be refreshed, unavailable account equity, the `$5.00` live protector triggering, or operator discomfort

## Documentation And Auditability
- Safety-critical functions must have docstrings or compact comments that explain why they exist and which risk boundary they protect.
- Comments must clarify non-obvious trading intent, not narrate obvious assignments.
- If a future change touches live execution, risk gates, broker order submission/cancellation, daily protection, stale-order reaping, managed exits, strategy fitness admission, or persistent trade/account records, update the relevant doc block or nearby comment in the same change.
- If a future change captures evidence for later learning, update `.venv-mac/bin/python main.py --evidence-report` or an equivalent report surface in the same task, and document how the evidence should be interpreted.
- Documentation must stay honest about the current mode: paper active, Alpaca Live dormant/readiness unless a recorded go-live override says otherwise.

## Database And Performance
- PostgreSQL remains the live operations source; do not silently route live monitoring or operation through SQLite.
- If PostgreSQL is configured, or paper/live execution is enabled, the operations ledger must fail closed when PostgreSQL is unavailable instead of falling back to SQLite.
- New persistence paths must be shaped for operator queries before they are considered complete: add appropriate indexes, use bounded lookbacks where possible, and avoid table scans on the normal control tick.
- New reports should prefer existing rollups/snapshots or indexed lookups over repeatedly rebuilding expensive views from raw history.
- CLI/status heartbeat views should avoid dashboard-only heavy visual queries unless explicitly requested by a dashboard snapshot path.
- Database optimization is part of feature quality, not cleanup for later, when the feature adds regular writes or repeated reads.

## Replay / Learning Constraints
- Historical replay is allowed and preferred for fast training.
- Replay results must not be presented as proven live edge.
- Small samples must be treated as exploratory, not trustworthy.

## Override Rule
If a user asks for something that violates one of these constraints, pause and ask for a human override instead of implementing it directly.
