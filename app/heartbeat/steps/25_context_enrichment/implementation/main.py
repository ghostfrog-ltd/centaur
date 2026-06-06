"""Heartbeat step implementation owned by `25_context_enrichment`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _enrich_candidates_with_technicals,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `context.enrichment` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    selected_candidates = list(context.state["market_scan"].get("selected_candidates", []))
    candidates = selected_candidates

    if not candidates:
        result = {
            "candidates_enriched": 0,
            "selected_candidates": 0,
            "news_items": 0,
            "sentiment_ready": False,
            "mode": "skipped",
            "reason": "no_selected_candidates",
        }
        context.state["context_enrichment"] = result
        return result

    enriched_candidates = _enrich_candidates_with_technicals(
        context,
        candidates=candidates,
        lookback_periods=20,
    )
    selected_enriched = [item for item in enriched_candidates if bool(item.get("selected"))]
    technical_ready = sum(
        1 for item in enriched_candidates if bool(item.get("technical_context_ready"))
    )
    breakout_ready = sum(
        1
        for item in enriched_candidates
        if bool(item.get("price_trigger_20"))
        and bool(item.get("volume_surge_20"))
        and bool(item.get("volatility_floor_pass_20"))
    )
    result = {
        "candidates_enriched": len(enriched_candidates),
        "selected_candidates": len(selected_enriched),
        "technical_context_ready": technical_ready,
        "breakout_ready_candidates": breakout_ready,
        "news_items": 0,
        "sentiment_ready": False,
        "mode": "fast_selected_candidates_only",
        "candidate_policy": "selected_from_discovery_target_count",
        "top_symbol": (selected_enriched[0]["symbol"] if selected_enriched else enriched_candidates[0]["symbol"]),
    }
    context.state["context_enrichment"] = {
        **result,
        "candidates": enriched_candidates,
        "selected_candidates": selected_enriched,
    }
    return result
