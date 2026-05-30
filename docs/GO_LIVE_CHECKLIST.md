# Go Live Checklist

Use this checklist before any move from paper trading to real-money trading.

## Hard Rule
Current repo constraints say:

- No live-money trading outside the explicit 2026-05-29 Alpaca Live go-live override and its recorded same-as-paper micro envelope.
- Alpaca Live guarded entry, cancellation, and managed-exit plumbing must not be widened beyond that override without a separate explicit record.

That means Centaur may only run live inside the recorded first-live envelope unless there is another explicit human override and the repo constraints are intentionally changed.

## Purpose
- prevent an emotional jump from paper to live money
- force an auditable standard for "ready enough"
- keep capital preservation ahead of excitement

## Required Before Any Override
Every item below should be true before even considering a live-money override:

1. One strategy is clearly selected using `docs/STRATEGY_SELECTION_CHECKLIST.md`.
2. Paper execution is boring and reliable, not fragile.
3. No unresolved broker/order/accounting bugs remain.
4. Costs and slippage are included in the decision basis.
5. The operator understands what the system is doing.

## Suggested Readiness Standard
These are the working minimums for a first live-money discussion:

- several weeks of stable paper execution
- at least `10-20` clean paper entries/exits for the chosen strategy
- at least `500` replay outcomes for the chosen strategy
- no repeated unexplained divergence between Centaur and Alpaca state
- no unresolved alert that affects execution correctness
- current risk envelope still small and understandable

## Go-Live Questions
All of these need a confident answer:

1. Which exact strategy is going live first?
2. Why that one and not the others?
3. What is the kill switch?
4. What is the maximum loss we accept on day one?
5. What exact signal should make us stop live trading immediately?

## First Live Phase Rules
If a human override is granted, first live mode should still be extremely constrained. The generic default is:

- one strategy only
- preferably one or two live slots at first, even though the planned envelope is `10 x 10` currency-units
- smaller than the current paper ambition if needed
- same risk rules and same kill-switch mentality
- immediate rollback to paper on suspicious behavior

The 2026-05-29 operator-selected plan explicitly chooses the same-as-paper follower lane instead of the one-strategy default. That exception is acceptable only while the `$10` notional, `10` base slots, one-order-per-tick cap, same-tick submitted-paper-order follow rule, `$5.00` daily protector, and rollback triggers remain in force.

## Current Dormant Live Lane
Current May-readiness prep is:

- broker id: `alpaca_live`
- default status: disabled
- live kill switch: on
- planned maximum envelope: `10 x 10` Alpaca account-currency units
- readiness asset classes: equities and crypto, matching paper
- readiness strategy allowlist: `mean_reversion.snapback`, `crypto_momentum.trend`, and `momentum.volatility_breakout`, matching paper
- readiness entry economics: `$10` notional, one order per tick, `$5.00` daily drawdown protector, `1.5%` equity projected-gain floor, `2.0%` crypto projected-gain floor, `5` bps equity limit buffer, and `25` bps crypto limit buffer
- earned-slot rule: after live has its own baseline, each full `10` account-currency units of tracked P/L may add one effective `10` unit slot
- live entry submission: dormant unless all explicit go-live gates pass
- live cancellation/stale-order cleanup: implemented but guarded by live credentials plus activation acknowledgement
- live managed exits: prepared to refresh stale or non-marketable sell exits like paper once the live lane is deliberately activated
- API keys plus `LIVE_EXECUTION_ENABLED=true`: not enough to trade live
- live can only follow a same-tick paper-approved trade that paper execution actually submitted
- live execution intelligence: read-only live-vs-paper execution monitor; strategy fitness remains shared shadow fitness

This lets paper and live be designed as side-by-side lanes without allowing accidental real-money execution.

## Current Funded Readiness State
As of 2026-05-29, Alpaca Live API keys have been added locally, the initial funds are visible, and the read-only funded checks passed. This is still not go-live approval.

## Explicit Go-Live Override
On 2026-05-29 at about 10:48 BST, the operator explicitly instructed Codex to turn Alpaca Live on. This satisfies the human-override requirement for the previously recorded first-live same-as-paper follower plan.

Authorized activation:
- set `LIVE_EXECUTION_ENABLED=true`
- set `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`
- set `LIVE_EXECUTION_KILL_SWITCH=false`
- do not change notional, slot count, strategy allowlist, asset classes, daily protector, projected-gain floors, or limit buffers
- watch the first live tick manually

Final pre-activation check:
- Alpaca Live account status: `ACTIVE`
- trading blocked: `false`
- account blocked: `false`
- user trade suspended: `false`
- cash/equity/buying power: `132.05`
- live positions: `0`
- recent live orders: `0`
- open live orders: `0`
- live daily protection: `active`
- live daily-protection baseline equity: `132.05`
- live daily drawdown: `0.0`
- latest scheduler tick before activation: `OK`

First live-enabled tick observation:
- first fully live-enabled observed tick: `20260529-105313`
- tick status: `OK`
- `alpaca_live.sync`: `0` open positions, `0` open orders, equity `132.050`, cash `132.050`
- `risk.live_cfo`: `hold`
- live hold reason: `no_paper_approved_trade_to_follow`
- `execution.live`: `0` orders submitted, `0` orders saved, status `idle`
- post-activation read-only check: `0` live positions, `0` recent live orders, `0` open live orders

Current live controls:
- after activation, `LIVE_EXECUTION_ENABLED=true`
- after activation, `LIVE_EXECUTION_KILL_SWITCH=false`
- after activation, `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`
- keep paper trading and live-readiness monitoring running
- do not treat this approval as permission to widen any risk setting

Funded read-only check result on 2026-05-29:
- Alpaca Live credentials detected by config
- live account status: `ACTIVE`
- trading blocked: `false`
- account blocked: `false`
- user trade suspended: `false`
- cash/equity/buying power: `132.05`
- positions: `0`
- recent orders: `0`
- open orders: `0`
- live daily protection: `active`
- live daily-protection baseline equity: `132.05`
- Centaur live entry guard result: blocked with `live_execution_disabled`

## Recorded First-Live Plan
The operator-selected first-live policy is "same as paper" rather than one strategy only. This is intentionally recorded because the safer generic checklist default is one strategy first, but the requested launch shape is a same-as-paper follower lane.

First-live strategy policy:
- allow only the current paper execution strategies: `mean_reversion.snapback`, `crypto_momentum.trend`, and `momentum.volatility_breakout`
- do not add any strategy that is not already paper-allowed
- live may only follow a same-tick paper-approved trade that paper execution actually submitted
- strategy scoring remains shared paper/shadow fitness; live gets execution monitoring, not its own strategy brain

Day-one live limits:
- observed starting live account equity for readiness: `132.05`
- operating bankroll envelope: `$100`, not the full `132.05`
- base slots: `10`
- notional per entry: `$10`
- max orders per tick: `1`
- max daily live drawdown protector: `$5.00`
- asset classes: equities and crypto, matching paper
- equity projected-gain floor: `1.5%`
- crypto projected-gain floor: `2.0%`
- equity limit buffer: `5` bps
- crypto limit buffer: `25` bps
- direction: long-only entries, matching current paper behavior
- no duplicate live symbol position or open live order
- extra funded balance above `$100` is buffer only and does not create extra launch slots

Rollback triggers:
- any unexpected live position or live open order before activation
- any live account block, trading block, or user suspension
- any live order that does not correspond to a same-proposal submitted paper order
- any surprising live-vs-paper fill drift, status mismatch, reject, or partial-fill behavior
- any stale live order that cannot be canceled/refreshed by the guarded live path
- live daily drawdown reaches the configured `$5.00` protector
- account/equity numbers diverge from Alpaca or become unavailable
- the operator is unsure or uncomfortable with what happened

Rollback action:
- set `LIVE_EXECUTION_KILL_SWITCH=true`
- if needed, set `LIVE_EXECUTION_ENABLED=false`
- do not submit new live entries
- inspect and manage any live positions deliberately; after activation, guarded sell exits may still be used for protection
- record the rollback reason in this checklist, `CONSTRAINTS.md`, `DECISION_LOG.md`, `docs/DECISION_LOG.md`, `docs/PROJECT_RECORD.md`, and `PROGRESS.txt`

## Next Steps Before Activation
Before activating live entries, do this in order:

1. Re-run the read-only status/sync check immediately before activation and confirm Alpaca Live cash, equity, buying power, positions, and orders are still sane.
2. Confirm the live account has no unexpected positions and no unexpected open orders.
3. Confirm the live readiness envelope still matches the intended first phase: `$10` notional, one order per tick, `10` base slots, `$5.00` daily protector, same paper strategy allowlist, equities plus crypto, and the same projected-gain/limit-buffer settings. The `$132.05` balance does not widen the `$10 x 10` envelope.
4. Confirm the recorded first-live policy above still stands: same-as-paper follower lane, same paper strategy allowlist, and no independent live strategy scoring.
5. Run one final paper tick/status check and confirm paper execution is not showing unresolved broker, order, stale-exit, or accounting alerts.
6. Update this checklist, `CONSTRAINTS.md`, `DECISION_LOG.md`, `docs/DECISION_LOG.md`, `docs/PROJECT_RECORD.md`, and `PROGRESS.txt` with the explicit go-live override.
7. Only after that documentation exists, set `LIVE_EXECUTION_ENABLED=true`, set `LIVE_EXECUTION_ACTIVATION_ACK=LIVE_TRADING_APPROVED`, and clear `LIVE_EXECUTION_KILL_SWITCH=false`.
8. Watch the first live tick manually. If anything is surprising, turn the live kill switch back on and record the rollback.

Do not skip the read-only key test. Do not flip all live flags just because the account is approved.

## Things That Are Not Good Enough
- "it feels ready"
- one profitable paper trade
- one week of lucky results
- a strong replay score with weak execution evidence
- switching to live because the dashboard looks exciting

## Current Status
Current Centaur status is:

- paper active
- Alpaca Live explicitly approved for same-as-paper follower activation
- first-live same-as-paper policy, limits, and rollback rules recorded
- no risk widening beyond the `$10 x 10` / `$5.00` protector envelope

## Decision Record
If live trading is ever approved, record:

- date of override
- person approving the override
- chosen strategy
- starting live size
- kill-switch rule
- rollback conditions
