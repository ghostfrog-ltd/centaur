# Strategy Selection Checklist

Use this checklist to decide which strategy, if any, should be treated as Centaur's current lead candidate.

This is not the same as approving live-money trading.

## Purpose
- pick the strongest strategy based on evidence
- avoid choosing based on one lucky week or one sparse live paper trade
- keep strategy selection deterministic and auditable

## Current Rule
- live paper frequency alone is not enough to choose a strategy
- historical replay and shadow outcomes must carry most of the evidence
- live paper is mainly for broker/execution validation, not primary strategy discovery

## Minimum Selection Standard
All of these should be true before calling a strategy the current lead candidate:

1. The strategy has positive fitness after configured spread/slippage realism.
2. The strategy is still positive across more than one checkpoint window where applicable.
3. The evidence is not tiny.
4. The strategy can be explained simply.
5. The strategy does not depend on breaking any repo constraint.

## Suggested Evidence Thresholds
These are the working guide rails for selection:

- at least `500` replay outcomes for the strategy family/profile being considered
- at least `50` shadow or live-paper proposals for the same strategy when feasible
- evidence across more than one date range or market regime
- no unresolved execution or accounting bug that would make the score misleading

## Ranking Questions
Before selecting a strategy, answer these clearly:

1. Is it top because of real score quality, not just a tiny sample?
2. Is the score still acceptable after friction assumptions?
3. Is the sample broad, moderate, early, or small?
4. Is the latest result driven by one checkpoint only, or does it hold up more broadly?
5. Can we explain why it wins in plain English?

## Things That Do Not Count As Enough
- one good paper trade
- one good day
- one exciting screenshot
- replay results without friction
- positive score on fewer than `20` evaluated outcomes

## Current Practical Reading
As of this checklist being written:

- `momentum.volatility_breakout` can be the top-ranked fitness row while still having a small sample
- `mean_reversion.snapback` currently has much broader evidence and is the only strategy approved for paper execution
- a strategy can be the current leader without being ready for paper promotion

## Output Format
When naming a lead strategy, record:

- strategy id
- checkpoint used for the ranking
- composite fitness score
- sample size
- evidence label: `small`, `early`, `moderate`, or `broad`
- plain-English reason it is currently on top
- whether it is approved for paper execution

## Current Recommendation
- use this checklist to decide the current lead strategy
- do not use this checklist alone to decide live-money trading
