# Project Centaur Constraints

## Hard Nos
- No live-money trading.
- No Alpaca Live order submission while the live lane is scaffold-only.
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
- projected gain must be at least `1.5%` of entry price
- daily equity drawdown must remain under the configured `$5.00` protector
- notional is exactly the configured micro size, currently `$10`
- the selected broker adapter must be able to build the order without widening size or leverage

## Broker Routing
- Execution now runs through a broker-adapter layer instead of hard-wiring Alpaca into every execution path.
- Current active routing:
  - equities -> `alpaca_paper`
  - crypto -> `alpaca_paper`
- `Alpaca Live` now exists as a scaffold/readiness lane only; it must not submit or cancel live orders until a go-live override updates this file and the decision log.
- `IG` is scaffold-only for now and is not active for execution.
- No IG trade may pass if the minimum spread-bet size would exceed the fixed `$10` notional cap.
- No IG trade may pass if the implied exposure would exceed `1x` leverage.

## Current Paper Execution Envelope
- Execution architecture: broker-adapter layer
- Active broker: Alpaca Paper
- IG status: scaffold-only / shadow-only preparation
- Entry type: marketable limit order
- Exit management: internal managed exits
- Fractional equities use `DAY` limit orders because Alpaca does not support `IOC` for fractional equity orders
- Crypto entries and exits may use `IOC` limit orders
- Daily equity drawdown protector: `$5.00`
- Stale unfilled equity entry orders are reaped after `5` minutes
- Max orders per tick: `1`
- Base max open positions: `10`
- Earned-slot compounding rule: by explicit human override on 2026-05-20, paper may add `1` effective open-position slot for each full `$10` of tracked P/L above the pre-first-order baseline; `$13` tracked P/L therefore allows `11` effective slots while keeping each entry at `$10`
- Earned slots are dynamic and can fall away if tracked P/L drops below a full `$10` increment
- Default notional: `$10`
- Allowed paper strategies at time of writing: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`
- Asset classes currently allowed for paper execution: equities and crypto
- Strategy-allocation suppress threshold in `.env`: `-5.70`; last manually lowered by explicit human override on 2026-05-11
- Adaptive paper-only strategy threshold controller: enabled by explicit human override on 2026-05-13
- Adaptive controller rails: the default effective threshold may move from `-5.70` down to the configured fallback floor `-6.50`, at no more than `0.10` per adjustment, with at least `medium` GA confidence, at least `120` evidence ticks, and a `30` minute cooldown
- Adaptive cliff governor: when the current tick has a clean paper-allowed, proposal-viable strategy cliff just below the configured fallback floor, the controller may step below `-6.50` only far enough to admit that allowed cliff, only by the configured max step, and only if the nearest blocked/disallowed cliff remains at least `0.10` lower
- Adaptive controller band: the trade-aware GA tracks a local cliff band of `+/-0.10` around the current recommended threshold, while the cliff governor prevents chasing very weak `-11`/`-12` style signals and keeps the current `-6.86` liquidity-probe band blocked
- Adaptive catch-up: when the GA has already met the confidence/evidence gates and is moving toward the same tradeable local cliff with no non-tradeable survivors, it may continue taking `0.10` catch-up steps without waiting for the cooldown; the configured fallback floor still applies unless the current-tick cliff governor has a clean allowed-vs-blocked safety gap
- Adaptive controller state is persisted in PostgreSQL and must not mutate `.env`, notional, broker routing, live readiness, max slots, projected-gain, daily-protection, stale-order, market-hours, long-only, or strategy-allowlist policy
- GA threshold advice outside those adaptive rails remains recommendation-only and must not change paper/live execution policy without a separate explicit human override
- Holding-window fitness advice is recommendation-only; it may compare `15m`, `1h`, `1d`, and simple dynamic policies from shadow outcomes, but it must not change managed paper exits without a separate explicit human override

## Current Live Execution Lane
- Alpaca Live broker id: `alpaca_live`
- Default status: disabled with kill switch on
- Prepared bankroll model: `$10` x `10` slots = `$100`
- Default live strategy allowlist: empty
- Earned-slot compounding mirrors paper for live once live has its own baseline and P/L, but API keys alone still cannot activate live trading
- Live order submission remains blocked by configuration unless all live go-live gates pass
- API keys alone must not activate live trading
- Live may only follow a trade that the paper CFO gate has already approved on the same tick
- Required live activation gates: live execution enabled, kill switch off, Alpaca Live credentials configured, `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`, at least one live allowed strategy, available live slots, live daily drawdown below the configured limit, and broker validation success
- A future go-live override must record the strategy, starting slot count, daily loss limit, kill-switch rule, and rollback conditions before any real-money order path is turned on in configuration

## Replay / Learning Constraints
- Historical replay is allowed and preferred for fast training.
- Replay results must not be presented as proven live edge.
- Small samples must be treated as exploratory, not trustworthy.

## Override Rule
If a user asks for something that violates one of these constraints, pause and ask for a human override instead of implementing it directly.
