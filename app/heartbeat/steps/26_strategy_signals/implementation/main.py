"""Heartbeat step implementation owned by `26_strategy_signals`."""

from __future__ import annotations

from app.framework.engine.threshold_advisor_worker import request_threshold_advisor_update
from app.heartbeat.support import (
    PipelineResult,
    ThresholdAdvisor,
    TickContext,
    _as_float,
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
        excluded_by_asset_class = _excluded_by_asset_class(
            context.state.get("market_scan", {}).get("excluded_candidates", [])
        )
        rejection_summary = {
            "total_rejections": 0,
            "by_strategy_reason": [],
            "samples": [],
        }
        if int(excluded_by_asset_class.get("equity", 0) or 0) > 0:
            rejection_summary = {
                "total_rejections": 1,
                "by_strategy_reason": [
                    {
                        "strategy_id": "equity",
                        "reason": "strategy.skipped_no_fresh_market_data",
                        "count": 1,
                    }
                ],
                "samples": [
                    {
                        "strategy_id": "equity",
                        "profile_id": "",
                        "reason": "strategy.skipped_no_fresh_market_data",
                        "symbol": "",
                        "asset_class": "equity",
                        "canonical_instrument_id": "",
                        "metrics": {"excluded_candidates": excluded_by_asset_class.get("equity", 0)},
                    }
                ],
            }
        result = {
            "strategy_families": 0,
            "profiles_tested": 0,
            "candidates_evaluated": 0,
            "signals_generated": 0,
            "mode": "skipped",
            "rejection_summary": rejection_summary,
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
            "market_data_source_used_for_strategy": context.state.get("market_scan", {})
            .get("result", {})
            .get("market_data_source_used_for_strategy", {}),
            "candidates_excluded_due_to_stale_source_by_asset_class": _excluded_by_asset_class(
                context.state.get("market_scan", {}).get("excluded_candidates", [])
            ),
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
    threshold_state = _fast_tick_threshold_state(context)
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
    is_live_lane = context.config.centaur_environment == "live"
    if is_live_lane:
        score_to_trade_threshold = context.config.live_min_signal_score_to_trade
        score_to_trade_fitness_margin = (
            context.config.live_execution_high_score_override_fitness_margin
        )
    else:
        score_to_trade_threshold = context.config.paper_min_signal_score_to_trade
        score_to_trade_fitness_margin = (
            context.config.paper_execution_high_score_override_fitness_margin
        )
    # Second pass: apply the actual thresholds used by allocation. Paper and
    # live now use fitness-only admission into the money-facing lanes, so the
    # score-to-trade override remains a reportable concept but has no authority
    # to bypass suppression on the fast execution path.
    signal_dicts, allocation_stats = allocate_strategy_signals(
        signals=base_signal_dicts,
        fitness_summaries=fitness_summaries,
        min_checkpoints=context.config.strategy_allocation_min_checkpoints,
        favor_threshold=context.config.strategy_allocation_favor_threshold,
        suppress_threshold=suppress_threshold,
        asset_class_suppress_thresholds=suppress_thresholds,
        high_score_override_enabled=False,
        high_score_override_min_score=score_to_trade_threshold,
        high_score_override_fitness_margin=score_to_trade_fitness_margin,
        high_score_override_allowed_strategies=set(),
    )
    allocation_stats["suppress_threshold"] = suppress_threshold
    allocation_stats["suppress_thresholds"] = suppress_thresholds
    allocation_stats["threshold_adaptive"] = threshold_state
    context.usage_ledger.record_strategy_candidate_signals(
        tick_id=context.tick_id,
        signals=signal_dicts,
    )
    threshold_worker = request_threshold_advisor_update(
        tick_id=context.tick_id,
        requested_at=context.started_at,
        current_signal_preview=allocation_stats.get("raw_signals", []),
        enabled=bool(
            getattr(context.config, "strategy_threshold_adaptive_enabled", False)
        ),
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
        "threshold_advisor_worker": threshold_worker,
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


def _excluded_by_asset_class(candidates: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        asset_class = str(candidate.get("asset_class", "")).strip().lower()
        if not asset_class:
            continue
        counts[asset_class] = counts.get(asset_class, 0) + 1
    return counts


def _fast_tick_threshold_state(context: TickContext) -> dict[str, object]:
    """Use cached adaptive threshold state without running GA in the hot path.

    The GA adviser scans recent tick history and is too expensive for the
    30-second trading heartbeat. The fast tick may use an already persisted
    adaptive threshold, but it must not spend the live/paper decision loop
    recomputing threshold advice.
    """

    base_threshold = float(context.config.strategy_allocation_suppress_threshold)
    enabled = bool(getattr(context.config, "strategy_threshold_adaptive_enabled", False))
    state = context.usage_ledger.get_strategy_threshold_adaptive_state() if enabled else None
    state_threshold = _as_float((state or {}).get("effective_threshold"))
    effective = state_threshold if state_threshold is not None else base_threshold
    updated_at = (state or {}).get("updated_at")
    return {
        "enabled": enabled,
        "mode": "fast_tick_cached_adaptive_state" if enabled else "fixed_config",
        "base_threshold": base_threshold,
        "effective_threshold": effective,
        "previous_threshold": effective,
        "applied": False,
        "source_tick_id": context.tick_id,
        "cached_source_tick_id": (state or {}).get("source_tick_id"),
        "cached_updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "advice_status": "cached_state" if state_threshold is not None else "config_fallback",
        "reason": (
            "Fast tick uses cached adaptive threshold state; heavy GA advice is "
            "kept out of the trading heartbeat."
            if state_threshold is not None
            else "Fast tick found no cached adaptive threshold; using configured threshold."
        ),
    }
