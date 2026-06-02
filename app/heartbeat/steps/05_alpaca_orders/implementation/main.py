"""Heartbeat step implementation owned by `05_alpaca_orders`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_broker_adapter,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `alpaca.orders` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    adapter = get_broker_adapter(context, "alpaca_paper")
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
    summary = adapter.summarize_orders(raw_orders)
    result = {
        "broker_id": adapter.broker_id,
        **summary,
        "orders_saved": orders_saved,
        "mode": "recent_orders",
    }
    payload = {
        "broker_id": adapter.broker_id,
        "summary": result,
        "raw": raw_orders,
    }
    context.state["alpaca_orders"] = payload
    context.state["execution_orders"] = payload
    return result
