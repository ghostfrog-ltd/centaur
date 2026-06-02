"""Heartbeat step implementation owned by `12_maintenance_live_stale_orders`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    ExecutionRouter,
    PipelineResult,
    TickContext,
    _is_stale_entry_order,
    _live_runtime_allows_broker_reads,
    _live_runtime_allows_order_mutation,
    date,
    get_broker_adapter,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Cancel stale untouched live equity entry limits after activation gates.

    This mirrors the paper stale-order reaper for the future live lane. It only
    targets unfilled equity buy limits, records the cancellation in the order
    audit trail, and relies on the live adapter to enforce credentials and
    activation acknowledgement before any live account mutation.
    """
    if not _live_runtime_allows_broker_reads(context):
        result = {
            "broker": "alpaca_live",
            "mode": "skipped",
            "reason": "runtime_mode_not_live",
            "orders_checked": 0,
            "stale_candidates": 0,
            "orders_canceled": 0,
        }
        context.state["live_stale_order_reaper"] = {
            **result,
            "canceled_orders": [],
            "errors": [],
        }
        return result

    raw_orders = list(context.state.get("alpaca_live_orders", {}).get("raw", []))
    stale_after_minutes = max(1, int(context.config.paper_execution_stale_order_minutes))
    if not raw_orders:
        result = {
            "broker": "alpaca_live",
            "mode": "idle",
            "orders_checked": 0,
            "stale_candidates": 0,
            "orders_canceled": 0,
        }
        context.state["live_stale_order_reaper"] = {
            **result,
            "canceled_orders": [],
            "errors": [],
        }
        return result

    canceled_orders: list[dict[str, Any]] = []
    intended_cancellations: list[dict[str, Any]] = []
    cancel_errors: list[dict[str, Any]] = []
    stale_candidates: list[dict[str, Any]] = []
    updated_orders: list[dict[str, Any]] = []
    router = ExecutionRouter()

    for order in raw_orders:
        symbol = str(order.get("symbol", "")).upper()
        if not _is_stale_entry_order(
            order=order,
            as_of=context.started_at,
            stale_after_minutes=stale_after_minutes,
        ):
            updated_orders.append(order)
            continue
        stale_candidates.append(
            {
                "symbol": symbol,
                "order_id": str(order.get("id", "")).strip(),
                "broker_id": "alpaca_live",
            }
        )
        order_id = str(order.get("id", "")).strip()
        if not order_id:
            cancel_errors.append({"symbol": symbol, "error": "missing_order_id"})
            updated_orders.append(order)
            continue
        routed_cancel = router.route_cancel_order(
            context=context,
            broker_id="alpaca_live",
            order_id=order_id,
            lane="live",
        )
        if routed_cancel.canceled:
            canceled_order = {
                **order,
                "broker_id": "alpaca_live",
                "status": "canceled",
                "updated_at": context.started_at.isoformat(),
            }
            canceled_orders.append(canceled_order)
            updated_orders.append(canceled_order)
        elif routed_cancel.status == "live_dry_intent":
            intended_cancellations.append(
                {
                    "symbol": symbol,
                    "order_id": order_id,
                    "broker_id": "alpaca_live",
                    "intent": routed_cancel.intended_order or {},
                }
            )
            updated_orders.append(order)
        else:
            cancel_errors.append(
                {"symbol": symbol, "error": routed_cancel.error or routed_cancel.status}
            )
            updated_orders.append(order)

    orders_saved = 0
    if canceled_orders:
        orders_saved = context.usage_ledger.record_paper_trade_orders(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            orders=canceled_orders,
            broker_id="alpaca_live",
        )
        protection = context.state.get("live_daily_protection", {})
        session_date = protection.get("session_date") if isinstance(protection, dict) else None
        if session_date:
            stale_count = context.usage_ledger.increment_broker_daily_stale_order_count(
                session_date=date.fromisoformat(str(session_date)),
                broker_id="alpaca_live",
                tick_id=context.tick_id,
                checked_at=context.started_at,
                count=len(canceled_orders),
            )
            if isinstance(protection, dict):
                protection["stale_orders_reaped_count"] = stale_count
                if isinstance(protection.get("raw"), dict):
                    protection["raw"]["stale_orders_reaped_count"] = stale_count

    prior_summary = context.state.get("alpaca_live_orders", {}).get("summary", {})
    if _live_runtime_allows_order_mutation(context):
        revised_summary = get_broker_adapter(context, "alpaca_live").summarize_orders(updated_orders)
    else:
        revised_summary = prior_summary
    context.state["alpaca_live_orders"] = {
        "summary": {
            **revised_summary,
            "orders_saved": int(prior_summary.get("orders_saved", 0) or 0) + orders_saved,
            "mode": str(prior_summary.get("mode", "recent_orders")),
        },
        "raw": updated_orders,
    }

    result = {
        "broker": "alpaca_live",
        "mode": "monitoring",
        "orders_checked": len(raw_orders),
        "stale_candidates": len(stale_candidates),
        "orders_canceled": len(canceled_orders),
        "orders_intended": len(intended_cancellations),
        "orders_saved": orders_saved,
        "stale_after_minutes": stale_after_minutes,
    }
    if intended_cancellations:
        result["mode"] = "live_dry"
    if stale_candidates:
        result["first_stale_symbol"] = stale_candidates[0]["symbol"]
    if cancel_errors:
        result["error_count"] = len(cancel_errors)
        result["first_error"] = cancel_errors[0]["error"]
    context.state["live_stale_order_reaper"] = {
        **result,
        "canceled_orders": canceled_orders,
        "intended_cancellations": intended_cancellations,
        "errors": cancel_errors,
        "stale_candidates_detail": stale_candidates,
    }
    return result
