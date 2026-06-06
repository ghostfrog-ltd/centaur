# Project Centaur $50/Day Scaling Plan

Last updated: 2026-05-31

## Goal

Project Centaur's strategic growth target is to reach a sustained, evidence-backed net profit pace of `$50/day` while preserving capital and obeying all current risk constraints.

This target is not permission to widen risk. It does not change the `$10` per-trade notional, broker routing, strategy allowlists, projected-gain floors, daily protection, live gates, or managed exits without explicit human approval and matching reliability-stack updates.

## Current Observed State

Current closed Alpaca Paper round-trip metrics from the dashboard snapshot:

- Closed paper trades: `203`
- Wins: `113`
- Losses: `90`
- Win rate: `55.66%`
- Loss rate: `44.34%`
- Average winning trade: `+2.15%`
- Average losing trade: `-1.26%`
- Average net return per closed `$10` trade: about `+0.637%`, or about `$0.064`
- Observed closed trades per elapsed day: about `3.15`
- Current tracked paper P/L: `$12.32`

The current projection near `$82/year` is therefore not a failure of arithmetic; it is the result of a small positive edge applied to a very small `$10 x 10` operating envelope and modest trade throughput.

## Scale Math

At the current average net return:

- `$50/day / $0.064 per closed $10 trade = about 785 closed $10 trades/day`
- With `500` slots and one close per slot/day, the current edge would imply about `$31.80/day`
- At `500` slots, reaching `$50/day` requires average net expectancy closer to `1.0%` per closed trade, or more than one effective slot turn per day
- At current throughput patterns, reaching `$50/day` would require roughly `2,500` base slots, or about a `$25,000` operating envelope at `$10/slot`

The practical path is therefore not one lever. It requires:

1. More valid trades per day.
2. Higher net expectancy per closed trade.
3. Staged, evidence-backed slot/capital scaling.

## Required Work

### 1. Improve Throughput Before Size

Current status often shows `no_shadow_proposals` and `no_raw_signals`, even when crypto discovery finds candidates. This means the machine is frequently not finding trades that survive the strategy and risk pipeline.

Recommended actions:

- Run `main.py --crypto-health` regularly to diagnose overnight crypto visibility.
- Investigate ticks where dynamic discovery selected crypto candidates but no raw strategy signals were generated.
- Expand replay/evidence for allowed strategies before changing execution policy.
- Consider broader candidate universes only if they preserve the `$10` risk model and existing broker/risk gates.
- Avoid loosening thresholds blindly; use `main.py --threshold-advice` and the evidence report first.

### 2. Improve Expectancy Toward 1.0% Net

Current expectancy is approximately:

```text
55.66% x 2.15% wins - 44.34% x 1.26% losses = about +0.64% per closed trade
```

At `500` slots, a `1.0%` net return per closed `$10` trade with one close per slot/day would be near the `$50/day` target:

```text
500 x $10 x 1.0% = $50/day
```

Recommended actions:

- Reduce average losing trade below `1.26%`.
- Improve win rate above `55.66%`.
- Preserve the useful part of larger winners without letting small winners fade into losses.
- Use the profit-target ladder evidence before changing profit-capture or take-profit settings.
- Review actual paper exits against `15m`, `1h`, `1d`, and `7d` shadow outcomes before changing managed exits.

### 3. Fix Exit/Data Reliability Before Scaling

Latest status has shown open positions with `latest_bar_unavailable` exit skips. That must be treated as a scaling blocker.

Recommended actions:

- Diagnose why latest bars are unavailable for managed exits.
- Keep stale-order and managed-exit refresh paths healthy before adding slots.
- Review `max_hold_red_deferred`, `friday_no_weekend_carry`, and trailing drawdown observer evidence before promoting any new active exit rule.

### 4. Use A Promotion Ladder

Do not jump from `10` base slots to hundreds of slots.

Suggested staged ladder:

```text
10 slots   -> current envelope
25 slots   -> after data freshness and exit checks are clean
50 slots   -> after 500+ closed paper trades with positive expectancy
100 slots  -> after drawdown observer remains clean and throughput can use capacity
250 slots  -> after repeated positive months and no hidden exit/data defects
500 slots  -> only after throughput and expectancy show a realistic path toward $50/day
```

Each stage should require:

- Positive realized expectancy.
- No breach of the daily drawdown protector.
- Clean managed-exit and stale-order behavior.
- Enough proposals to use the extra capacity.
- No widening of per-trade notional.
- Updated reliability-stack files and explicit human approval before any execution envelope change.

## Operating Rule

The `$50/day` target must guide prioritization, reporting, and research, but it must not override capital preservation. Strategy fitness remains invalid if it depends on breaking risk rules.
