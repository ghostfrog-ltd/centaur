"""Heartbeat step implementation owned by `19_execution_paper_exits`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    ExecutionRouter,
    PipelineResult,
    TickContext,
    _active_paper_broker_ids,
    _build_exit_order_request,
    _build_unmanaged_equity_flatten_entry_order,
    _coerce_datetime,
    _equity_flatten_due,
    _find_most_protective_managed_entry_order,
    _is_trading212_price_seed_position,
    _latest_bars_by_symbol,
    _normalized_symbol_key,
    _open_exit_order_refresh_reason,
    _order_status_is_open,
    _orders_state_key_for_broker,
    _paper_execution_status,
    _paper_limit_buffer_bps,
    _position_reference_latest_bar,
    _position_symbol_for_broker,
    _positions_state_key_for_broker,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Submit or refresh deterministic managed exits for paper positions.

    This is the protective sell side of paper execution: it reconstructs the
    persisted entry plan, checks stop/profit/time/no-overnight rules, refreshes
    stale/non-marketable open exits, and writes every submitted exit back to the
    broker-separated order audit trail.
    """
    positions = []
    for broker_id in _active_paper_broker_ids(context):
        positions.extend(
            list(context.state.get(_positions_state_key_for_broker(broker_id), {}).get("raw", []))
        )
    if not positions:
        result = {
            "broker": "alpaca_paper",
            "positions_checked": 0,
            "exit_orders_submitted": 0,
            "mode": "idle",
        }
        context.state["paper_exit_management"] = {
            **result,
            "orders": [],
            "errors": [],
            "skipped": [],
        }
        return result

    recent_orders = context.usage_ledger.list_recent_execution_lane_trade_orders(limit=100)
    raw_open_orders = []
    for broker_id in _active_paper_broker_ids(context):
        raw_open_orders.extend(
            list(context.state.get(_orders_state_key_for_broker(broker_id), {}).get("raw", []))
        )
    latest_bars = _latest_bars_by_symbol(context)
    open_exit_by_symbol = {
        _normalized_symbol_key(str(order.get("symbol", "")).upper()): order
        for order in raw_open_orders
        if str(order.get("symbol", "")).strip()
        and str(order.get("side", "")).strip().lower() == "sell"
        and _order_status_is_open(str(order.get("status", "")))
    }

    exit_requests: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    refreshed_exit_orders: list[dict[str, Any]] = []
    refresh_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for position in positions:
        broker_id = str(position.get("broker_id", "alpaca_paper")).strip().lower() or "alpaca_paper"
        symbol = _position_symbol_for_broker(position, broker_id, config=context.config)
        if not symbol:
            continue
        if _is_trading212_price_seed_position(
            context=context,
            position=position,
            broker_id=broker_id,
            symbol=symbol,
            recent_orders=recent_orders,
        ):
            skipped.append(
                {
                    "symbol": symbol,
                    "broker_id": broker_id,
                    "reason": "price_seed_position",
                }
            )
            continue

        entry_order = _find_most_protective_managed_entry_order(
            symbol=symbol,
            orders=recent_orders,
            broker_id=broker_id,
        )
        if entry_order is None:
            latest_bar = latest_bars.get(symbol) or latest_bars.get(
                _normalized_symbol_key(symbol)
            )
            if latest_bar is None and _equity_flatten_due(
                context.config,
                asset_class="equity",
                as_of=context.started_at,
                next_close=context.state.get("market_gate", {}).get("next_close"),
            ):
                latest_bar = _position_reference_latest_bar(
                    position=position,
                    as_of=context.started_at,
                )
            if latest_bar is not None:
                unmanaged_entry_order = _build_unmanaged_equity_flatten_entry_order(
                    position=position,
                    broker_id=broker_id,
                    symbol=symbol,
                )
                exit_request, skip_reason = _build_exit_order_request(
                    context=context,
                    tick_id=context.tick_id,
                    position=position,
                    entry_order=unmanaged_entry_order,
                    latest_bar=latest_bar,
                    bar_history=[],
                    as_of=context.started_at,
                    limit_buffer_bps=_paper_limit_buffer_bps(
                        context.config,
                        "equity",
                    ),
                )
                if exit_request is not None:
                    exit_request["unmanaged_flatten"] = True
                    exit_request["missing_entry_plan"] = True
                    if exit_request.get("exit_reason") == "profit_capture_hit":
                        exit_request["exit_reason"] = "settings_profit_capture"
                    exit_requests.append(exit_request)
                    continue
                if _equity_flatten_due(
                    context.config,
                    asset_class="equity",
                    as_of=context.started_at,
                    next_close=context.state.get("market_gate", {}).get("next_close"),
                ):
                    skipped.append(
                        {
                            "symbol": symbol,
                            "reason": skip_reason or "unmanaged_flatten_failed",
                        }
                    )
                    continue
            skipped.append({"symbol": symbol, "reason": "missing_entry_plan"})
            continue

        symbol_key = _normalized_symbol_key(symbol)
        latest_bar = latest_bars.get(symbol) or latest_bars.get(symbol_key)
        if latest_bar is None and _equity_flatten_due(
            context.config,
            asset_class=str(entry_order.get("asset_class", "")),
            as_of=context.started_at,
            next_close=context.state.get("market_gate", {}).get("next_close"),
        ):
            latest_bar = _position_reference_latest_bar(
                position=position,
                as_of=context.started_at,
            )
        if latest_bar is None:
            skipped.append({"symbol": symbol, "reason": "latest_bar_unavailable"})
            continue

        open_exit_order = open_exit_by_symbol.get(symbol_key)
        if open_exit_order is not None:
            refresh_reason = _open_exit_order_refresh_reason(
                order=open_exit_order,
                position=position,
                latest_bar=latest_bar,
                as_of=context.started_at,
                stale_after_minutes=max(1, int(context.config.paper_execution_stale_order_minutes)),
            )
            if refresh_reason is None:
                skipped.append({"symbol": symbol, "reason": "exit_order_already_open"})
                continue
            order_id = str(
                open_exit_order.get("id") or open_exit_order.get("order_id") or ""
            ).strip()
            if not order_id:
                skipped.append({"symbol": symbol, "reason": "open_exit_order_missing_id"})
                continue
            routed_cancel = router.route_cancel_order(
                context=context,
                broker_id=broker_id,
                order_id=order_id,
                lane="paper",
            )
            if routed_cancel.canceled:
                refreshed_exit_orders.append(
                    {
                        **open_exit_order,
                        "status": "canceled",
                        "updated_at": context.started_at.isoformat(),
                        "exit_refresh_reason": refresh_reason,
                    }
                )
            else:
                refresh_errors.append(
                    {
                        "symbol": symbol,
                        "order_id": order_id,
                        "reason": refresh_reason,
                        "error": routed_cancel.error or routed_cancel.status,
                    }
                )
                skipped.append({"symbol": symbol, "reason": "exit_order_refresh_failed"})
                continue

        entry_started_at = _coerce_datetime(
            entry_order.get("submitted_at") or entry_order.get("captured_at")
        )
        bar_history = []
        if entry_started_at is not None:
            bar_history = context.usage_ledger.get_market_bars_for_window(
                source=str(entry_order.get("source", "")).strip(),
                symbol=str(entry_order.get("symbol") or symbol).strip(),
                start_at=entry_started_at - timedelta(minutes=5),
                end_at=context.started_at,
            )

        exit_request, skip_reason = _build_exit_order_request(
            context=context,
            tick_id=context.tick_id,
            position=position,
            entry_order=entry_order,
            latest_bar=latest_bar,
            bar_history=bar_history,
            as_of=context.started_at,
            limit_buffer_bps=_paper_limit_buffer_bps(
                context.config,
                str(entry_order.get("asset_class", "")),
            ),
        )
        if exit_request is None:
            skipped.append({"symbol": symbol, "reason": skip_reason or "exit_not_due"})
            continue
        if open_exit_order is not None:
            exit_request["refreshed_exit_order_id"] = str(
                open_exit_order.get("id") or open_exit_order.get("order_id") or ""
            ).strip()
        exit_requests.append(exit_request)

    refreshed_orders_saved = 0
    if refreshed_exit_orders:
        refreshed_orders_saved = context.usage_ledger.record_paper_trade_orders(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            orders=refreshed_exit_orders,
            broker_id="alpaca_paper",
        )

    if not exit_requests:
        result = {
            "broker": "alpaca_paper",
            "positions_checked": len(positions),
            "exit_orders_submitted": 0,
            "exit_orders_refreshed": len(refreshed_exit_orders),
            "refreshed_orders_saved": refreshed_orders_saved,
            "mode": "monitoring",
        }
        if skipped:
            result["skip_reason"] = skipped[0]["reason"]
        if refresh_errors:
            result["refresh_error_count"] = len(refresh_errors)
            result["first_refresh_error"] = refresh_errors[0]["error"]
        context.state["paper_exit_management"] = {
            **result,
            "orders": [],
            "errors": [],
            "skipped": skipped,
            "refreshed_exit_orders": refreshed_exit_orders,
            "refresh_errors": refresh_errors,
        }
        return result

    submitted_orders: list[dict[str, Any]] = []
    submission_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for exit_request in exit_requests:
        routed = router.route_order_request(
            context=context,
            broker_id=exit_request["broker_id"],
            order_request=exit_request["order_request"],
            lane="paper",
            action="flatten" if exit_request.get("unmanaged_flatten") else "exit",
            strategy_id=exit_request.get("strategy_id"),
        )
        if routed.submitted and routed.order is not None:
            submitted_orders.append(
                {
                    **routed.order,
                    "broker_id": exit_request["broker_id"],
                    "proposal_id": exit_request["proposal_id"],
                    "strategy_id": exit_request["strategy_id"],
                    "strategy_family": exit_request["strategy_family"],
                    "profile_id": exit_request["profile_id"],
                    "source": exit_request["source"],
                    "asset_class": exit_request["asset_class"],
                    "planned_take_profit_price": exit_request.get(
                        "planned_take_profit_price"
                    ),
                    "planned_stop_loss_price": exit_request.get(
                        "planned_stop_loss_price"
                    ),
                    "planned_holding_window_code": exit_request.get(
                        "planned_holding_window_code"
                    ),
                    "planned_holding_window_minutes": exit_request.get(
                        "planned_holding_window_minutes"
                    ),
                    "planned_managed_exit_policy": exit_request.get(
                        "planned_managed_exit_policy"
                    ),
                    "planned_profit_exit_window_minutes": exit_request.get(
                        "planned_profit_exit_window_minutes"
                    ),
                    "planned_max_hold_window_minutes": exit_request.get(
                        "planned_max_hold_window_minutes"
                    ),
                    "planned_profit_capture_pct": exit_request.get(
                        "planned_profit_capture_pct"
                    ),
                    "planned_profit_capture_price": exit_request.get(
                        "planned_profit_capture_price"
                    ),
                    "planned_break_even_trigger_price": exit_request.get(
                        "planned_break_even_trigger_price"
                    ),
                    "planned_trailing_stop_mode": exit_request.get(
                        "planned_trailing_stop_mode"
                    ),
                    "exit_reason": exit_request["exit_reason"],
                    "exit_quality_audit": exit_request.get("exit_quality_audit"),
                    "linked_order_id": exit_request.get("linked_order_id", ""),
                    "unmanaged_flatten": exit_request.get("unmanaged_flatten", False),
                    "refreshed_exit_order_id": exit_request.get(
                        "refreshed_exit_order_id", ""
                    ),
                    "paper_canary": bool(exit_request.get("paper_canary")),
                    "execution_mode": str(exit_request.get("execution_mode", "paper")),
                    "mode": str(exit_request.get("mode", "paper")),
                }
            )
        elif routed.error:
            submission_errors.append(
                {
                    "symbol": exit_request["symbol"],
                    "broker_id": exit_request["broker_id"],
                    "strategy_id": exit_request["strategy_id"],
                    "error": routed.error,
                    "exit_reason": exit_request["exit_reason"],
                }
            )

    orders_saved = context.usage_ledger.record_paper_trade_orders(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        orders=submitted_orders,
    )
    broker_ids = sorted(
        {
            str(item.get("broker_id", "")).strip().lower()
            for item in submitted_orders or exit_requests
            if str(item.get("broker_id", "")).strip()
        }
    )
    result = {
        "broker": broker_ids[0] if len(broker_ids) == 1 else "multiple",
        "positions_checked": len(positions),
        "exit_orders_submitted": len(submitted_orders),
        "exit_orders_refreshed": len(refreshed_exit_orders),
        "refreshed_orders_saved": refreshed_orders_saved,
        "orders_saved": orders_saved,
        "execution_status": _paper_execution_status(
            submitted_count=len(submitted_orders),
            error_count=len(submission_errors),
        ),
        "mode": "managed_exits",
    }
    if len(broker_ids) > 1:
        result["brokers"] = broker_ids
    if submitted_orders:
        result["submitted_symbols"] = [
            str(order.get("symbol", "")).upper() for order in submitted_orders
        ]
        result["latest_exit_reason"] = submitted_orders[0].get("exit_reason", "")
    if submission_errors:
        result["error_count"] = len(submission_errors)
        result["first_error"] = submission_errors[0]["error"]
    if refresh_errors:
        result["refresh_error_count"] = len(refresh_errors)
        result["first_refresh_error"] = refresh_errors[0]["error"]
    if skipped:
        result["skipped_positions"] = len(skipped)
    context.state["paper_exit_management"] = {
        **result,
        "orders": submitted_orders,
        "errors": submission_errors,
        "skipped": skipped,
        "refreshed_exit_orders": refreshed_exit_orders,
        "refresh_errors": refresh_errors,
    }
    return result
