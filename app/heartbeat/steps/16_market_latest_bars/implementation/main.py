"""Heartbeat step implementation owned by `16_market_latest_bars`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_market_data_adapter,
    summarize_latest_bars,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `market.latest_bars` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    gate = context.state["market_gate"]
    watchlist = list(context.config.discovery_equity_symbols)

    if not gate["equity_scan_ready"]:
        result = {
            "bars_requested": len(watchlist),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "skipped",
            "reason": gate["equity_reason"],
        }
        context.state["market_data_latest_bars"] = result
        return result

    market_data = get_market_data_adapter(context, "alpaca")
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = market_data.get_latest_equity_bars(context, symbols=watchlist)
    bars_saved = context.usage_ledger.record_latest_bars(
        tick_id=context.tick_id,
        captured_at=captured_at,
        source="alpaca_market_data",
        bars_by_symbol=bars,
        quote_currency="USD",
        usd_to_gbp=float(fx_reference["usd_to_gbp"]),
    )
    result = {
        "bars_requested": len(watchlist),
        "bars_saved": bars_saved,
        "mode": "latest_bars",
        **summarize_latest_bars(bars),
    }
    context.state["market_data_latest_bars"] = {
        **result,
        "raw": bars,
    }
    return result
