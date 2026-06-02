"""Heartbeat step implementation owned by `23_market_scan`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    rank_candidates,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `market.scan` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    gate = context.state["market_gate"]
    equity_universe = list(context.config.discovery_equity_symbols)
    crypto_universe = list(context.config.discovery_crypto_symbols)
    current_rows = context.usage_ledger.get_latest_bars_for_tick(
        tick_id=context.tick_id,
        sources=[
            "alpaca_market_data",
            "alpaca_crypto_data",
            "trading212_market_data",
        ],
    )

    result = {
        "equity_universe": len(equity_universe),
        "crypto_universe": len(crypto_universe),
        "bars_available": len(current_rows),
        "candidates_found": 0,
        "selected_candidates": 0,
        "mode": "pending",
        "scan_ready": gate["can_scan"],
    }
    if not current_rows:
        result["mode"] = "skipped"
        result["scan_ready"] = False
        result["skip_reason"] = gate["reason"] if gate["can_scan"] else gate["reason"]
        context.state["market_scan"] = {
            "result": result,
            "ranked_candidates": [],
            "selected_candidates": [],
        }
        return result

    previous_rows = context.usage_ledger.get_previous_bars(
        tick_id=context.tick_id,
        symbol_keys=[(row["source"], row["symbol"]) for row in current_rows],
    )
    ranked_candidates = rank_candidates(
        current_rows=current_rows,
        previous_by_symbol=previous_rows,
        target_count=context.config.discovery_target_count,
    )
    ranked_candidate_dicts = [item.as_dict() for item in ranked_candidates]
    selected_candidates = [item for item in ranked_candidate_dicts if item["selected"]]
    context.usage_ledger.record_discovery_candidates(
        tick_id=context.tick_id,
        candidates=ranked_candidate_dicts,
    )

    result["candidates_found"] = len(ranked_candidate_dicts)
    result["selected_candidates"] = len(selected_candidates)
    result["mode"] = "dynamic_discovery"
    if selected_candidates:
        result["top_symbol"] = selected_candidates[0]["symbol"]
        result["top_score"] = selected_candidates[0]["discovery_score"]

    context.state["market_scan"] = {
        "result": result,
        "ranked_candidates": ranked_candidate_dicts,
        "selected_candidates": selected_candidates,
    }
    return result
