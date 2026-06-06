"""Heartbeat step implementation owned by `22_strategy_fitness`."""

from __future__ import annotations

from app.framework.strategies.registry import build_strategy_registry
from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    enrich_strategy_fitness_rows,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Build and save the latest strategy-fitness scorecard.

    Storage returns raw aggregates grouped by strategy/asset/checkpoint. The
    fitness engine applies minimum-sample rules, computes composite scores, and
    ranks the summaries. These summaries are shared evidence for paper and the
    independent live lane.
    """
    strategy_ids, profile_ids = _fitness_scope_registry_filters(context)
    source_environments, execution_providers, included_sources = _allocation_fitness_sources(context)
    raw_rows = context.usage_ledger.list_strategy_fitness_rows(
        as_of=context.started_at,
        lookback_days=context.config.strategy_fitness_lookback_days,
        source_environments=source_environments,
        execution_providers=execution_providers,
        strategy_ids=strategy_ids,
        profile_ids=profile_ids,
    )
    evidence_mix = context.usage_ledger.list_strategy_fitness_evidence_mix(
        as_of=context.started_at,
        lookback_days=context.config.strategy_fitness_lookback_days,
        strategy_ids=strategy_ids,
        profile_ids=profile_ids,
    )
    summaries = enrich_strategy_fitness_rows(
        rows=raw_rows,
        min_checkpoints=context.config.strategy_fitness_min_checkpoints,
    )
    saved_count = context.usage_ledger.record_strategy_fitness_snapshots(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        summaries=summaries,
        environment=context.config.centaur_environment,
        mode=context.config.centaur_mode,
        source_environment="shadow",
        broker_id=context.config.paper_execution_equity_broker_id,
        data_provider="alpaca",
        execution_provider="shadow",
    )
    result = {
        "strategy_summaries": len(summaries),
        "summaries_saved": saved_count,
        "lookback_days": context.config.strategy_fitness_lookback_days,
        "min_checkpoints": context.config.strategy_fitness_min_checkpoints,
        "fitness_included_source_environments": list(source_environments),
        "fitness_included_execution_providers": list(execution_providers),
        "fitness_included_sources": included_sources,
        "fitness_evidence_mix": {
            "live_evidence_count": int(evidence_mix.get("live_evidence_count", 0) or 0),
            "paper_evidence_count": int(evidence_mix.get("paper_evidence_count", 0) or 0),
            "backtest_evidence_count": int(evidence_mix.get("backtest_evidence_count", 0) or 0),
            "simulator_evidence_count": int(evidence_mix.get("simulator_evidence_count", 0) or 0),
        },
        "mode": "scorecard" if summaries else "insufficient_data",
    }
    if summaries:
        top_summary = summaries[0]
        result["top_strategy"] = top_summary["strategy_id"]
        result["top_checkpoint"] = top_summary["checkpoint_code"]
        result["top_composite_score"] = top_summary["composite_fitness_score"]
        result["top_win_rate"] = top_summary["win_rate"]
    context.state["strategy_fitness"] = {
        **result,
        "summaries": summaries,
    }
    return result


def _fitness_scope_registry_filters(context: TickContext) -> tuple[tuple[str, ...], tuple[str, ...]]:
    strategy_ids: list[str] = []
    profile_ids: list[str] = []
    for strategy in build_strategy_registry():
        for profile in strategy.build_profiles(context.config):
            strategy_ids.append(str(profile.strategy_id))
            profile_ids.append(str(profile.profile_id))
    return tuple(sorted(set(strategy_ids))), tuple(sorted(set(profile_ids)))


def _allocation_fitness_sources(
    context: TickContext,
) -> tuple[tuple[str, ...], tuple[str, ...], list[str]]:
    source_environments = ["shadow"]
    execution_providers = ["shadow"]
    if (
        context.config.centaur_environment == "paper"
        and bool(getattr(context.config, "include_backtest_evidence_in_paper_fitness", False))
    ) or (
        context.config.centaur_environment == "live"
        and bool(getattr(context.config, "include_backtest_evidence_in_live_fitness", False))
    ):
        source_environments.append("backtest")
        execution_providers.append("simulator")
    return (
        tuple(source_environments),
        tuple(execution_providers),
        [
            f"{source_environment}:{execution_provider}"
            for source_environment in source_environments
            for execution_provider in execution_providers
            if (source_environment, execution_provider) in {
                ("shadow", "shadow"),
                ("backtest", "simulator"),
            }
        ],
    )
