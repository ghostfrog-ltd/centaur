"""Heartbeat step implementation owned by `06_alpaca_live_sync`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _empty_live_broker_state,
    _live_runtime_allows_broker_reads,
    get_broker_adapter,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `alpaca_live.sync` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    if not _live_runtime_allows_broker_reads(context):
        return _empty_live_broker_state(context, reason="runtime_mode_not_live")
    if not context.config.alpaca_live_api_configured:
        return _empty_live_broker_state(
            context,
            reason="alpaca_live_credentials_missing",
        )

    adapter = get_broker_adapter(context, "alpaca_live")
    raw_account = {
        **adapter.get_account(context),
        "broker_id": adapter.broker_id,
    }
    account_summary = adapter.summarize_account(raw_account)
    raw_positions = [
        {
            **position,
            "broker_id": adapter.broker_id,
        }
        for position in adapter.get_positions(context)
    ]
    positions_summary = adapter.summarize_positions(raw_positions)
    raw_orders = [
        {
            **order,
            "broker_id": adapter.broker_id,
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
    account_payload = {
        "broker_id": adapter.broker_id,
        "summary": account_summary,
        "raw": raw_account,
    }
    context.state["alpaca_live_account"] = account_payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = account_payload
    context.state["alpaca_live_positions"] = {
        "broker_id": adapter.broker_id,
        "summary": positions_summary,
        "raw": raw_positions,
    }
    context.state["alpaca_live_orders"] = {
        "broker_id": adapter.broker_id,
        "summary": orders_summary,
        "raw": raw_orders,
    }
    return {
        "broker_id": adapter.broker_id,
        "mode": "synced",
        "orders_saved": orders_saved,
        "open_positions": positions_summary.get("open_positions", 0),
        "open_orders": orders_summary.get("open_orders", 0),
        "equity": account_summary.get("equity"),
        "cash": account_summary.get("cash"),
    }
