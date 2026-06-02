"""Heartbeat step implementation owned by `18_crypto_latest_bars`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_market_data_adapter,
    summarize_latest_bars,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `crypto.latest_bars` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    gate = context.state["market_gate"]
    symbols = list(context.config.discovery_crypto_symbols)

    if not symbols:
        result = {
            "bars_requested": 0,
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "disabled",
        }
        context.state["crypto_data_latest_bars"] = result
        return result

    if not gate["crypto_scan_ready"]:
        result = {
            "bars_requested": len(symbols),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "skipped",
            "reason": gate["crypto_reason"],
        }
        context.state["crypto_data_latest_bars"] = result
        return result

    market_data = get_market_data_adapter(context, "alpaca")
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = market_data.get_latest_crypto_bars(
        context,
        location=context.config.alpaca_crypto_location,
        symbols=symbols,
    )
    bars_saved = context.usage_ledger.record_latest_bars(
        tick_id=context.tick_id,
        captured_at=captured_at,
        source="alpaca_crypto_data",
        bars_by_symbol=bars,
        quote_currency="USD",
        usd_to_gbp=float(fx_reference["usd_to_gbp"]),
    )
    result = {
        "bars_requested": len(symbols),
        "bars_saved": bars_saved,
        "mode": "latest_crypto_bars",
        **summarize_latest_bars(bars),
    }
    context.state["crypto_data_latest_bars"] = {
        **result,
        "raw": bars,
    }
    return result
