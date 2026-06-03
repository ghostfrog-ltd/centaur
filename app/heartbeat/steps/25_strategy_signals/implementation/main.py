"""Heartbeat step implementation owned by `25_strategy_signals`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    ThresholdAdvisor,
    TickContext,
    _paper_allocation_suppress_thresholds,
    allocate_strategy_signals,
    evaluate_strategies,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Generate current signals and apply fitness allocation.

    Deterministic strategy logic creates base signals first. Fitness then acts
    as a narrow allocation gate: it can weight, favor, suppress, or annotate a
    signal, but it does not invent trades or relax CFO/execution constraints.
    """
    candidates = context.state["context_enrichment"].get("candidates", [])
    if not candidates:
        result = {
            "strategy_families": 0,
            "profiles_tested": 0,
            "candidates_evaluated": 0,
            "signals_generated": 0,
            "mode": "skipped",
        }
        context.state["strategy_signals"] = {
            **result,
            "signals": [],
        }
        return result

    batch = evaluate_strategies(
        tick_id=context.tick_id,
        candidates=candidates,
        config=context.config,
        market_context={
            "market_gate": context.state["market_gate"],
            "account_equity": context.state["alpaca_account"]["summary"]["equity"],
        },
    )
    base_signal_dicts = [item.as_dict(tick_id=context.tick_id) for item in batch.signals]
    fitness_summaries = context.state.get("strategy_fitness", {}).get("summaries", [])
    # First pass: disable suppression so the adaptive threshold adviser can see
    # the current raw fitness cliff without mutating the signal set.
    _, preliminary_allocation_stats = allocate_strategy_signals(
        signals=base_signal_dicts,
        fitness_summaries=fitness_summaries,
        min_checkpoints=context.config.strategy_allocation_min_checkpoints,
        favor_threshold=context.config.strategy_allocation_favor_threshold,
        suppress_threshold=-999.0,
        asset_class_suppress_thresholds={"equity": -999.0, "crypto": -999.0},
    )
    threshold_state = ThresholdAdvisor(
        config=context.config,
        usage_ledger=context.usage_ledger,
    ).effective_threshold(
        tick_id=context.tick_id,
        now=context.started_at,
        current_signal_preview=preliminary_allocation_stats.get("raw_signals", []),
    )
    suppress_threshold = float(
        threshold_state.get(
            "effective_threshold",
            context.config.strategy_allocation_suppress_threshold,
        )
    )
    suppress_thresholds = _paper_allocation_suppress_thresholds(
        context,
        equity_threshold=suppress_threshold,
    )
    score_to_trade_threshold = (
        context.config.live_min_signal_score_to_trade
        if context.config.centaur_environment == "live"
        else context.config.paper_min_signal_score_to_trade
    )
    # Second pass: apply the actual thresholds used by allocation. A strategy
    # already approved for the active lane can survive fitness suppression only
    # when its raw setup score meets that lane's configured score-to-trade dial;
    # CFO/risk still enforces instrument, projected-gain, duplicate, capacity,
    # market, and drawdown gates before execution.
    signal_dicts, allocation_stats = allocate_strategy_signals(
        signals=base_signal_dicts,
        fitness_summaries=fitness_summaries,
        min_checkpoints=context.config.strategy_allocation_min_checkpoints,
        favor_threshold=context.config.strategy_allocation_favor_threshold,
        suppress_threshold=suppress_threshold,
        asset_class_suppress_thresholds=suppress_thresholds,
        high_score_override_enabled=(
            bool(context.config.paper_execution_enabled)
            and not bool(context.config.paper_execution_kill_switch)
        ),
        high_score_override_min_score=score_to_trade_threshold,
        high_score_override_fitness_margin=(
            context.config.paper_execution_high_score_override_fitness_margin
        ),
        high_score_override_allowed_strategies={
            strategy_id.lower()
            for strategy_id in context.config.paper_execution_allowed_strategies
            if strategy_id
        },
    )
    allocation_stats["suppress_threshold"] = suppress_threshold
    allocation_stats["suppress_thresholds"] = suppress_thresholds
    allocation_stats["threshold_adaptive"] = threshold_state
    context.usage_ledger.record_strategy_candidate_signals(
        tick_id=context.tick_id,
        signals=signal_dicts,
    )
    result = {
        "strategy_families": batch.family_count,
        "profiles_tested": batch.profile_count,
        "candidates_evaluated": len(candidates),
        "signals_generated": len(signal_dicts),
        "signals_suppressed": allocation_stats["suppressed"],
        "signals_high_score_overridden": allocation_stats["high_score_overrides"],
        "signals_favored": allocation_stats["favored"],
        "rejection_summary": batch.rejection_summary,
        "allocation_min_checkpoints": context.config.strategy_allocation_min_checkpoints,
        "allocation_suppress_threshold": suppress_threshold,
        "allocation_suppress_thresholds": suppress_thresholds,
        "threshold_adaptive": threshold_state,
        "mode": "fitness_weighted_rule_based",
    }
    raw_signal_preview = allocation_stats.get("raw_signals", [])
    suppressed_signal_preview = allocation_stats.get("suppressed_signals", [])
    if raw_signal_preview:
        result["raw_signal_preview"] = raw_signal_preview
    if suppressed_signal_preview:
        result["suppressed_signal_preview"] = suppressed_signal_preview
    if signal_dicts:
        result["top_symbol"] = signal_dicts[0]["symbol"]
        result["top_strategy"] = signal_dicts[0]["strategy_id"]
        result["top_score"] = signal_dicts[0]["signal_score"]
    context.state["strategy_signals"] = {
        **result,
        "signals": signal_dicts,
        "allocation": allocation_stats,
    }
    return result
