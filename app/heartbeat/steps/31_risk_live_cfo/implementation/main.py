"""Heartbeat step implementation owned by `31_risk_live_cfo`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    PipelineResult,
    TickContext,
    _account_trade_ready,
    _build_live_trade_approval,
    _earned_slot_policy,
    _find_most_protective_managed_entry_order,
    _live_runtime_allows_broker_reads,
)


LIVE_ENTRY_PLAN_AUDIT_ORDER_LIMIT = 500


def run_implementation(context: TickContext) -> PipelineResult:
    """Gate independent live entries using live `.env` dials and guardrails.

    Live uses the shared proposal/evidence stream, then applies its own live
    account, slot, drawdown, allowlist, activation, and broker-validation checks.
    It must obey the active `LIVE_*` settings exactly; the final `LiveRiskGuard`
    still re-checks safety immediately before any real broker mutation.
    """
    config = context.config
    gate = context.state["market_gate"]
    protection = context.state.get("live_daily_protection", {})
    proposals = list(context.state.get("shadow_trade_proposals", {}).get("proposals", []))
    live_account_summary = context.state.get("alpaca_live_account", {}).get("summary", {})
    live_account_trade_ready, live_account_reason = _account_trade_ready(live_account_summary)
    positions_summary = context.state.get("alpaca_live_positions", {}).get("summary", {})
    orders_summary = context.state.get("alpaca_live_orders", {}).get("summary", {})
    open_positions = int(positions_summary.get("open_positions", 0) or 0)
    open_orders = int(orders_summary.get("open_orders", 0) or 0)
    unmanaged_live_symbols = _unmanaged_live_position_symbols(context)
    occupied_slots = open_positions + open_orders
    slot_policy = _earned_slot_policy(
        context=context,
        broker_id="alpaca_live",
        account_state_key="alpaca_live_account",
        base_max_positions=int(config.live_execution_max_open_positions),
        slot_size_usd=float(config.live_execution_default_notional_usd),
    )
    effective_max_positions = int(slot_policy["effective_max_open_positions"])
    available_slots = max(0, effective_max_positions - occupied_slots)
    decision = "hold"
    reason = "live_execution_disabled"
    rejected: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []

    if not _live_runtime_allows_broker_reads(context):
        reason = "runtime_mode_not_live"
    elif not config.live_execution_enabled:
        reason = "live_execution_disabled"
    elif config.live_execution_kill_switch:
        reason = "live_kill_switch_on"
    elif not config.alpaca_live_api_configured:
        reason = "alpaca_live_credentials_missing"
    elif config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
        reason = "activation_ack_missing"
    elif str(protection.get("system_status", "unknown")).lower() != "active":
        reason = str(protection.get("reason", "live_daily_protection_blocked"))
    elif not live_account_trade_ready:
        reason = f"live_{live_account_reason}"
    elif not gate["account_trade_ready"]:
        reason = gate["reason"]
    elif not config.live_execution_allowed_strategies:
        reason = "no_live_strategies_allowed"
    elif unmanaged_live_symbols:
        reason = "unmanaged_live_positions_present"
    elif not proposals:
        reason = "no_live_proposals"
    elif available_slots <= 0:
        reason = "max_live_positions_reached"
    else:
        position_symbols = {
            str(symbol).upper()
            for symbol in positions_summary.get("symbols", [])
            if symbol
        }
        open_order_symbols = {
            str(symbol).upper()
            for symbol in orders_summary.get("open_order_symbols", [])
            if symbol
        }
        allowed_strategies = {
            strategy_id.lower()
            for strategy_id in config.live_execution_allowed_strategies
            if strategy_id
        }
        for proposal in proposals:
            strategy_id = str(proposal.get("strategy_id", "")).lower()
            if strategy_id not in allowed_strategies:
                rejected.append(
                    {
                        "symbol": str(proposal.get("symbol", "")).upper(),
                        "broker_id": "alpaca_live",
                        "strategy_id": str(proposal.get("strategy_id", "")),
                        "reason": "strategy_not_allowed_live",
                    }
                )
                continue
            approval, rejection = _build_live_trade_approval(
                context=context,
                proposal=proposal,
                tick_id=context.tick_id,
                config=config,
                market_gate=gate,
                position_symbols=position_symbols,
                open_order_symbols=open_order_symbols,
            )
            if rejection is not None:
                rejected.append(rejection)
                continue
            if approval is None:
                continue
            approved.append(approval)
            if len(approved) >= min(config.live_execution_max_orders_per_tick, available_slots):
                break

        if approved:
            decision = "submit_live"
            reason = "live_trade_approved"
        elif rejected:
            reason = rejected[0]["reason"]
        else:
            reason = "no_live_eligible_proposals"

    result = {
        "approved_trades": len(approved),
        "rejected_trades": len(rejected),
        "decision": decision,
        "reason": reason,
        "watch_candidates": len(proposals),
        "proposal_candidates": len(proposals),
        "decision_policy": "independent_live_env_dials",
        "submitted_paper_follow_candidates": 0,
        "open_positions": open_positions,
        "open_orders": open_orders,
        "available_slots": available_slots,
        "base_max_open_positions": int(config.live_execution_max_open_positions),
        "effective_max_open_positions": effective_max_positions,
        "earned_slots": int(slot_policy["earned_slots"]),
        "earned_slot_pnl_usd": slot_policy["total_pnl_usd"],
    }
    if unmanaged_live_symbols:
        result["unmanaged_live_positions"] = unmanaged_live_symbols
        result["unmanaged_live_position_count"] = len(unmanaged_live_symbols)
    if approved:
        result["approved_symbols"] = [item["symbol"] for item in approved]
        result["approved_strategy"] = approved[0]["strategy_id"]
        result["approved_broker"] = approved[0]["broker_id"]
    if rejected:
        result["rejection_reason"] = rejected[0]["reason"]
    context.state["live_risk_cfo"] = {
        **result,
        "approved_order_requests": approved,
        "rejected_candidates": rejected,
    }
    return result


def _unmanaged_live_position_symbols(context: TickContext) -> list[str]:
    """Return live positions that lack a persisted managed-exit entry plan.

    Independent live entries still must not add real-money exposure while any
    existing live position lacks an auditable stop/target/holding policy. This
    entry gate is intentionally conservative and leaves sell exits available
    when a managed plan exists.
    """
    positions = list(context.state.get("alpaca_live_positions", {}).get("raw", []))
    if not positions:
        return []
    list_orders = getattr(
        context.usage_ledger,
        "list_recent_execution_lane_trade_orders",
        None,
    )
    if list_orders is None:
        return [
            str(position.get("symbol", "")).upper()
            for position in positions
            if str(position.get("symbol", "")).strip()
        ]
    recent_orders = list(list_orders(limit=LIVE_ENTRY_PLAN_AUDIT_ORDER_LIMIT))
    missing: list[str] = []
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue
        broker_id = (
            str(position.get("broker_id", "alpaca_live")).strip().lower()
            or "alpaca_live"
        )
        entry_order = _find_most_protective_managed_entry_order(
            symbol=symbol,
            orders=recent_orders,
            broker_id=broker_id,
        )
        if entry_order is None:
            missing.append(symbol)
    return sorted(set(missing))
