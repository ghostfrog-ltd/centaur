# Go Live Checklist

Use this checklist before any move from paper trading to real-money trading.

## Hard Rule
Current repo constraints say:

- `No live-money trading.`
- `Alpaca Live` is scaffold-only and cannot submit/cancel orders.

That means Centaur must remain paper-only unless there is an explicit human override and the repo constraints are intentionally changed.

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
If a human override is granted, first live mode should still be extremely constrained:

- one strategy only
- preferably one or two live slots at first, even though the planned envelope is `10 x 10` currency-units
- smaller than the current paper ambition if needed
- same risk rules and same kill-switch mentality
- immediate rollback to paper on suspicious behavior

## Current Dormant Live Lane
Current May-readiness prep is:

- broker id: `alpaca_live`
- default status: disabled
- live kill switch: on
- planned maximum envelope: `10 x 10` Alpaca account-currency units
- earned-slot rule: after live has its own baseline, each full `10` account-currency units of tracked P/L may add one effective `10` unit slot
- live strategy allowlist: empty
- live order submission: dormant unless all explicit go-live gates pass
- live order cancellation: blocked in code
- API keys alone: not enough to trade live
- live can only follow a same-tick paper-approved trade

This lets paper and live be designed as side-by-side lanes without allowing accidental real-money execution.

## Things That Are Not Good Enough
- "it feels ready"
- one profitable paper trade
- one week of lucky results
- a strong replay score with weak execution evidence
- switching to live because the dashboard looks exciting

## Current Status
Current Centaur status is:

- paper only
- Alpaca Live scaffold visible but safe-off
- not cleared for live-money trading
- strategy selection is still evidence-building, not final

## Decision Record
If live trading is ever approved, record:

- date of override
- person approving the override
- chosen strategy
- starting live size
- kill-switch rule
- rollback conditions
