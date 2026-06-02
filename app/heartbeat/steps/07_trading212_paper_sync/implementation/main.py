"""Heartbeat step implementation owned by `07_trading212_paper_sync`."""

from __future__ import annotations

from app.heartbeat.support import (
    BrokerAdapterError,
    PipelineResult,
    TickContext,
    _empty_trading212_paper_state,
    _symbol_from_broker_payload,
    get_broker_adapter,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Sync the separate Trading 212 demo account without enabling execution.

    This optional paper lane is isolated from Alpaca execution. API/read
    failures are reported in tick state but do not halt the active paper/live
    control path, because Trading 212 order mutation is still fail-closed.
    """
    if not getattr(context.config, "trading212_paper_api_configured", False):
        return _empty_trading212_paper_state(
            context,
            reason="trading212_paper_credentials_missing",
        )

    try:
        adapter = get_broker_adapter(context, "trading212_paper")
        raw_account = {
            **adapter.get_account(context),
            "broker_id": adapter.broker_id,
        }
        account_summary = adapter.summarize_account(raw_account)
        raw_positions = [
            {
                **position,
                "broker_id": adapter.broker_id,
                "symbol": _symbol_from_broker_payload(position),
            }
            for position in adapter.get_positions(context)
        ]
        positions_summary = adapter.summarize_positions(raw_positions)
        raw_orders = [
            {
                **order,
                "broker_id": adapter.broker_id,
                "symbol": _symbol_from_broker_payload(order),
            }
            for order in adapter.get_orders(
                context,
                status="all",
                after=context.started_at - timedelta(days=7),
                limit=100,
                nested=True,
            )
        ]
        orders_saved = context.usage_ledger.record_paper_trade_orders(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            orders=raw_orders,
            broker_id=adapter.broker_id,
        )
        orders_summary = adapter.summarize_orders(raw_orders)
        context.usage_ledger.record_broker_account_snapshot(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            broker_id=adapter.broker_id,
            summary=account_summary,
            raw_account=raw_account,
            positions=raw_positions,
        )
    except BrokerAdapterError as exc:
        result = _empty_trading212_paper_state(
            context,
            reason=str(exc),
            mode="sync_error",
        )
        result["error_type"] = type(exc).__name__
        return result

    account_payload = {
        "broker_id": adapter.broker_id,
        "summary": account_summary,
        "raw": raw_account,
    }
    context.state["trading212_paper_account"] = account_payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = account_payload
    context.state["trading212_paper_positions"] = {
        "broker_id": adapter.broker_id,
        "summary": positions_summary,
        "raw": raw_positions,
    }
    context.state["trading212_paper_orders"] = {
        "broker_id": adapter.broker_id,
        "summary": orders_summary,
        "raw": raw_orders,
    }
    return {
        "broker_id": adapter.broker_id,
        "mode": "synced",
        "account_snapshot_saved": 1,
        "orders_saved": orders_saved,
        "open_positions": positions_summary.get("open_positions", 0),
        "open_orders": orders_summary.get("open_orders", 0),
        "equity": account_summary.get("equity"),
        "cash": account_summary.get("cash"),
        "currency": account_summary.get("currency"),
    }
