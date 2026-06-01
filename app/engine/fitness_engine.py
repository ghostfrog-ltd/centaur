"""Strategy-fitness summarization and signal allocation.

This module is the second half of Centaur's strategy-fitness loop. It does not
look at raw bars directly; storage has already joined shadow proposals to their
evaluated outcomes. The flow is:

1. `enrich_strategy_fitness_rows` turns raw aggregate rows into ranked,
   sample-weighted fitness summaries.
2. `allocate_strategy_signals` joins those summaries back onto current signals
   and decides whether each signal is unproven, weighted, favored, suppressed,
   or admitted by the paper-only high-score near-miss override.

The thresholds in this file are capital-preservation gates. A comment/docstring
change is safe, but logic, weights, or comparison changes alter execution
eligibility and need explicit review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def enrich_strategy_fitness_rows(
    *,
    rows: list[dict[str, Any]],
    min_checkpoints: int,
) -> list[dict[str, Any]]:
    """Build ranked strategy fitness summaries from aggregate outcome rows.

    Input rows come from `UsageLedger.list_strategy_fitness_rows`, grouped by
    strategy, asset class, and checkpoint window. Rows below the minimum sample
    count are ignored so tiny samples cannot favor or suppress current trades.
    """
    enriched: list[dict[str, Any]] = []
    threshold = max(1, min_checkpoints)

    for row in rows:
        checkpoints_evaluated = int(row.get("checkpoints_evaluated", 0) or 0)
        if checkpoints_evaluated < threshold:
            continue

        wins = int(row.get("win_count", 0) or 0)
        losses = int(row.get("loss_count", 0) or 0)
        target_hits = int(row.get("target_hit_count", 0) or 0)
        stop_hits = int(row.get("stop_hit_count", 0) or 0)
        time_exits = int(row.get("time_exit_count", 0) or 0)
        ambiguous = int(row.get("ambiguous_count", 0) or 0)
        avg_fitness = _round(row.get("avg_fitness_score"))
        avg_return = _round(row.get("avg_realized_return_pct"))
        avg_mfe = _round(row.get("avg_max_favorable_excursion_pct"))
        avg_mae = _round(row.get("avg_max_adverse_excursion_pct"))
        avg_signal_score = _round(row.get("avg_signal_score"))
        avg_signal_confidence = _round(row.get("avg_signal_confidence"))
        avg_discovery_score = _round(row.get("avg_discovery_score"))

        win_rate = round(wins / checkpoints_evaluated, 6)
        loss_rate = round(losses / checkpoints_evaluated, 6)
        target_hit_rate = round(target_hits / checkpoints_evaluated, 6)
        stop_hit_rate = round(stop_hits / checkpoints_evaluated, 6)
        time_exit_rate = round(time_exits / checkpoints_evaluated, 6)
        ambiguous_rate = round(ambiguous / checkpoints_evaluated, 6)
        # Sample weight ramps up linearly until 12 checkpoints. This damps
        # early evidence instead of letting a handful of wins/losses dominate.
        sample_weight = round(min(1.0, checkpoints_evaluated / 12.0), 6)
        composite_score = _compute_composite_score(
            avg_fitness_score=avg_fitness,
            avg_realized_return_pct=avg_return,
            win_rate=win_rate,
            sample_weight=sample_weight,
        )

        enriched.append(
            {
                "strategy_id": str(row.get("strategy_id", "")),
                "environment": str(row.get("environment", "paper") or "paper"),
                "mode": str(row.get("mode", "paper") or "paper"),
                "source_environment": str(
                    row.get("source_environment", "shadow") or "shadow"
                ),
                "broker_id": str(row.get("broker_id", "") or ""),
                "data_provider": str(row.get("data_provider", "alpaca") or "alpaca"),
                "execution_provider": str(
                    row.get("execution_provider", "shadow") or "shadow"
                ),
                "strategy_family": str(row.get("strategy_family", "")),
                "profile_id": str(row.get("profile_id", "")),
                "asset_class": str(row.get("asset_class", "")),
                "checkpoint_code": str(row.get("checkpoint_code", "")).lower(),
                "lookback_days": int(row.get("lookback_days", 0) or 0),
                "evaluated_proposals": int(row.get("evaluated_proposals", 0) or 0),
                "checkpoints_evaluated": checkpoints_evaluated,
                "win_count": wins,
                "loss_count": losses,
                "target_hit_count": target_hits,
                "stop_hit_count": stop_hits,
                "time_exit_count": time_exits,
                "ambiguous_count": ambiguous,
                "win_rate": win_rate,
                "loss_rate": loss_rate,
                "target_hit_rate": target_hit_rate,
                "stop_hit_rate": stop_hit_rate,
                "time_exit_rate": time_exit_rate,
                "ambiguous_rate": ambiguous_rate,
                "avg_fitness_score": avg_fitness,
                "avg_realized_return_pct": avg_return,
                "avg_max_favorable_excursion_pct": avg_mfe,
                "avg_max_adverse_excursion_pct": avg_mae,
                "avg_signal_score": avg_signal_score,
                "avg_signal_confidence": avg_signal_confidence,
                "avg_discovery_score": avg_discovery_score,
                "sample_weight": sample_weight,
                "composite_fitness_score": composite_score,
                "first_proposed_at": _normalize_datetime(row.get("first_proposed_at")),
                "last_evaluated_at": _normalize_datetime(row.get("last_evaluated_at")),
            }
        )

    enriched.sort(
        key=lambda item: (
            float(item.get("composite_fitness_score", 0) or 0),
            float(item.get("avg_fitness_score", 0) or 0),
            int(item.get("checkpoints_evaluated", 0) or 0),
            str(item.get("strategy_id", "")),
        ),
        reverse=True,
    )
    for index, item in enumerate(enriched, start=1):
        item["fitness_rank"] = index
    return enriched


def allocate_strategy_signals(
    *,
    signals: list[dict[str, Any]],
    fitness_summaries: list[dict[str, Any]],
    min_checkpoints: int,
    favor_threshold: float,
    suppress_threshold: float,
    asset_class_suppress_thresholds: dict[str, float] | None = None,
    high_score_override_enabled: bool = False,
    high_score_override_min_score: float = 90.0,
    high_score_override_fitness_margin: float = 0.25,
    high_score_override_allowed_strategies: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply historical fitness to current strategy signals.

    The allocator is a gate, not a strategy generator. It never creates new
    opportunities; it only annotates, boosts, or removes signals that already
    passed deterministic strategy logic. Suppressed signals are kept in the
    diagnostics so the dashboard can explain quiet ticks.
    """
    summary_index = {
        (
            str(item.get("strategy_id", "")),
            str(item.get("asset_class", "")),
            str(item.get("checkpoint_code", "")).lower(),
        ): item
        for item in fitness_summaries
    }
    threshold = max(1, min_checkpoints)
    allocated: list[dict[str, Any]] = []
    stats = {
        "signals_in": len(signals),
        "signals_out": 0,
        "favored": 0,
        "weighted": 0,
        "suppressed": 0,
        "high_score_overrides": 0,
        "unproven": 0,
        "raw_signals": [],
        "suppressed_signals": [],
        "suppress_thresholds": {},
    }
    override_allowed_strategies = {
        str(strategy_id).strip().lower()
        for strategy_id in (high_score_override_allowed_strategies or set())
        if str(strategy_id).strip()
    }
    if asset_class_suppress_thresholds:
        stats["suppress_thresholds"] = {
            str(key).strip().lower(): float(value)
            for key, value in asset_class_suppress_thresholds.items()
        }

    for signal in signals:
        signal_copy = dict(signal)
        strategy_id = str(signal_copy.get("strategy_id", ""))
        asset_class = str(signal_copy.get("asset_class", "")).strip().lower()
        checkpoint_code = str(signal_copy.get("holding_window_code", "")).lower()
        # Fitness is checkpoint-specific: a strategy can be fit for one holding
        # window and weak for another, so match on the signal's intended window.
        summary = summary_index.get((strategy_id, asset_class, checkpoint_code))
        threshold_used = _resolve_suppress_threshold(
            default_threshold=suppress_threshold,
            asset_class=asset_class,
            asset_class_suppress_thresholds=asset_class_suppress_thresholds,
        )

        base_score = float(signal_copy.get("signal_score", 0) or 0)
        adjusted_score = base_score
        allocation_status = "unproven"
        composite_score: float | None = None
        sample_weight: float | None = None
        checkpoints_evaluated = 0

        if summary is None:
            stats["unproven"] += 1
        else:
            composite_score = float(summary.get("composite_fitness_score", 0) or 0)
            sample_weight = float(summary.get("sample_weight", 0) or 0)
            checkpoints_evaluated = int(summary.get("checkpoints_evaluated", 0) or 0)

            if checkpoints_evaluated < threshold:
                stats["unproven"] += 1
            else:
                # Positive composite fitness nudges ranking up; negative
                # composite fitness nudges it down. The helper caps the bonus
                # tightly so fitness cannot overwhelm the raw setup score.
                score_bonus = _allocation_bonus(
                    composite_fitness_score=composite_score,
                    sample_weight=sample_weight,
                )
                adjusted_score = round(base_score + score_bonus, 6)

                # Suppression is the capital-preservation side of fitness.
                # Asset classes may have separate thresholds, but live still
                # follows the shared paper/shadow strategy-fitness evidence.
                if composite_score <= threshold_used:
                    override_allowed = (
                        high_score_override_enabled
                        and strategy_id.strip().lower() in override_allowed_strategies
                        and base_score >= high_score_override_min_score
                        and composite_score
                        >= threshold_used - max(0.0, high_score_override_fitness_margin)
                    )
                    if override_allowed:
                        allocation_status = "high_score_override"
                        stats["high_score_overrides"] += 1
                    else:
                        allocation_status = "suppressed"
                        stats["suppressed"] += 1
                        signal_copy.update(
                            {
                                "base_signal_score": round(base_score, 6),
                                "signal_score": adjusted_score,
                                "allocation_status": allocation_status,
                                "fitness_composite_score": round(composite_score, 6),
                                "fitness_sample_weight": round(sample_weight, 6),
                                "fitness_checkpoints_evaluated": checkpoints_evaluated,
                                "suppress_threshold_used": round(threshold_used, 6),
                                "allocation_note": (
                                    f"Suppressed by shadow fitness: composite {composite_score:.3f} "
                                    f"vs threshold {threshold_used:.3f} over {checkpoints_evaluated} checkpoints."
                                ),
                            }
                        )
                        _append_signal_diagnostic(stats["raw_signals"], signal_copy)
                        _append_signal_diagnostic(stats["suppressed_signals"], signal_copy)
                        continue

                elif composite_score >= favor_threshold:
                    allocation_status = "favored"
                    stats["favored"] += 1
                else:
                    allocation_status = "weighted"
                    stats["weighted"] += 1

        signal_copy.update(
            {
                "base_signal_score": round(base_score, 6),
                "signal_score": adjusted_score,
                "allocation_status": allocation_status,
                "fitness_composite_score": (
                    round(composite_score, 6) if composite_score is not None else None
                ),
                "fitness_sample_weight": (
                    round(sample_weight, 6) if sample_weight is not None else None
                ),
                "fitness_checkpoints_evaluated": checkpoints_evaluated,
                "suppress_threshold_used": round(threshold_used, 6),
                "allocation_note": _allocation_note(
                    allocation_status=allocation_status,
                    composite_score=composite_score,
                    checkpoints_evaluated=checkpoints_evaluated,
                    suppress_threshold=threshold_used,
                    high_score_override_min_score=high_score_override_min_score,
                    high_score_override_fitness_margin=high_score_override_fitness_margin,
                ),
            }
        )
        _append_signal_diagnostic(stats["raw_signals"], signal_copy)
        allocated.append(signal_copy)

    allocated.sort(
        key=lambda item: (
            float(item.get("signal_score", 0) or 0),
            float(item.get("confidence", 0) or 0),
            str(item.get("strategy_id", "")),
            str(item.get("symbol", "")),
        ),
        reverse=True,
    )
    for index, item in enumerate(allocated, start=1):
        item["signal_rank"] = index
    stats["signals_out"] = len(allocated)
    return allocated, stats


def _append_signal_diagnostic(
    diagnostics: list[dict[str, Any]],
    signal: dict[str, Any],
    *,
    limit: int = 12,
) -> None:
    """Keep a bounded preview of allocation decisions for reports/status."""
    if len(diagnostics) >= limit:
        return
    diagnostics.append(
        {
            "strategy_id": str(signal.get("strategy_id", "")),
            "symbol": str(signal.get("symbol", "")),
            "asset_class": str(signal.get("asset_class", "")),
            "holding_window_code": str(signal.get("holding_window_code", "")),
            "base_signal_score": _round(signal.get("base_signal_score")),
            "signal_score": _round(signal.get("signal_score")),
            "confidence": _round(signal.get("confidence")),
            "target_return_pct": _round(signal.get("target_return_pct")),
            "allocation_status": str(signal.get("allocation_status", "")),
            "fitness_composite_score": (
                _round(signal.get("fitness_composite_score"))
                if signal.get("fitness_composite_score") not in (None, "")
                else None
            ),
            "fitness_checkpoints_evaluated": int(
                signal.get("fitness_checkpoints_evaluated", 0) or 0
            ),
            "suppress_threshold_used": _round(signal.get("suppress_threshold_used")),
            "allocation_note": str(signal.get("allocation_note", "")),
        }
    )


def _compute_composite_score(
    *,
    avg_fitness_score: float,
    avg_realized_return_pct: float,
    win_rate: float,
    sample_weight: float,
) -> float:
    """Blend outcome quality, hit rate, and raw returns into one fitness score.

    `avg_fitness_score` is already risk-adjusted at the checkpoint level.
    `win_rate_edge` rewards consistency relative to a 50% baseline.
    `return_component` keeps actual net return visible after friction.
    `sample_weight` damps small sample sizes before clipping to [-100, 100].
    """
    win_rate_edge = ((win_rate * 100.0) - 50.0) * 0.6
    return_component = avg_realized_return_pct * 4.0
    raw_score = (avg_fitness_score * 0.65) + win_rate_edge + return_component
    weighted_score = raw_score * sample_weight
    if weighted_score > 100.0:
        weighted_score = 100.0
    if weighted_score < -100.0:
        weighted_score = -100.0
    return round(weighted_score, 6)


def _allocation_bonus(
    *,
    composite_fitness_score: float,
    sample_weight: float,
) -> float:
    """Translate composite fitness into a small ranking adjustment."""
    damped_weight = 0.5 + max(0.0, min(1.0, sample_weight))
    bonus = composite_fitness_score * damped_weight
    if bonus > 8.0:
        bonus = 8.0
    if bonus < -8.0:
        bonus = -8.0
    return round(bonus, 6)


def _allocation_note(
    *,
    allocation_status: str,
    composite_score: float | None,
    checkpoints_evaluated: int,
    suppress_threshold: float | None = None,
    high_score_override_min_score: float = 90.0,
    high_score_override_fitness_margin: float = 0.25,
) -> str:
    if composite_score is None or checkpoints_evaluated <= 0:
        return "No prior strategy fitness history yet."
    if allocation_status == "favored":
        return (
            f"Favored by shadow fitness: composite {composite_score:.3f} "
            f"over {checkpoints_evaluated} checkpoints."
        )
    if allocation_status == "weighted":
        return (
            f"Weighted by shadow fitness: composite {composite_score:.3f} "
            f"over {checkpoints_evaluated} checkpoints."
        )
    if allocation_status == "suppressed":
        return (
            f"Suppressed by shadow fitness: composite {composite_score:.3f} "
            f"vs threshold {float(suppress_threshold or 0):.3f} over {checkpoints_evaluated} checkpoints."
        )
    if allocation_status == "high_score_override":
        return (
            f"Paper high-score override: signal score >= {high_score_override_min_score:.1f} "
            f"and composite {composite_score:.3f} is within {high_score_override_fitness_margin:.3f} "
            f"of threshold {float(suppress_threshold or 0):.3f} over {checkpoints_evaluated} checkpoints."
        )
    return (
        f"Observed but still unproven: composite {composite_score:.3f} "
        f"over {checkpoints_evaluated} checkpoints."
    )


def _resolve_suppress_threshold(
    *,
    default_threshold: float,
    asset_class: str,
    asset_class_suppress_thresholds: dict[str, float] | None,
) -> float:
    """Choose the active suppress threshold for the signal asset class."""
    if asset_class_suppress_thresholds:
        specific = asset_class_suppress_thresholds.get(str(asset_class).strip().lower())
        if specific is not None:
            return float(specific)
    return float(default_threshold)


def _normalize_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _round(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return round(float(value), 6)
