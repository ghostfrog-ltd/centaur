"""Heartbeat step implementation owned by `31_execution_live`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    ExecutionRouter,
    PipelineResult,
    TickContext,
    _live_runtime_allows_broker_reads,
    _live_runtime_allows_order_mutation,
    _paper_execution_status,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Submit approved live follower entries and persist the live audit trail.

    Live execution is deliberately downstream of paper submission and live CFO.
    This step only sends orders that survived those gates, then stores Alpaca
    Live responses separately so live-vs-paper drift remains reviewable.
    """
    approvals = list(context.state.get("live_risk_cfo", {}).get("approved_order_requests", []))
    if not _live_runtime_allows_order_mutation(context):
        result = {
            "broker": "alpaca_live",
            "orders_submitted": 0,
            "orders_saved": 0,
            "execution_status": "live_dry" if approvals else "idle",
            "mode": "live_dry" if _live_runtime_allows_broker_reads(context) else "skipped",
            "reason": "runtime_mode_not_live_order_mutation",
            "intended_orders": len(approvals),
        }
        context.state["execution_live"] = result
        return result
    if not approvals:
        result = {
            "broker": "alpaca_live",
            "orders_submitted": 0,
            "orders_saved": 0,
            "execution_status": "idle",
        }
        context.state["execution_live"] = result
        return result

    submitted_orders: list[dict[str, Any]] = []
    submission_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for approval in approvals:
        routed = router.route_entry_approval(
            context=context,
            approval=approval,
            lane="live",
        )
        if routed.submitted and routed.order is not None:
            submitted_orders.append(
                {
                    **routed.order,
                    "broker_id": approval["broker_id"],
                    "proposal_id": approval["proposal_id"],
                    "strategy_id": approval["strategy_id"],
                    "strategy_family": approval["strategy_family"],
                    "profile_id": approval["profile_id"],
                    "source": approval["source"],
                    "asset_class": approval["asset_class"],
                    "planned_take_profit_price": approval.get("target_price"),
                    "planned_stop_loss_price": approval.get("stop_loss_price"),
                    "planned_holding_window_code": approval.get("holding_window_code"),
                    "planned_holding_window_minutes": approval.get(
                        "holding_window_minutes"
                    ),
                    "planned_managed_exit_policy": approval.get(
                        "managed_exit_policy"
                    ),
                    "planned_profit_exit_window_minutes": approval.get(
                        "profit_exit_window_minutes"
                    ),
                    "planned_max_hold_window_minutes": approval.get(
                        "max_hold_window_minutes"
                    ),
                    "planned_profit_capture_pct": context.config.paper_execution_profit_capture_pct,
                }
            )
        elif routed.error:
            submission_errors.append(
                {
                    "symbol": approval["symbol"],
                    "broker_id": approval["broker_id"],
                    "strategy_id": approval["strategy_id"],
                    "error": routed.error,
                }
            )

    orders_saved = context.usage_ledger.record_paper_trade_orders(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        orders=submitted_orders,
        broker_id="alpaca_live",
    )
    result = {
        "broker": "alpaca_live",
        "orders_submitted": len(submitted_orders),
        "orders_saved": orders_saved,
        "execution_status": _paper_execution_status(
            submitted_count=len(submitted_orders),
            error_count=len(submission_errors),
        ),
    }
    if submitted_orders:
        result["submitted_symbols"] = [
            str(order.get("symbol", "")).upper() for order in submitted_orders
        ]
        result["latest_status"] = submitted_orders[0].get("status", "")
    if submission_errors:
        result["error_count"] = len(submission_errors)
        result["first_error"] = submission_errors[0]["error"]
    context.state["execution_live"] = {
        **result,
        "orders": submitted_orders,
        "errors": submission_errors,
    }
    return result
