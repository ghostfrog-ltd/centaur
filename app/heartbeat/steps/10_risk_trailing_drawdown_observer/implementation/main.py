"""Heartbeat step implementation owned by `10_risk_trailing_drawdown_observer`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    PipelineResult,
    TickContext,
    _account_state_key_for_broker,
    _build_trailing_drawdown_observation,
    _current_market_session,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Record high-water drawdown evidence without changing trading gates.

    This is a shadow risk rule: it measures whether a future trailing giveback
    guard would have blocked new entries, but it deliberately does not latch
    protection, cancel orders, submit exits, or alter paper/live CFO decisions.
    """
    config = context.config
    session_date, session_open_at = _current_market_session(
        started_at=context.started_at,
        market_timezone=config.market_timezone,
    )
    result: dict[str, Any] = {
        "mode": "observe_only",
        "enabled": bool(config.trailing_drawdown_observer_enabled),
        "affects_execution": False,
        "entries_blocked": False,
        "session_date": session_date.isoformat(),
        "session_open_at": session_open_at,
        "lanes": {},
        "any_would_block_new_entries": False,
    }
    if not config.trailing_drawdown_observer_enabled:
        result["mode"] = "disabled"
        context.state["trailing_drawdown_observer"] = result
        return result

    paper_brokers = {
        str(config.paper_execution_equity_broker_id or "").strip().lower(),
        str(config.paper_execution_crypto_broker_id or "").strip().lower(),
    }
    live_brokers = {
        str(config.live_execution_equity_broker_id or "").strip().lower(),
        str(config.live_execution_crypto_broker_id or "").strip().lower(),
    }
    lanes: dict[str, Any] = {}
    for broker_id in sorted(broker for broker in paper_brokers if broker):
        lanes[broker_id] = _build_trailing_drawdown_observation(
            context=context,
            broker_id=broker_id,
            account_state_key=_account_state_key_for_broker(broker_id),
            session_open_at=session_open_at,
            threshold_usd=float(config.trailing_drawdown_observer_paper_giveback_usd),
            threshold_pct=float(config.trailing_drawdown_observer_paper_giveback_pct),
        )
    for broker_id in sorted(broker for broker in live_brokers if broker):
        lanes[broker_id] = _build_trailing_drawdown_observation(
            context=context,
            broker_id=broker_id,
            account_state_key=_account_state_key_for_broker(broker_id),
            session_open_at=session_open_at,
            threshold_usd=float(config.trailing_drawdown_observer_live_giveback_usd),
            threshold_pct=float(config.trailing_drawdown_observer_live_giveback_pct),
        )
    result["lanes"] = lanes
    result["any_would_block_new_entries"] = any(
        bool(lane.get("would_block_new_entries"))
        for lane in lanes.values()
        if isinstance(lane, dict)
    )
    context.state["trailing_drawdown_observer"] = result
    return result
