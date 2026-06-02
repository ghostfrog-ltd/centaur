"""Heartbeat step implementation owned by `08_risk_daily_protection`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _as_float,
    _current_market_session,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Persist the paper daily drawdown latch before any new entry decision.

    This protects the fixed micro-capital envelope by preserving the first
    session baseline and keeping the protected state durable once the configured
    loss limit is reached. CFO reads this state; the protector itself does not
    size trades or choose strategies.
    """
    account = context.state["alpaca_account"]["summary"]
    current_equity = _as_float(account.get("equity"))
    if current_equity is None or current_equity <= 0:
        result = {
            "system_status": "unknown",
            "entries_blocked": False,
            "reason": "equity_unavailable",
        }
        context.state["daily_protection"] = result
        return result

    session_date, market_open_at = _current_market_session(
        started_at=context.started_at,
        market_timezone=context.config.market_timezone,
    )
    existing = context.usage_ledger.get_daily_protection_state(session_date=session_date)
    baseline_equity = _as_float(existing.get("baseline_equity")) if existing else current_equity
    if baseline_equity is None or baseline_equity <= 0:
        baseline_equity = current_equity
    equity_drawdown_usd = max(0.0, baseline_equity - current_equity)
    protection_already_active = str(existing.get("system_status", "")).lower() == "protected" if existing else False
    system_status = (
        "protected"
        if protection_already_active
        or equity_drawdown_usd >= float(context.config.paper_execution_max_daily_drawdown_usd)
        else "active"
    )
    notes = "daily_drawdown_limit_reached" if system_status == "protected" else ""
    row = context.usage_ledger.upsert_daily_protection_state(
        session_date=session_date,
        market_open_at=market_open_at,
        tick_id=context.tick_id,
        checked_at=context.started_at,
        current_equity=current_equity,
        max_daily_drawdown_usd=context.config.paper_execution_max_daily_drawdown_usd,
        system_status=system_status,
        notes=notes,
    )
    result = {
        "session_date": row.get("session_date"),
        "market_open_at": row.get("market_open_at"),
        "baseline_equity": _as_float(row.get("baseline_equity")),
        "current_equity": _as_float(row.get("latest_equity")),
        "equity_drawdown_usd": _as_float(row.get("equity_drawdown_usd")) or 0.0,
        "max_daily_drawdown_usd": _as_float(row.get("max_daily_drawdown_usd")) or 0.0,
        "system_status": str(row.get("system_status", "active")).lower(),
        "entries_blocked": str(row.get("system_status", "active")).lower() == "protected",
        "baseline_created": existing is None,
        "stale_orders_reaped_count": int(row.get("stale_orders_reaped_count", 0) or 0),
    }
    if row.get("protection_triggered_at") is not None:
        result["protection_triggered_at"] = row.get("protection_triggered_at")
    context.state["daily_protection"] = {**result, "raw": row}
    return result
