"""Heartbeat step implementation owned by `30_execution_paper`."""

from __future__ import annotations

from app.framework.reporting.paper_candidate_decision_report import (
    PaperCandidateDecisionReport,
)
from app.framework.reporting.paper_canary import PAPER_CANARY_EXECUTION_MODE
from app.heartbeat.support import (
    Any,
    ExecutionRouter,
    PipelineResult,
    TickContext,
    _paper_canary_active,
    _paper_execution_status,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Submit only CFO-approved paper entries and persist broker responses.

    Execution does not re-rank or resize proposals. It sends the exact approved
    order request through the selected broker adapter, captures any broker error,
    and writes submitted orders with their planned exits for later management.
    """
    approvals = list(context.state["risk_cfo"].get("approved_order_requests", []))
    canary_active = _paper_canary_active(context)
    paper_decision = PaperCandidateDecisionReport(
        config=context.config,
        usage_ledger=context.usage_ledger,
    ).build_report()
    if (
        not canary_active
        and str(paper_decision.get("paper_trading_allowed", "no") or "no").lower() != "yes"
    ):
        result = {
            "broker": "blocked",
            "orders_submitted": 0,
            "orders_saved": 0,
            "execution_status": "blocked",
            "reason": "paper_trading_not_allowed",
            "paper_candidate_status": str(paper_decision.get("paper_candidate_status", "") or ""),
            "paper_block_reason": str(paper_decision.get("paper_block_reason", "") or ""),
            "failed_audit_reason": str(paper_decision.get("failed_audit_reason", "") or ""),
            "current_known_best_candidate": str(paper_decision.get("current_known_best_candidate", "") or ""),
            "current_paper_candidate": paper_decision.get("current_paper_candidate"),
        }
        context.state["execution"] = result
        return result
    if not approvals:
        default_brokers = sorted(
            {
                context.config.paper_execution_equity_broker_id,
                context.config.paper_execution_crypto_broker_id,
            }
        )
        result = {
            "broker": default_brokers[0] if len(default_brokers) == 1 else "multiple",
            "orders_submitted": 0,
            "orders_saved": 0,
            "execution_status": "idle",
        }
        if len(default_brokers) > 1:
            result["brokers"] = default_brokers
        context.state["execution"] = result
        return result

    submitted_orders: list[dict[str, Any]] = []
    submission_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for approval in approvals:
        routed = router.route_entry_approval(
            context=context,
            approval=approval,
            lane="paper",
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
                    "planned_break_even_trigger_price": approval.get(
                        "break_even_trigger_price"
                    ),
                    "planned_break_even_trigger_price_gbp": approval.get(
                        "break_even_trigger_price_gbp"
                    ),
                    "planned_trailing_stop_mode": approval.get("trailing_stop_mode"),
                    "paper_canary": bool(approval.get("paper_canary")),
                    "execution_mode": str(
                        approval.get("execution_mode", "paper")
                    ),
                    "mode": str(approval.get("mode", "paper")),
                    "operator_override": str(approval.get("operator_override", "") or ""),
                    "timeframe": str(approval.get("timeframe", "") or ""),
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
    )
    if canary_active and submitted_orders:
        updater = getattr(context.usage_ledger, "update_paper_canary_state", None)
        if callable(updater):
            updater(
                updated_at=context.started_at,
                last_signal_at=context.started_at,
                last_entry_at=context.started_at,
            )
    broker_ids = sorted(
        {
            str(item.get("broker_id", "")).strip().lower()
            for item in submitted_orders or approvals
            if str(item.get("broker_id", "")).strip()
        }
    )
    result = {
        "broker": broker_ids[0] if len(broker_ids) == 1 else "multiple",
        "orders_submitted": len(submitted_orders),
        "orders_saved": orders_saved,
        "execution_status": _paper_execution_status(
            submitted_count=len(submitted_orders),
            error_count=len(submission_errors),
        ),
    }
    if len(broker_ids) > 1:
        result["brokers"] = broker_ids
    if submitted_orders:
        result["submitted_symbols"] = [
            str(order.get("symbol", "")).upper() for order in submitted_orders
        ]
        result["latest_status"] = submitted_orders[0].get("status", "")
        if canary_active:
            result["execution_mode"] = PAPER_CANARY_EXECUTION_MODE
    if submission_errors:
        result["error_count"] = len(submission_errors)
        result["first_error"] = submission_errors[0]["error"]
    context.state["execution"] = {
        **result,
        "orders": submitted_orders,
        "errors": submission_errors,
    }
    return result
