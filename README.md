# Project Centaur

Project Centaur is a pipeline-first trading research and micro paper-trading system.

It scans equity and crypto markets, creates deterministic strategy signals, scores them against stored shadow outcomes, applies strict risk/CFO gates, and submits tiny Alpaca Paper orders only when the configured constraints allow it.

The current experiment is deliberately small:

> Can a system trade for almost nothing, repeatedly capture small profits, keep losses controlled, and produce a measurable edge before any live-money discussion?

Centaur is not a live-money bot. It is an auditable learning system with a paper execution lane.

## The Current Hypothesis

The important 2026-05-28 insight is that Centaur's paper lane is a **micro system**.

That means:

- `$10` entries
- small profit capture
- many repetitions
- strict stops and daily protection
- fitness as a guardrail, not a total handbrake
- larger profit targets recorded in shadow, not forced onto tiny paper trades

The suspected old failure mode was:

1. Centaur found high-scoring setups.
2. The setup score was often strong, for example `92`.
3. The accumulated fitness score drifted just below the suppress threshold.
4. Fitness acted as a hard veto.
5. No `$10` entry happened, so the system could not express the micro edge.
6. When trades did happen, old targets were often too ambitious for `$10` micro trades.

The current paper operating model is:

```text
high-quality setup -> $10 paper entry -> 1.25% profit capture -> record what bigger targets would have done -> repeat and measure
```

This is a hypothesis, not proof. The goal now is to collect enough paper outcomes to judge whether the small edge survives across different market sessions.

## What Would Count As Evidence?

Useful evidence:

- how often `1.25%` profit capture fires
- average win size
- average loss size
- stop-hit frequency
- time-to-profit-capture
- daily realized P/L
- whether losing days stay small
- whether `2%`, `3%`, `4%`, or `6%` targets would have hit later in shadow
- whether crypto and equities behave differently

Danger signs:

- many trades hit stops before touching `1.25%`
- average loss grows larger than several small wins
- high-score override floods weak trades
- daily drawdown protector is hit often
- green open P/L appears but does not convert into filled exits
- results depend on one unusual market session

## Current Status

- Runtime: Python control pipeline
- Scheduler: macOS `launchd`, currently every `30` seconds, with busy-skip locking
- Operations store: PostgreSQL
- Dashboard: DDEV/OrbStack web dashboard at `https://ghostfrog-centaur.ddev.site`
- Active broker: Alpaca Paper
- Live broker: Alpaca Live same-as-paper follower lane approved for activation on 2026-05-29
- Trade size: `$10` paper notional
- Base paper slots: `10`
- Earned slots: each full `$10` of tracked paper P/L earns one extra `$10` slot
- Allowed paper strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`
- Paper exit capture: `1.25%`
- Shadow target ladder: `1.25%`, `2%`, `3%`, `4%`, `6%`
- Live-money trading: approved only inside the recorded `$10 x 10` Alpaca Live envelope

API keys alone must not activate live trading.

## Safety Rules

Read these before changing behavior:

- [AGENTS.md](AGENTS.md)
- [CONSTRAINTS.md](CONSTRAINTS.md)
- [DECISION_LOG.md](DECISION_LOG.md)
- [SKILL.md](SKILL.md)
- [PROGRESS.txt](PROGRESS.txt)

Important current constraints:

- No live-money order submission outside the recorded 2026-05-29 go-live override.
- No paper trade above `$10` notional without explicit approval.
- No silent broker switch.
- No silent risk widening.
- No new paper entry after the daily drawdown protector has triggered.
- Equities require market hours when configured.
- Crypto can trade outside equity market hours when crypto scanning is ready.
- Current paper execution is long-only.
- Existing stops, projected-gain checks, broker routing, max orders, and daily protector stay active.

## How A Tick Works

Each control tick is an explicit sequence:

1. Sync account, clock, positions, and recent orders.
2. Apply paper/live protection checks.
3. Decide whether equity and crypto scans are allowed.
4. Fetch latest bars.
5. Manage exits for open paper positions.
6. Evaluate due shadow checkpoints.
7. Recompute strategy fitness.
8. Discover current market candidates.
9. Generate deterministic strategy signals.
10. Apply fitness allocation and high-score near-miss override.
11. Create shadow proposals.
12. Apply paper CFO/risk approval.
13. Submit Alpaca Paper orders.
14. Let Alpaca Live follow only submitted same-tick paper trades if every live gate passes.
15. Persist diagnostics for status and review.

Paper and live can see the same signal, but each lane must pass its own checks.

## How The Current Paper Rules Work

### Entry

Centaur does not buy `$10` of anything that moved up. A paper trade must pass:

- market gate
- strategy signal generation
- fitness allocation
- paper strategy allowlist
- long-only check
- no duplicate position/order
- valid entry price
- valid stop
- valid target
- projected-gain floor
- daily drawdown protector
- slot availability
- broker validation

Only after those pass does the system size the order at `$10`.

### High-score near-miss override

This was added after the 2026-05-28 diagnosis.

If a paper-allowed strategy has a raw `signal_score >= 90.0`, and its composite fitness is only slightly below the active suppress threshold, it can survive suppression.

Current settings:

```text
PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED=true
PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE=90.0
PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN=0.25
```

This means a signal like:

```text
score=92
fitness=-6.889
threshold=-6.800
```

can be allowed through because it is only `0.089` under the line.

This does **not** allow disallowed strategies to trade, and it does **not** override stops, projected-gain checks, broker routing, notional, max orders, or live execution.

### Exit

Current real paper exit idea:

```text
take small profit when available; do not wait for heroic targets on $10 trades
```

Paper managed exits can sell when:

- stop loss is hit
- `1.25%` profit capture is hit
- the larger planned target is hit
- a managed policy says the hold/backstop has elapsed

For `crypto_momentum.trend`, the current managed policy is `profit_capture_else_1d`: the `1.25%` capture, stop, and larger target stay active, but if none of them hit the position can hold up to a `1d` backstop.

For `mean_reversion.snapback`, profitable positions may exit after `1h`, while non-profitable positions can continue under stop/target protection until a `1d` backstop.

## Shadow Learning

Shadow learning is how Centaur asks "what would have happened?" without risking the actual paper position.

Current checkpoints:

```text
SHADOW_CHECKPOINT_WINDOWS=15m,1h,1d,7d
```

Current profit-target ladder:

```text
SHADOW_PROFIT_TARGET_LADDER_PCT=1.25,2,3,4,6
```

This lets us keep the real paper behavior conservative while still learning:

- would `2%` have hit?
- would `3%` have hit?
- would `4%` have hit?
- would `6%` have hit?
- did the stop hit first?
- did waiting help or hurt?

That matters because we do not want to guess. We want to sell at `1.25%` now, then let the shadow record tell us whether higher exits are worth testing later.

## Key Variables

These live in `.env`. Use `.env.example` as the template.

### Control

`CONTROL_TICK_INTERVAL_SECONDS`
: Target scheduler interval. Currently `30`.

`CONTROL_MAX_TICK_RUNTIME_SECONDS`
: Expected maximum tick runtime before it should be treated as too slow.

`CONTROL_REFRESH_DASHBOARD_SNAPSHOT`
: Whether each control tick refreshes `var/dashboard_snapshot.json`. Currently false so dashboard work does not slow trading.

`CONTROL_LOCK_NAME`
: Lock name used by the wrapper so scheduled ticks skip instead of stacking.

### Database and Cost

`OPERATIONS_DB_BACKEND`
: Live operations backend. Current repo truth is PostgreSQL.

`DATABASE_URL`
: PostgreSQL connection string.

`API_DAILY_COST_WARNING_USD` / `API_DAILY_COST_LIMIT_USD`
: Cost guardrails for API usage.

### Gemini

`GEMINI_API_KEY`
: Gemini credential. Current runtime analysis is usually kept disabled for cost control.

`GEMINI_API_BASE_URL`
: Gemini API base URL.

`GEMINI_MODEL`
: Gemini model name used when analysis is enabled.

`GEMINI_ANALYSIS_ENABLED`
: Enables or disables Gemini analysis/commentary. Deterministic trading logic must not depend on hidden LLM behavior.

`GEMINI_REQUEST_TIMEOUT_SECONDS`
: Timeout for Gemini calls.

`GEMINI_ANALYSIS_CANDIDATE_LIMIT`
: Maximum candidates sent for Gemini analysis.

`GEMINI_MAX_OUTPUT_TOKENS`
: Output limit for Gemini responses.

`GEMINI_INPUT_COST_PER_MILLION_TOKENS_USD` / `GEMINI_OUTPUT_COST_PER_MILLION_TOKENS_USD`
: Pricing inputs used for API cost estimates.

### Market Universe

`DISCOVERY_EQUITY_SYMBOLS`
: Equity symbols scanned for candidates. Currently Nasdaq-100 style universe.

`DISCOVERY_CRYPTO_SYMBOLS`
: Crypto symbols scanned for candidates.

`ALPACA_CRYPTO_SYMBOLS`
: Crypto symbols requested from Alpaca.

`DISCOVERY_TARGET_COUNT`
: Number of candidates selected for downstream strategy evaluation.

### Shadow Strategy Defaults

`SHADOW_ENABLED`
: Enables shadow proposal generation and learning.

`SHADOW_PROPOSAL_LIMIT`
: Maximum shadow proposals created per tick.

`SHADOW_PROPOSAL_COOLDOWN_MINUTES`
: Prevents repeatedly proposing the same strategy/source/symbol too quickly.

`SHADOW_MIN_OPPORTUNITY_SCORE`
: Minimum strategy signal score needed for a shadow proposal.

`SHADOW_STOP_LOSS_PCT`
: Default stop distance for shared shadow strategies.

`SHADOW_TARGET_MULTIPLE`
: Default target multiple relative to risk.

`SHADOW_CHECKPOINT_WINDOWS`
: Future checkpoints to evaluate for each shadow proposal. Currently `15m,1h,1d,7d`.

`SHADOW_PROFIT_TARGET_LADDER_PCT`
: Counterfactual target ladder. Currently `1.25,2,3,4,6`.

`SHADOW_EXECUTION_SPREAD_BPS`, `SHADOW_ENTRY_SLIPPAGE_BPS`, `SHADOW_EXIT_SLIPPAGE_BPS`
: Friction assumptions used in shadow/replay scoring.

`SHADOW_FIXED_ROUND_TRIP_COST_USD`
: Fixed per-trade cost assumption. Important for `$10` micro trades because pennies matter.

### Crypto Momentum

`CRYPTO_MOMENTUM_STOP_LOSS_PCT`
: Crypto-specific stop. Currently `0.03`.

`CRYPTO_MOMENTUM_TARGET_MULTIPLE`
: Crypto-specific target multiple. Currently `2.0`.

`CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE`
: Minimum crypto momentum signal score. Currently `60.0`.

`CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT`
: Required positive crypto movement. Currently `0.15`.

`CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE`
: Discovery floor for crypto candidates. Currently `2.5`.

`CRYPTO_MOMENTUM_MIN_TRADE_COUNT`
: Minimum trade count. Currently `2`.

### Fitness Allocation

`STRATEGY_FITNESS_LOOKBACK_DAYS`
: Fitness lookback. `0` means all available history.

`STRATEGY_FITNESS_MIN_CHECKPOINTS`
: Minimum checkpoint count for fitness summary confidence.

`STRATEGY_ALLOCATION_MIN_CHECKPOINTS`
: Minimum checkpoints before a fitness row can suppress/favor signals.

`STRATEGY_ALLOCATION_FAVOR_THRESHOLD`
: Fitness level that favors a signal.

`STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD`
: Main equity suppress threshold.

`STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD`
: Separate crypto suppress threshold.

`STRATEGY_THRESHOLD_ADAPTIVE_ENABLED`
: Enables the guarded adaptive suppress-threshold controller.

`STRATEGY_THRESHOLD_ADAPTIVE_FLOOR` / `STRATEGY_THRESHOLD_ADAPTIVE_CEILING`
: Rails for adaptive threshold movement.

`STRATEGY_THRESHOLD_ADAPTIVE_BAND_WIDTH`
: Local band used by threshold advice/cliff logic.

`STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP`
: Separation required between allowed and blocked/disallowed cliffs.

`STRATEGY_THRESHOLD_ADAPTIVE_MAX_STEP`
: Maximum threshold move per adjustment.

`STRATEGY_THRESHOLD_ADAPTIVE_MIN_CONFIDENCE`
: Confidence gate for adaptive changes.

`STRATEGY_THRESHOLD_ADAPTIVE_COOLDOWN_MINUTES`
: Cooldown between adaptive changes.

`STRATEGY_THRESHOLD_ADAPTIVE_MIN_TICKS`
: Minimum usable tick evidence before adaptive changes.

### Paper Execution

`PAPER_EXECUTION_ENABLED`
: Enables paper order submission.

`PAPER_EXECUTION_KILL_SWITCH`
: If true, blocks paper execution.

`PAPER_EXECUTION_REQUIRE_MARKET_OPEN`
: Equities require market open when true.

`PAPER_EXECUTION_EQUITY_ONLY`
: If true, crypto paper execution is blocked.

`PAPER_EXECUTION_MAX_ORDERS_PER_TICK`
: Hard cap on order submissions per tick. Currently `1`.

`PAPER_EXECUTION_MAX_OPEN_POSITIONS`
: Base open position/order slot cap. Currently `10`.

`PAPER_EXECUTION_DEFAULT_NOTIONAL_USD`
: Per-trade size. Currently `$10.00`.

`PAPER_EXECUTION_MAX_DAILY_DRAWDOWN_USD`
: Daily equity drawdown protector. Currently `$5.00`.

`PAPER_EXECUTION_STALE_ORDER_MINUTES`
: Unfilled equity entry limits older than this are canceled.

`PAPER_EXECUTION_MIN_PROJECTED_GAIN_PCT`
: Equity projected-gain floor. Currently `0.015`, or `1.5%`.

`PAPER_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT`
: Crypto projected-gain floor. Currently `0.02`, or `2%`.

`PAPER_EXECUTION_PROFIT_CAPTURE_PCT`
: Real paper profit capture. Currently `0.0125`, or `1.25%`.

`PAPER_EXECUTION_LIMIT_BUFFER_BPS`
: Equity marketable-limit buffer. Currently `5.0` bps.

`PAPER_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS`
: Crypto marketable-limit buffer. Currently `25.0` bps.

`PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED`
: Enables the paper-only near-miss override for very strong setup scores.

`PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE`
: Minimum raw signal score for the override. Currently `90.0`.

`PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN`
: How far below the active fitness threshold a high-score signal may be and still survive. Currently `0.25`.

`PAPER_EXECUTION_ALLOWED_STRATEGIES`
: Strategy allowlist for paper orders.

### Broker Routing

`PAPER_EXECUTION_EQUITY_BROKER_ID`
: Current equity paper broker. Usually `alpaca_paper`.

`PAPER_EXECUTION_CRYPTO_BROKER_ID`
: Current crypto paper broker. Usually `alpaca_paper`.

`ALPACA_API_KEY` / `ALPACA_SECRET_KEY`
: Alpaca Paper credentials.

`ALPACA_BASE_URL`
: Alpaca Paper API base URL.

`ALPACA_DATA_BASE_URL`
: Alpaca data API base URL.

`ALPACA_STOCK_FEED`
: Alpaca stock feed, currently `iex`.

`ALPACA_REQUEST_TIMEOUT_SECONDS`
: Timeout for Alpaca requests.

`ALPACA_WATCHLIST_SYMBOLS`
: Alpaca watchlist universe.

`ALPACA_CRYPTO_LOCATION`
: Alpaca crypto location setting, currently `us`.

`ALPACA_REQUEST_COST_USD`, `ALPACA_DATA_REQUEST_COST_USD`, `ALPACA_CRYPTO_DATA_REQUEST_COST_USD`
: Pricing inputs for internal cost accounting.

### Historical Replay

`HISTORICAL_BACKFILL_DEFAULT_DAYS` / `HISTORICAL_BACKFILL_DEFAULT_TIMEFRAME`
: Defaults for market-data backfill.

`HISTORICAL_REPLAY_DEFAULT_DAYS` / `HISTORICAL_REPLAY_DEFAULT_TIMEFRAME`
: Defaults for replay runs.

`HISTORICAL_REPLAY_MAX_TIMESTAMPS`
: Optional replay cap. `0` means no timestamp cap.

### FX and Optional Providers

`ECB_REFERENCE_RATES_URL`
: ECB reference-rate feed used for GBP reporting.

`ECB_REQUEST_TIMEOUT_SECONDS`
: Timeout for ECB requests.

`ECB_REFERENCE_CACHE_MINUTES`
: How long to cache ECB reference data.

`POLYGON_API_KEY` / `NEWS_API_KEY`
: Optional provider keys.

`POLYGON_REQUEST_COST_USD` / `NEWS_API_REQUEST_COST_USD`
: Optional provider cost assumptions.

`APP_SHARED_SECRET` / `WEBHOOK_SECRET`
: Shared app/webhook secrets.

### IG Scaffold

`IG_API_KEY`, `IG_USERNAME`, `IG_PASSWORD`, `IG_ACCOUNT_NUMBER`
: IG demo credentials. IG remains scaffold-only unless separately approved.

`IG_ACCOUNT_TYPE`
: IG account type, normally `DEMO`.

`IG_BASE_URL`
: IG API base URL.

`IG_REQUEST_TIMEOUT_SECONDS`
: Timeout for IG requests.

`IG_MIN_BET_PER_POINT_GBP`
: Minimum IG bet size assumption. Important because IG may not fit the `$10`/`1x` safety envelope.

`IG_EPIC_OVERRIDES`
: Optional symbol-to-IG-epic mapping.

`IG_REQUEST_COST_USD`
: Cost assumption for IG requests.

### Live Execution

Live execution has its own variables and remains bounded by explicit activation gates.
Strategy fitness remains shared through shadow outcomes. The live execution
intelligence surface is read-only and monitors future live-vs-paper fill drift,
status mismatch, unmatched live orders, and blockers. The live mechanics are
prepared to mirror paper, including live account readiness, persisted daily
protection, stale-entry cleanup, and managed sell-exit refresh. The 2026-05-29
operator override authorizes activation only inside the recorded same-as-paper
micro envelope.

`ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_SECRET_KEY`
: Alpaca Live credentials. Credentials alone are insufficient.

`ALPACA_LIVE_BASE_URL`
: Alpaca Live API base URL.

`LIVE_EXECUTION_ENABLED`
: Main live execution enable flag. Must remain false unless a go-live override is completed.

`LIVE_EXECUTION_KILL_SWITCH`
: Live kill switch. Must remain on until explicit go-live.

`LIVE_EXECUTION_REQUIRE_MARKET_OPEN`
: Market-hours requirement for live equities.

`LIVE_EXECUTION_EQUITY_ONLY`
: Live asset-class restriction.

`LIVE_EXECUTION_MAX_ORDERS_PER_TICK`
: Live order cap per tick.

`LIVE_EXECUTION_MAX_OPEN_POSITIONS`
: Live slot cap.

`LIVE_EXECUTION_DEFAULT_NOTIONAL_USD`
: Live order notional. Scaffold default mirrors the `$10` paper size.

`LIVE_EXECUTION_MAX_DAILY_DRAWDOWN_USD`
: Live daily loss limit.

`LIVE_EXECUTION_MIN_PROJECTED_GAIN_PCT`
: Live equity projected-gain floor.

`LIVE_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT`
: Live crypto projected-gain floor.

`LIVE_EXECUTION_LIMIT_BUFFER_BPS`
: Live equity marketable-limit buffer.

`LIVE_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS`
: Live crypto marketable-limit buffer.

`LIVE_EXECUTION_EQUITY_BROKER_ID` / `LIVE_EXECUTION_CRYPTO_BROKER_ID`
: Live broker routing ids.

`LIVE_EXECUTION_ALLOWED_STRATEGIES`
: Live strategy allowlist. Empty means none allowed.

`LIVE_EXECUTION_ACTIVATION_ACK`
: Must be set to the approved acknowledgement value during a real go-live process.

Live trading requires all of these to be intentionally handled:

- live execution enabled
- live entry kill switch off
- live credentials present
- activation acknowledgement set
- live strategy allowlist configured
- go-live checklist updated

API keys plus `LIVE_EXECUTION_ENABLED=true` are not enough. Live entries only
follow paper trades that were approved and actually submitted on the same tick;
guarded cancellation and managed sell exits exist so a deliberately activated
live lane can protect positions like paper.

Do not infer live readiness from paper success.

Current funded readiness state: Alpaca Live keys and read-only funded checks
passed with an active, unblocked account, `132.05` cash/equity/buying power,
and no positions or recent/open orders. That balance does not widen the `$10 x
10` live envelope. First-live strategy policy, limits, and rollback rules are
now recorded: by operator request, live starts as a same-as-paper follower lane
using the current paper strategy allowlist, equities plus crypto, `$10` entries,
`10` base slots, one order per tick, the `$5.00` live daily protector, shared
paper/shadow fitness, and read-only live execution intelligence. The extra
`32.05` above the `$100` operating envelope is buffer only. On 2026-05-29 at
about 10:48 BST, the operator explicitly approved turning Alpaca Live on within
that recorded envelope. That approval does not widen notional, slots, strategy
allowlist, asset classes, projected-gain floors, limit buffers, or daily loss
limits.

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

Run a paper exit post-mortem:

```bash
.venv-mac/bin/python main.py --paper-exit-review --strategy-id mean_reversion.snapback
```

Run combined strategy health:

```bash
.venv-mac/bin/python main.py --strategy-health --strategy-id mean_reversion.snapback
```

Run overnight crypto health:

```bash
.venv-mac/bin/python main.py --crypto-health
```

Run historical replay:

```bash
.venv-mac/bin/python main.py --replay
```

Start DDEV:

```bash
ddev start
```

## How To Mull The Results

When Alpaca shows `+0.00%`, remember it is dividing by the whole `$100k` paper account.

For this experiment, the better denominators are:

- per trade: `$10`
- current paper envelope: about `$100-$110`
- daily realized/unrealized P/L in dollars

Example:

```text
$0.50/day * 30 days = $15/month
$15 / $110 = 13.6% monthly return on the micro envelope
```

That is why tiny dollar moves can still be meaningful research signals.

But the comparison is only fair if losses stay controlled. Bank interest is low-risk; trading P/L is noisy and can reverse.

## Dashboard

The primary dashboard is the DDEV/OrbStack web app:

```text
https://ghostfrog-centaur.ddev.site
```

It reads:

```text
var/dashboard_snapshot.json
```

That file is runtime output and is ignored by Git. In the current headless trading setup, automatic snapshot refresh after each control tick is disabled so the trade loop does not wait on dashboard work.

To refresh manually:

```bash
.venv-mac/bin/python scripts/dashboard_snapshot.py
```

## Durable Project Memory

Long-lived project history lives in:

- [docs/PROJECT_RECORD.md](docs/PROJECT_RECORD.md)
- [docs/DECISION_LOG.md](docs/DECISION_LOG.md)
- [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)
- [docs/STRATEGY_SELECTION_CHECKLIST.md](docs/STRATEGY_SELECTION_CHECKLIST.md)

When runtime behavior or risk policy changes, update the reliability stack in the same task.

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

## Disclaimer

Centaur is a research and paper-trading system. Paper results are exploratory and may not translate to live execution. Live trading involves real risk, including slippage, rejected orders, partial fills, changing market regimes, and loss of capital.
