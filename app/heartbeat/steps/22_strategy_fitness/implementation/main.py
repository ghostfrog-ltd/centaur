"""Heartbeat step implementation owned by `22_strategy_fitness`."""

from __future__ import annotations

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
    approved same-as-paper live follower lane.
    """
    raw_rows = context.usage_ledger.list_strategy_fitness_rows(
        as_of=context.started_at,
        lookback_days=context.config.strategy_fitness_lookback_days,
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
