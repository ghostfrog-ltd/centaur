"""Heartbeat step implementation owned by `32_evaluation_post_trade`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _build_tick_blocker_summary,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `evaluation.post_trade` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    orders_submitted = context.state["execution"]["orders_submitted"]
    shadow_outcomes = context.state.get("shadow_trade_outcomes", {})
    shadow_proposals = context.state.get("shadow_trade_proposals", {})
    strategy_state = context.state.get("strategy_signals", {})
    strategy_fitness_state = context.state.get("strategy_fitness", {})
    result = {
        "trades_reviewed": orders_submitted,
        "fitness_inputs": shadow_outcomes.get("checkpoints_evaluated", 0),
        "memory_updates": shadow_outcomes.get("checkpoints_evaluated", 0),
        "strategy_signals_generated": strategy_state.get("signals_generated", 0),
        "shadow_proposals_created": shadow_proposals.get("proposals_created", 0),
        "shadow_outcomes_evaluated": shadow_outcomes.get("checkpoints_evaluated", 0),
        "average_fitness_score": shadow_outcomes.get("average_fitness_score", 0.0),
        "strategy_scorecards": strategy_fitness_state.get("strategy_summaries", 0),
        "top_strategy": strategy_fitness_state.get("top_strategy", ""),
        "top_composite_fitness_score": strategy_fitness_state.get(
            "top_composite_score",
            0.0,
        ),
        "paper_execution_status": context.state["execution"].get("execution_status", "idle"),
    }
    context.state["tick_blockers"] = _build_tick_blocker_summary(context)
    context.state["post_trade_evaluation"] = result
    return result
