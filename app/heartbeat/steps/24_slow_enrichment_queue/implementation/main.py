"""Heartbeat step implementation owned by `24_slow_enrichment_queue`."""

from __future__ import annotations

from app.framework.engine.slow_enrichment_queue import (
    enqueue_slow_enrichment_candidates,
)
from app.heartbeat.support import PipelineResult, TickContext


def run_implementation(context: TickContext) -> PipelineResult:
    """Queue non-selected ranked candidates without changing trade decisions."""

    market_scan = context.state.get("market_scan", {})
    ranked_candidates = list(market_scan.get("ranked_candidates", []))
    selected_candidates = list(market_scan.get("selected_candidates", []))
    if not ranked_candidates:
        result = {
            "mode": "skipped",
            "reason": "no_ranked_candidates",
            "ranked_candidates": 0,
            "selected_candidates": len(selected_candidates),
            "enqueued": 0,
            "trade_authority": "none",
        }
        context.state["slow_enrichment_queue"] = result
        return result

    result = enqueue_slow_enrichment_candidates(
        tick_id=context.tick_id,
        queued_at=context.started_at,
        ranked_candidates=ranked_candidates,
        selected_candidates=selected_candidates,
        usage_ledger=context.usage_ledger,
    )
    result["trade_authority"] = "none"
    context.state["slow_enrichment_queue"] = result
    return result
