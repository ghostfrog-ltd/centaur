"""Heartbeat step implementation owned by `09_risk_live_daily_protection`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _as_float,
    _current_market_session,
    _live_runtime_allows_broker_reads,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Persist and latch Alpaca Live daily drawdown protection by session.

    Paper already has a durable daily protector; live readiness needs the same
    audit trail so a future real-money lane cannot reset its baseline mid-session
    or forget that protection has already triggered.
    """
    if not _live_runtime_allows_broker_reads(context):
        result = {
            "system_status": "skipped",
            "entries_blocked": True,
            "reason": "runtime_mode_not_live",
            "max_daily_drawdown_usd": float(
                context.config.live_execution_max_daily_drawdown_usd
            ),
        }
        context.state["live_daily_protection"] = result
        return result

    account_state = context.state.get("alpaca_live_account", {})
    summary = account_state.get("summary", {}) if isinstance(account_state, dict) else {}
    current_equity = _as_float(summary.get("equity"))
    max_drawdown = float(context.config.live_execution_max_daily_drawdown_usd)
    if current_equity is None or current_equity <= 0:
        result = {
            "system_status": "unknown",
            "entries_blocked": True,
            "reason": "live_equity_unavailable",
            "max_daily_drawdown_usd": max_drawdown,
        }
        context.state["live_daily_protection"] = result
        return result

    session_date, market_open_at = _current_market_session(
        started_at=context.started_at,
        market_timezone=context.config.market_timezone,
    )
    existing = context.usage_ledger.get_broker_daily_protection_state(
        session_date=session_date,
        broker_id="alpaca_live",
    )
    baseline_equity = _as_float(existing.get("baseline_equity")) if existing else None
    if baseline_equity is None or baseline_equity <= 0:
        baseline_equity = current_equity
    equity_drawdown_usd = max(0.0, baseline_equity - current_equity)
    protection_already_active = (
        str(existing.get("system_status", "")).lower() == "protected"
        if existing
        else False
    )
    protected = protection_already_active or equity_drawdown_usd >= max_drawdown
    notes = "daily_drawdown_limit_reached" if protected else ""
    row = context.usage_ledger.upsert_broker_daily_protection_state(
        session_date=session_date,
        broker_id="alpaca_live",
        market_open_at=market_open_at,
        tick_id=context.tick_id,
        checked_at=context.started_at,
        current_equity=current_equity,
        max_daily_drawdown_usd=max_drawdown,
        system_status="protected" if protected else "active",
        notes=notes,
    )
    result = {
        "session_date": row.get("session_date"),
        "market_open_at": row.get("market_open_at"),
        "baseline_equity": _as_float(row.get("baseline_equity")),
        "current_equity": _as_float(row.get("latest_equity")),
        "equity_drawdown_usd": _as_float(row.get("equity_drawdown_usd")) or 0.0,
        "max_daily_drawdown_usd": _as_float(row.get("max_daily_drawdown_usd")) or max_drawdown,
        "system_status": str(row.get("system_status", "active")).lower(),
        "entries_blocked": str(row.get("system_status", "active")).lower() == "protected",
        "baseline_created": existing is None,
        "stale_orders_reaped_count": int(row.get("stale_orders_reaped_count", 0) or 0),
        "reason": "daily_drawdown_limit_reached" if protected else "active",
    }
    if row.get("protection_triggered_at") is not None:
        result["protection_triggered_at"] = row.get("protection_triggered_at")
    context.state["live_daily_protection"] = {**result, "raw": row}
    return result
