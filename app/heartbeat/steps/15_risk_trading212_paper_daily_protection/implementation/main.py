"""Heartbeat step implementation owned by `15_risk_trading212_paper_daily_protection`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _as_float,
    _current_market_session,
    _native_equity_to_usd,
    _paper_trading212_enabled,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Latch the Trading 212 paper daily protector in USD-equivalent terms."""
    if not _paper_trading212_enabled(context):
        result = {
            "system_status": "skipped",
            "entries_blocked": True,
            "reason": "trading212_paper_execution_disabled",
            "max_daily_drawdown_usd": float(context.config.paper_execution_max_daily_drawdown_usd),
        }
        context.state["trading212_paper_daily_protection"] = result
        return result

    account_state = context.state.get("trading212_paper_account", {})
    summary = account_state.get("summary", {}) if isinstance(account_state, dict) else {}
    equity_native = _as_float(summary.get("equity"))
    usd_to_gbp = _as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp"))
    current_equity_usd = _native_equity_to_usd(
        equity_native,
        currency=str(summary.get("currency", "GBP")),
        usd_to_gbp=usd_to_gbp,
    )
    max_drawdown = float(context.config.paper_execution_max_daily_drawdown_usd)
    if current_equity_usd is None or current_equity_usd <= 0:
        result = {
            "system_status": "unknown",
            "entries_blocked": True,
            "reason": "trading212_paper_equity_unavailable",
            "max_daily_drawdown_usd": max_drawdown,
        }
        context.state["trading212_paper_daily_protection"] = result
        return result

    session_date, market_open_at = _current_market_session(
        started_at=context.started_at,
        market_timezone=context.config.market_timezone,
    )
    broker_id = "trading212_paper"
    existing = context.usage_ledger.get_broker_daily_protection_state(
        session_date=session_date,
        broker_id=broker_id,
    )
    baseline_equity = _as_float(existing.get("baseline_equity")) if existing else None
    if baseline_equity is None or baseline_equity <= 0:
        baseline_equity = current_equity_usd
    equity_drawdown_usd = max(0.0, baseline_equity - current_equity_usd)
    protection_already_active = (
        str(existing.get("system_status", "")).lower() == "protected"
        if existing
        else False
    )
    protected = protection_already_active or equity_drawdown_usd >= max_drawdown
    notes = "daily_drawdown_limit_reached" if protected else ""
    row = context.usage_ledger.upsert_broker_daily_protection_state(
        session_date=session_date,
        broker_id=broker_id,
        market_open_at=market_open_at,
        tick_id=context.tick_id,
        checked_at=context.started_at,
        current_equity=current_equity_usd,
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
        "native_equity": equity_native,
        "native_currency": str(summary.get("currency", "GBP")),
        "reason": "daily_drawdown_limit_reached" if protected else "active",
    }
    if row.get("protection_triggered_at") is not None:
        result["protection_triggered_at"] = row.get("protection_triggered_at")
    context.state["trading212_paper_daily_protection"] = {**result, "raw": row}
    return result
