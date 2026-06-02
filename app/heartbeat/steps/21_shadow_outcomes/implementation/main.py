"""Heartbeat step implementation owned by `21_shadow_outcomes`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    PipelineResult,
    TickContext,
    evaluate_shadow_checkpoint,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Evaluate due shadow checkpoints and persist risk-adjusted outcomes.

    Shadow outcomes are evidence, not trades. They replay later bars against
    prior watch-only proposals, apply the configured friction model, and store
    per-checkpoint fitness scores for the next `strategy_fitness` step.
    """
    if not context.config.shadow_enabled:
        result = {
            "checkpoints_due": 0,
            "checkpoints_evaluated": 0,
            "mode": "disabled",
        }
        context.state["shadow_trade_outcomes"] = {
            **result,
            "outcomes": [],
        }
        return result

    due_checkpoints = context.usage_ledger.list_due_shadow_trade_outcomes(
        as_of=context.started_at,
    )
    outcomes: list[dict[str, Any]] = []
    bars_loaded = 0

    for checkpoint in due_checkpoints:
        proposed_at = checkpoint.get("proposed_at")
        if proposed_at is None:
            continue
        bars = context.usage_ledger.get_market_bars_for_window(
            source=str(checkpoint["source"]),
            symbol=str(checkpoint["symbol"]),
            start_at=proposed_at,
            end_at=context.started_at,
        )
        bars_loaded += len(bars)
        # This is the only point in the live tick where due shadow checkpoints
        # become scored fitness evidence.
        outcome = evaluate_shadow_checkpoint(
            checkpoint=checkpoint,
            bars=bars,
            as_of=context.started_at,
            execution_spread_bps=context.config.shadow_execution_spread_bps,
            entry_slippage_bps=context.config.shadow_entry_slippage_bps,
            exit_slippage_bps=context.config.shadow_exit_slippage_bps,
            fixed_round_trip_cost_usd=context.config.shadow_fixed_round_trip_cost_usd,
            reference_notional_usd=context.config.paper_execution_default_notional_usd,
            profit_target_ladder_pct=context.config.shadow_profit_target_ladder_pct,
        )
        if outcome is not None:
            outcomes.append(outcome)

    checkpoints_evaluated = context.usage_ledger.record_shadow_trade_outcomes(
        outcomes=outcomes,
    )
    average_fitness = (
        round(
            sum(float(item["fitness_score"]) for item in outcomes) / len(outcomes),
            6,
        )
        if outcomes
        else 0.0
    )
    result = {
        "checkpoints_due": len(due_checkpoints),
        "checkpoints_evaluated": checkpoints_evaluated,
        "waiting_for_future_bars": max(0, len(due_checkpoints) - checkpoints_evaluated),
        "bars_loaded": bars_loaded,
        "average_fitness_score": average_fitness,
        "mode": "evaluated" if due_checkpoints else "idle",
    }
    context.state["shadow_trade_outcomes"] = {
        **result,
        "outcomes": outcomes,
    }
    return result
