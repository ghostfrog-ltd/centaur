# Project Centaur

Project Centaur is an autonomous trading research, shadow-learning, paper-execution, and promotion-gated control system.

It runs continuously, stores operational state in PostgreSQL, collects live market/account/risk data, runs real historical replay research from stored bars, evaluates strategy/profile evidence, updates internal research and promotion stages, and sends Slack attention alerts when Gary needs to approve or reject paper/live permission changes.

Centaur may advance internal evidence stages automatically. It must not auto-approve broker paper execution, must not auto-approve live execution, and must not silently remove paper/live permissions without manual review.

## Current Project Summary

Centaur is not just a paper bot and not just an offline backtester. The current system combines:

- unattended heartbeat supervision via `launchd`
- continuous market/account/risk observation
- deterministic signal generation and shadow learning
- real replay research over stored historical bars
- promotion-stage updates driven by evidence
- manual Slack attention workflows for execution permission changes

The practical question is still small and conservative:

> Can a tightly constrained system learn continuously, protect capital, and earn the right to paper or live execution through auditable evidence rather than assumption?

## Runtime Architecture

- `launchd` is the primary runtime supervisor.
- A cron kickstart/backstop path exists so the unattended agent can be re-kicked or monitored if needed.
- The supervised heartbeat service runs `main.py --heartbeat-service --interval-seconds 10`.
- Ticks are sequential and reload `.env` plus runtime storage each loop.
- PostgreSQL is required for operations storage. When PostgreSQL is configured, or paper/live execution is enabled, Centaur fails closed instead of silently falling back to SQLite.
- Slack is notification-only. The heartbeat can send hourly liveness messages and repeat unresolved attention alerts, but Slack is not a command surface.
- The autonomous research cycle runs on a 60-minute cadence when enabled.
- The real research path replays stored historical bars, writes evidence decisions, updates internal stages, and keeps broker paper/live safety gates closed unless a manual approval path is completed.

Useful service commands:

```bash
scripts/centaur-agent.sh status
scripts/centaur-agent.sh start
scripts/centaur-agent.sh stop
scripts/centaur-agent.sh restart
```

## Learning And Promotion Model

Centaur distinguishes between autonomous internal stages and manual execution stages.

Autonomous internal stages:

- `research_only`
- `promising_research`
- `paper_sim_candidate`
- `paper_sim_active`
- `paper_candidate`
- `paper_removal_candidate`
- `rejected`

Manual execution stages:

- `paper_approved`
- `live_approved`

Important rule:

- Centaur may move strategies through internal evidence stages automatically.
- Centaur must not add or remove broker paper or live execution permissions without manual approval through the Slack attention workflow.

## Proof Commands

```bash
python main.py --autopilot-proof
python main.py --real-learning-proof
python main.py --real-learning-proof --run-fresh
python main.py --historical-replay-coverage
python main.py --research-cycle-status
python main.py --research-proof-vs-real
python main.py --postgres-preflight
python main.py --attention-status
```

- `--autopilot-proof` is the synthetic safety harness. It proves the promotion and execution guardrails, not real learning from stored history.
- `--real-learning-proof` is the real stored historical replay evidence proof. It verifies that the unattended heartbeat used stored bars, wrote decisions, and kept paper/live auto-approval closed.

## Current Proven State

Latest real proof output:

```text
real_learning_proven=true
historical_windows_selected=8
profiles_with_replay=3
raw_decisions_count=18
evidence_decisions_count=18
promotion_eligible_count=0
broker_orders_created=0
live_orders_created=0
final_safety_summary=PASS
```

This means the real learning path is working and writing replay-backed evidence, but no strategy is currently promotion-eligible. Centaur is learning, not self-authorizing execution.

## Current Status

- Runtime: Python heartbeat/control pipeline
- Scheduler: macOS `launchd` heartbeat service, `10` second interval, sequential busy-skip behavior
- Research cadence: `60` minutes when `RESEARCH_CYCLE_ENABLED=true`
- Operations store: PostgreSQL
- Dashboard: DDEV/OrbStack web dashboard at `https://ghostfrog-centaur.ddev.site`
- Paper lanes: Alpaca Paper and eligible Trading 212 Paper equity lane
- Live lane: separate `LIVE_*`-dial lane that remains manual-gated and must not be inferred as active from documentation alone
- Trade size: `$10` paper notional by default
- Base paper slots: `10`
- Allowed paper strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, `momentum.volatility_breakout`
- Research/watch-only crypto strategy: `crypto_pullback.downside_reversal_watch` can emit research diagnostics and replay evidence, but it is not execution-approved
- Replay/reporting-only continuation interpretation: `crypto_pullback.downside_continuation_watch` remains research-only
- Replay/reporting-only extreme reversal segmentation: `crypto_pullback.extreme_drop_reversal_watch` remains research-only
- Paper exit capture: `1.25%`
- Shadow target ladder: `1.25%`, `2%`, `3%`, `4%`, `6%`

API keys alone must not activate live trading.

## Safety Rules

Read these before changing behavior:

- [AGENTS.md](AGENTS.md)
- [CONSTRAINTS.md](CONSTRAINTS.md)
- [DECISION_LOG.md](DECISION_LOG.md)
- [SKILL.md](SKILL.md)
- [PROGRESS.txt](PROGRESS.txt)

Important current constraints:

- No live auto-approval.
- No broker paper auto-approval.
- No auto removal from paper or live without Gary.
- No silent broker switch.
- No silent risk widening.
- No threshold changes without review.
- No secrets in logs or in this README.
- SQLite fallback is refused for live/paper operations when PostgreSQL is required.
- No paper trade above `$10` notional without explicit approval.
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
10. Apply fitness allocation and promotion-safe evidence rules.
11. Create shadow proposals.
12. Apply paper CFO/risk approval.
13. Submit Alpaca Paper orders.
14. Evaluate the live lane only if it has been intentionally enabled and manually approved; otherwise keep live mutation blocked.
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

### Fitness-only paper/live admission

Shadow learning still records raw scores and broad proposal evidence, but the
money-facing paper/live lanes now use fitness-only admission on the fast
execution path.

Raw `signal_score` remains useful for:

- ranking candidates
- research and reporting
- shadow evidence analysis

It no longer has authority to bypass fitness suppression into paper or live
execution unless a future reviewed policy explicitly re-enables that behavior.

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
- an equity position reaches the final same-day flatten window

For equities, Centaur is no-overnight-carry: new entries are blocked in the final 15 minutes of the equity session, and equity positions are flattened in the final 5 minutes regardless of red/green. Positions missing a managed entry plan use an audited unmanaged flatten instead of being allowed to drift overnight.

For `crypto_momentum.trend`, the current managed policy is `profit_capture_else_1d`: the `1.25%` capture, stop, and larger target stay active, but if none of them hit the position exits at the hard `1d` backstop.

For `mean_reversion.snapback`, profitable positions may exit after `1h`, while non-profitable positions can continue under stop/target protection until the same-day equity flatten window.

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
: Target heartbeat interval. The supervised `launchd` service currently runs at `10` seconds.

`CONTROL_MAX_TICK_RUNTIME_SECONDS`
: Expected maximum tick runtime before it should be treated as too slow.

`CONTROL_LOCK_NAME`
: Lock name used by the wrapper so scheduled ticks skip instead of stacking.

### Database and Cost

`OPERATIONS_DB_BACKEND`
: Live operations backend. Current repo truth is PostgreSQL; when PostgreSQL is configured, or paper/live execution is enabled, Centaur fails closed instead of falling back to SQLite.

`DATABASE_URL`
: PostgreSQL connection string.

`POSTGRES_SCHEMA`
: Optional PostgreSQL schema for operations tables. Leave unset for the current shared-schema runtime; set explicitly for future paper/live schema-separated deployments.

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

`PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT`, `LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT`
: Crypto-specific stop. Currently `0.01` for both lanes. Legacy `CRYPTO_MOMENTUM_STOP_LOSS_PCT` remains a fallback.

`PAPER_CRYPTO_MOMENTUM_TARGET_MULTIPLE`, `LIVE_CRYPTO_MOMENTUM_TARGET_MULTIPLE`
: Crypto-specific target multiple. Currently `2.0` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE`, `LIVE_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE`
: Minimum crypto momentum signal score. Currently `60.0` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT`, `LIVE_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT`
: Required positive crypto movement. Currently `0.15` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MAX_MOVEMENT_PCT`, `LIVE_CRYPTO_MOMENTUM_MAX_MOVEMENT_PCT`
: Maximum allowed positive crypto movement before the candidate is treated as a possible spike. Currently `2.5` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE`, `LIVE_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE`
: Discovery floor for crypto candidates. Currently `2.5` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MIN_TRADE_COUNT`, `LIVE_CRYPTO_MOMENTUM_MIN_TRADE_COUNT`
: Minimum trade count. Currently `2` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MIN_VOLUME_GBP`, `LIVE_CRYPTO_MOMENTUM_MIN_VOLUME_GBP`
: Minimum notional crypto candidate volume in GBP. Candidates can supply `volume_gbp`, or the strategy derives it from `close_price_gbp * volume`. Currently `50000` for both lanes.

`PAPER_CRYPTO_MOMENTUM_MAX_SPREAD_PCT`, `LIVE_CRYPTO_MOMENTUM_MAX_SPREAD_PCT`
: Maximum crypto spread percentage when spread data is available. Currently `0.25` for both lanes.

Live crypto momentum values default to the paper values. When live is armed, any live-vs-paper difference must be listed in `LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES`.

### Fitness Allocation

`STRATEGY_FITNESS_LOOKBACK_DAYS`
: Fitness lookback. `0` means all available history.

`STRATEGY_FITNESS_MIN_CHECKPOINTS`
: Minimum checkpoint count for fitness summary confidence.

`INCLUDE_BACKTEST_EVIDENCE_IN_PAPER_FITNESS`, `INCLUDE_BACKTEST_EVIDENCE_IN_LIVE_FITNESS`
: Replay/backtest evidence inclusion switches for allocation fitness. Both default to `false` so `backtest:simulator` evidence does not influence paper/live allocation unless explicitly enabled.

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
: Daily equity drawdown protector. Currently `$10.00` for paper.

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
: Legacy knob retained for compatibility. The fast paper/live execution path now uses fitness-only admission, so this no longer grants score-based trade authority.

`PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE`
: Legacy reporting/config knob for historical score-to-trade analysis.

`PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN`
: Legacy reporting/config knob for historical score-to-trade analysis.

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

`RESEARCH_CYCLE_ENABLED`
: Gate for unattended heartbeat research cycles. When `true`, the supervised heartbeat may run the replay-only research cycle on its normal 60-minute cadence without approving broker paper or live execution.

`RESEARCH_REPLAY_TIMEFRAME` / `RESEARCH_REPLAY_DAYS`
: Replay settings for `main.py --research-cycle`.

`RESEARCH_MAX_REPLAY_TIMESTAMPS`
: Per-window replay cap used by the research cycle.

`RESEARCH_MIN_WINDOWS` / `RESEARCH_MIN_PROPOSALS`
: Minimum bounded replay coverage before a strategy can move beyond `research_only`.

`RESEARCH_MIN_NET_RETURN_PCT` / `RESEARCH_MIN_NET_WIN_RATE`
: Recommendation thresholds for research-only promotion advice. They do not alter paper/live thresholds.

`RESEARCH_ALLOWED_STRATEGIES`
: Research-only strategy ids evaluated by the autonomous cycle. These remain non-executable until a separate manual promotion step approves them.

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

`SLACK_ALERTS_ENABLED` / `SLACK_WEBHOOK_URL`
: Optional one-way Slack incoming-webhook alerts for operator notifications. Slack must not be used as a live-trading command surface.

`SLACK_ALERT_DEDUPE_MINUTES` / `SLACK_REQUEST_TIMEOUT_SECONDS`
: Dedupe window and request timeout for Slack alerts. Notification events are persisted so the scheduler does not spam repeated tick-level warnings.

`SLACK_HOURLY_STATUS_ENABLED` / `SLACK_HOURLY_STATUS_INTERVAL_MINUTES`
: Sends a one-way hourly Slack liveness/status message from the normal control tick. If the message stops arriving, treat the scheduler/control loop as stale until proven healthy.

`SLACK_ATTENTION_REPEAT_ENABLED` / `SLACK_ATTENTION_REPEAT_MINUTES` / `SLACK_ATTENTION_MAX_REPEATS`
: Repeats unresolved attention-required Slack alerts from the heartbeat until acknowledged, resolved, rejected, expired, or manually approved/rejected where applicable. `SLACK_ATTENTION_MAX_REPEATS=0` means repeat forever.

`TEST_MONITOR_ENABLED`
: Enables the scheduled unit-test monitor. The monitor runs the test command, checks scheduler freshness, persists only a small JSON status file, and never mutates trading state.

`TEST_MONITOR_COMMAND`
: Optional override for the build/change test command. Leave blank to run `python -m unittest discover tests` with the monitor's Python.

`TEST_MONITOR_SLACK_ENABLED`
: Optional override for test monitor Slack alerts. Leave blank to inherit `SLACK_ALERTS_ENABLED`.

`TEST_MONITOR_REMINDER_MINUTES`
: Reminder cadence while the same test failure remains active and unacknowledged.

`TEST_MONITOR_STATE_PATH` / `TEST_MONITOR_LOG_PATH`
: JSON state and append-only log paths for scheduled test monitoring.

`TEST_MONITOR_SCHEDULER_FRESHNESS_ENABLED` / `TEST_MONITOR_SCHEDULER_MAX_AGE_MINUTES`
: Adds a cron/launchd working check to the scheduled test monitor. The monitor fails if the latest persisted control tick is missing, not `ok`, or older than the configured freshness limit.

For each build/change, run the unit suite:

```bash
.venv-mac/bin/python -m unittest discover tests
```

For the scheduled operational check, including the scheduler freshness test, run:

```bash
.venv-mac/bin/python scripts/run_test_monitor.py
```

To acknowledge the current failure fingerprint and stop reminders until tests change or recover:

```bash
scripts/run_test_monitor.py --reset-failure-notification
```

To install the macOS launchd monitor, run:

```bash
scripts/install_test_monitor_launch_agent.sh
```

For classic cron, use `ops/centaur_tests.cron` as the crontab line.

`LIVE_EQUITY_PDT_REVIEW_REMINDERS_ENABLED`
: When enabled, Slack sends an action-required reminder after the configured review date while the Alpaca Live equity PDT guard is still active. Turn this off only after reviewing live API/account behaviour and deciding what to do with equity entries.

`LIVE_EQUITY_PDT_REVIEW_REMINDER_START_DATE` / `LIVE_EQUITY_PDT_REVIEW_REMINDER_INTERVAL_MINUTES`
: Review reminder start date and repeat cadence. Defaults to `2026-06-04` and `30` minutes.

### Storage Lanes

`CORE_POSTGRES_SCHEMA`, `PAPER_POSTGRES_SCHEMA`, `LIVE_POSTGRES_SCHEMA`
: The intended core/paper/live PostgreSQL lane names. `core` is for shared reviewed evidence and strategy fitness; `paper` and `live` are execution/evidence lanes.

`POSTGRES_SCHEMA`
: Optional active runtime schema. When set for a deployment, it selects the current paper or live lane schema while the storage report still shows the full core/paper/live layout.

`scripts/bootstrap_storage_lanes.py`
: Initializes the configured PostgreSQL `core`, `paper`, and `live` schemas/tables before an operational cutover. It does not change the active scheduler lane by itself.

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
: Main live execution enable flag. Treat live as `safe_off` unless the explicit activation path has been completed and current runtime status confirms otherwise.

`LIVE_EXECUTION_KILL_SWITCH`
: Live kill switch. Keep it on unless live has been intentionally armed.

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

API keys plus `LIVE_EXECUTION_ENABLED=true` are not enough. Live execution
must remain a manually gated lane with its own `LIVE_*` dials, approvals,
checklists, and safety guards.

Do not infer live readiness from paper success.

Documentation must not claim live is active merely because historical approvals
or credentials exist. Use `main.py --status`, `main.py --attention-status`, and
the current runtime environment to determine whether live is `safe_off`,
`blocked`, or deliberately armed.

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

Run the evidence registry before deciding actions:

```bash
.venv-mac/bin/python main.py --evidence-report
```

Run historical replay:

```bash
.venv-mac/bin/python main.py --replay
```

Run one autonomous research cycle:

```bash
.venv-mac/bin/python main.py --research-cycle
```

Show the latest research-cycle decision report:

```bash
.venv-mac/bin/python main.py --research-status
```

Optional disabled-by-default scheduler examples for research-only automation:

```cron
# hourly
0 * * * * cd /Volumes/Bob/www/ghostfrog-centaur && .venv-mac/bin/python main.py --research-cycle

# daily
15 2 * * * cd /Volumes/Bob/www/ghostfrog-centaur && .venv-mac/bin/python main.py --research-cycle
```

Only enable an external scheduler after explicitly setting
`RESEARCH_CYCLE_ENABLED=true` in your environment and keeping the cycle on the
research-only command path. In the normal runtime, the `launchd` heartbeat is
already the primary scheduler, and the research cycle stays replay-only.

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

It reads through the routed PHP proxy:

```text
/api/snapshot.php
```

That endpoint proxies the live host dashboard API at `http://host.docker.internal:8788/api/snapshot`. The Python dashboard API is the source of truth; the DDEV web app no longer depends on a repo-local snapshot file bridge.

To run the host dashboard API directly:

```bash
.venv-mac/bin/python main.py --dashboard --host 0.0.0.0 --port 8788
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
- `/.runtime/` local SQLite fallback files
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
