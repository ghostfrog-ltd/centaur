"""Heartbeat step implementation owned by `17_trading212_latest_bars`."""

from __future__ import annotations

from app.heartbeat.support import (
    MarketDataAdapterError,
    PipelineResult,
    TickContext,
    _as_float,
    _trading212_position_price_bars,
    get_market_data_adapter,
    summarize_latest_bars,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `trading212.latest_bars` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    provider = str(
        getattr(context.config, "trading212_paper_market_data_provider", "disabled")
        or "disabled"
    ).strip().lower()
    symbols = list(getattr(context.config, "trading212_paper_equity_symbols", tuple()) or tuple())
    broker_market = (
        context.state.get("market_gate", {})
        .get("broker_equity_markets", {})
        .get("trading212_paper", {})
    )
    if provider in {"disabled", "none", "off"}:
        result = {
            "bars_requested": len(symbols),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "disabled",
            "provider": provider,
        }
        context.state["trading212_data_latest_bars"] = result
        return result
    if provider in {"positions_api", "trading212_positions"}:
        bars = _trading212_position_price_bars(
            context=context,
            allowed_symbols=symbols,
        )
        bars_saved = context.usage_ledger.record_latest_bars(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            source="trading212_market_data",
            bars_by_symbol=bars,
            quote_currency="GBP",
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
        result = {
            "bars_requested": len(symbols),
            "bars_received": len(bars),
            "bars_saved": bars_saved,
            "mode": "latest_bars" if bars else "skipped",
            "provider": provider,
            "reason": "" if bars else "trading212_no_held_positions_with_current_price",
            **summarize_latest_bars(bars),
        }
        context.state["trading212_data_latest_bars"] = {
            **result,
            "raw": bars,
        }
        return result
    if not symbols:
        result = {
            "bars_requested": 0,
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "disabled",
            "provider": provider,
            "reason": "trading212_symbols_missing",
        }
        context.state["trading212_data_latest_bars"] = result
        return result
    if not bool(broker_market.get("equity_scan_ready")):
        result = {
            "bars_requested": len(symbols),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "skipped",
            "provider": provider,
            "reason": str(broker_market.get("reason") or "trading212_market_closed"),
        }
        context.state["trading212_data_latest_bars"] = result
        return result

    try:
        market_data = get_market_data_adapter(context, provider)
        bars = market_data.get_latest_equity_bars(context, symbols=symbols)
    except MarketDataAdapterError as exc:
        result = {
            "bars_requested": len(symbols),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "error",
            "provider": provider,
            "reason": str(exc),
        }
        context.state["trading212_data_latest_bars"] = result
        return result

    bars_saved = context.usage_ledger.record_latest_bars(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        source="trading212_market_data",
        bars_by_symbol=bars,
        quote_currency="GBP",
        usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
    )
    result = {
        "bars_requested": len(symbols),
        "bars_received": len(bars),
        "bars_saved": bars_saved,
        "mode": "latest_bars",
        "provider": provider,
        **summarize_latest_bars(bars),
    }
    context.state["trading212_data_latest_bars"] = {
        **result,
        "raw": bars,
    }
    return result
