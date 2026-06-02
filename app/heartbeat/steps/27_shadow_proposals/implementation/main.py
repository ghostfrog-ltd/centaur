"""Heartbeat step implementation owned by `27_shadow_proposals`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    build_shadow_proposals,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `shadow.proposals` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    if not context.config.shadow_enabled:
        result = {
            "strategy_signals": 0,
            "proposals_created": 0,
            "mode": "disabled",
        }
        context.state["shadow_trade_proposals"] = {
            **result,
            "proposals": [],
        }
        return result

    strategy_state = context.state.get("strategy_signals", {})
    signals = strategy_state.get("signals", [])
    if not signals:
        result = {
            "strategy_signals": 0,
            "proposals_created": 0,
            "mode": "skipped",
        }
        context.state["shadow_trade_proposals"] = {
            **result,
            "proposals": [],
        }
        return result

    recent_strategy_keys = context.usage_ledger.list_recent_shadow_proposal_keys(
        since=context.started_at
        - timedelta(minutes=context.config.shadow_proposal_cooldown_minutes)
    )
    proposals = build_shadow_proposals(
        tick_id=context.tick_id,
        proposed_at=context.started_at,
        strategy_signals=signals,
        recent_strategy_keys=recent_strategy_keys,
        proposal_limit=context.config.shadow_proposal_limit,
        min_signal_score=context.config.shadow_min_opportunity_score,
        checkpoint_windows=context.config.shadow_checkpoint_windows,
    )
    for proposal in proposals:
        proposal.setdefault("environment", context.config.centaur_environment)
        proposal.setdefault("mode", context.config.centaur_mode)
        proposal.setdefault("source_environment", "shadow")
        proposal.setdefault("data_provider", proposal.get("source", "alpaca"))
        proposal.setdefault("execution_provider", "shadow")
    context.usage_ledger.record_shadow_trade_proposals(proposals=proposals)

    result = {
        "strategy_signals": len(signals),
        "proposals_created": len(proposals),
        "cooldown_minutes": context.config.shadow_proposal_cooldown_minutes,
        "score_threshold": context.config.shadow_min_opportunity_score,
        "mode": "created" if proposals else "idle",
    }
    if proposals:
        result["top_symbol"] = proposals[0]["symbol"]
        result["top_strategy"] = proposals[0]["strategy_id"]
        result["holding_window"] = proposals[0]["holding_window_code"]
    context.state["shadow_trade_proposals"] = {
        **result,
        "proposals": proposals,
    }
    return result
