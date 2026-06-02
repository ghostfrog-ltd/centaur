"""Heartbeat step implementation owned by `28_risk_cfo`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    PipelineResult,
    TickContext,
    _account_state_key_for_broker,
    _active_paper_broker_ids,
    _build_paper_trade_approval,
    _earned_slot_policy,
    _orders_state_key_for_broker,
    _paper_lane_position_state,
    _paper_protection_state_key_for_broker,
    _slot_size_native_for_broker,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Approve at most the configured micro paper entries after all risk gates.

    The CFO gate is the paper capital-preservation choke point: it combines the
    kill switch, durable daily protection, account readiness, earned slots,
    duplicate-symbol checks, strategy allowlist, broker validation, and projected
    gain floor before an order request can reach execution.
    """
    config = context.config
    gate = context.state["market_gate"]
    protection = context.state.get("daily_protection", {})
    proposals = list(context.state.get("shadow_trade_proposals", {}).get("proposals", []))
    paper_brokers = _active_paper_broker_ids(context)
    recent_trade_orders: list[dict[str, Any]] = []
    if "trading212_paper" in paper_brokers:
        list_recent_orders = getattr(
            context.usage_ledger,
            "list_recent_execution_lane_trade_orders",
            None,
        )
        if callable(list_recent_orders):
            recent_trade_orders = list_recent_orders(limit=500)
    lane_results: dict[str, dict[str, Any]] = {}
    total_open_positions = 0
    total_open_orders = 0
    total_available_slots = 0
    decision = "hold"
    reason = "paper_execution_disabled"
    rejected: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []

    if config.paper_execution_kill_switch:
        reason = "paper_kill_switch_on"
    elif not config.paper_execution_enabled:
        reason = "paper_execution_disabled"
    elif str(protection.get("system_status", "active")).lower() == "protected":
        reason = "daily_drawdown_limit_reached"
    elif not gate["account_trade_ready"]:
        reason = gate["reason"]
    elif not proposals:
        reason = "no_shadow_proposals"
    else:
        allowed_strategies = {
            strategy_id.lower()
            for strategy_id in config.paper_execution_allowed_strategies
            if strategy_id
        }
        for broker_id in paper_brokers:
            position_state = _paper_lane_position_state(
                context,
                broker_id,
                recent_orders=recent_trade_orders,
            )
            orders_summary = context.state.get(
                _orders_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            open_positions = int(position_state.get("open_positions", 0) or 0)
            open_orders = int(orders_summary.get("open_orders", 0) or 0)
            total_open_positions += open_positions
            total_open_orders += open_orders
            occupied_slots = open_positions + open_orders
            slot_policy = _earned_slot_policy(
                context=context,
                broker_id=broker_id,
                account_state_key=_account_state_key_for_broker(broker_id),
                base_max_positions=int(config.paper_execution_max_open_positions),
                slot_size_usd=_slot_size_native_for_broker(context, broker_id),
            )
            effective_max_positions = int(slot_policy["effective_max_open_positions"])
            available_slots = max(0, effective_max_positions - occupied_slots)
            total_available_slots += available_slots
            protection_state = context.state.get(
                _paper_protection_state_key_for_broker(broker_id),
                {},
            )
            lane_results[broker_id] = {
                "open_positions": open_positions,
                "open_orders": open_orders,
                "available_slots": available_slots,
                "base_max_open_positions": int(config.paper_execution_max_open_positions),
                "effective_max_open_positions": effective_max_positions,
                "earned_slots": int(slot_policy["earned_slots"]),
                "earned_slot_pnl": slot_policy["total_pnl_usd"],
                "approved_trades": 0,
                "rejected_trades": 0,
                "reason": "pending",
            }
            if int(position_state.get("price_seed_positions", 0) or 0) > 0:
                lane_results[broker_id]["price_seed_positions"] = int(
                    position_state.get("price_seed_positions", 0) or 0
                )
                lane_results[broker_id]["price_seed_symbols"] = sorted(
                    position_state.get("price_seed_symbols", set())
                )
            if str(protection_state.get("system_status", "active")).lower() == "protected":
                lane_results[broker_id]["reason"] = "daily_drawdown_limit_reached"
                rejected.append(
                    {
                        "symbol": "",
                        "broker_id": broker_id,
                        "strategy_id": "",
                        "reason": "daily_drawdown_limit_reached",
                    }
                )
                continue
            if available_slots <= 0:
                lane_results[broker_id]["reason"] = "max_open_positions_reached"
                rejected.append(
                    {
                        "symbol": "",
                        "broker_id": broker_id,
                        "strategy_id": "",
                        "reason": "max_open_positions_reached",
                    }
                )
                continue
            position_symbols = set(position_state.get("symbols", set()))
            open_order_symbols = {
                str(symbol).upper()
                for symbol in orders_summary.get("open_order_symbols", [])
                if symbol
            }
            for proposal in proposals:
                if broker_id == "trading212_paper" and str(proposal.get("asset_class", "")).lower() != "equity":
                    continue
                approval, rejection = _build_paper_trade_approval(
                    context=context,
                    proposal=proposal,
                    tick_id=context.tick_id,
                    config=config,
                    market_gate=gate,
                    position_symbols=position_symbols,
                    open_order_symbols=open_order_symbols,
                    broker_id=broker_id,
                )
                if rejection is not None:
                    rejected.append(rejection)
                    lane_results[broker_id]["rejected_trades"] += 1
                    continue
                if approval is None:
                    continue
                strategy_id = str(approval.get("strategy_id", "")).lower()
                if allowed_strategies and strategy_id not in allowed_strategies:
                    rejected.append(
                        {
                            "symbol": approval["symbol"],
                            "broker_id": approval["broker_id"],
                            "strategy_id": approval["strategy_id"],
                            "reason": "strategy_not_allowed",
                        }
                    )
                    lane_results[broker_id]["rejected_trades"] += 1
                    continue
                approved.append(approval)
                lane_results[broker_id]["approved_trades"] += 1
                if lane_results[broker_id]["approved_trades"] >= min(
                    config.paper_execution_max_orders_per_tick,
                    available_slots,
                ):
                    break
            if lane_results[broker_id]["approved_trades"]:
                lane_results[broker_id]["reason"] = "paper_trade_approved"
            elif lane_results[broker_id]["rejected_trades"]:
                lane_results[broker_id]["reason"] = "no_paper_eligible_proposals"
            else:
                lane_results[broker_id]["reason"] = "no_paper_eligible_proposals"

        if approved:
            decision = "submit_paper"
            reason = "paper_trade_approved"
        elif rejected:
            reason = rejected[0]["reason"]
        else:
            reason = "no_paper_eligible_proposals"

    if not lane_results:
        for broker_id in paper_brokers:
            position_state = _paper_lane_position_state(
                context,
                broker_id,
                recent_orders=recent_trade_orders,
            )
            orders_summary = context.state.get(
                _orders_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            open_positions = int(position_state.get("open_positions", 0) or 0)
            open_orders = int(orders_summary.get("open_orders", 0) or 0)
            total_open_positions += open_positions
            total_open_orders += open_orders
            slot_policy = _earned_slot_policy(
                context=context,
                broker_id=broker_id,
                account_state_key=_account_state_key_for_broker(broker_id),
                base_max_positions=int(config.paper_execution_max_open_positions),
                slot_size_usd=_slot_size_native_for_broker(context, broker_id),
            )
            effective_max_positions = int(slot_policy["effective_max_open_positions"])
            available_slots = max(0, effective_max_positions - open_positions - open_orders)
            total_available_slots += available_slots
            lane_results[broker_id] = {
                "open_positions": open_positions,
                "open_orders": open_orders,
                "available_slots": available_slots,
                "base_max_open_positions": int(config.paper_execution_max_open_positions),
                "effective_max_open_positions": effective_max_positions,
                "earned_slots": int(slot_policy["earned_slots"]),
                "earned_slot_pnl": slot_policy["total_pnl_usd"],
                "approved_trades": 0,
                "rejected_trades": 0,
                "reason": reason,
            }
            if int(position_state.get("price_seed_positions", 0) or 0) > 0:
                lane_results[broker_id]["price_seed_positions"] = int(
                    position_state.get("price_seed_positions", 0) or 0
                )
                lane_results[broker_id]["price_seed_symbols"] = sorted(
                    position_state.get("price_seed_symbols", set())
                )

    result = {
        "approved_trades": len(approved),
        "rejected_trades": len(rejected),
        "decision": decision,
        "reason": reason,
        "watch_candidates": len(proposals),
        "open_positions": total_open_positions,
        "open_orders": total_open_orders,
        "available_slots": total_available_slots,
        "base_max_open_positions": int(config.paper_execution_max_open_positions),
        "effective_max_open_positions": sum(
            int(lane.get("effective_max_open_positions", 0) or 0)
            for lane in lane_results.values()
        ),
        "earned_slots": sum(
            int(lane.get("earned_slots", 0) or 0) for lane in lane_results.values()
        ),
        "earned_slot_pnl_usd": 0.0,
        "broker_lanes": lane_results,
    }
    if approved:
        result["approved_symbols"] = [item["symbol"] for item in approved]
        result["approved_strategy"] = approved[0]["strategy_id"]
        result["approved_broker"] = approved[0]["broker_id"]
    if rejected:
        result["rejection_reason"] = rejected[0]["reason"]
    context.state["risk_cfo"] = {
        **result,
        "approved_order_requests": approved,
        "rejected_candidates": rejected,
    }
    return result
