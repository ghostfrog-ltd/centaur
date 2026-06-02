"""Heartbeat step implementation owned by `13_market_gate`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _account_trade_ready,
    _broker_equity_market_snapshots,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Build the account/market readiness snapshot used by scan and CFO gates."""
    account = context.state["alpaca_account"]["summary"]
    clock = context.state["alpaca_clock"]["summary"]
    is_open = bool(clock["is_open"])
    account_status = str(account.get("status", "")).upper()
    account_active = account_status == "ACTIVE"
    account_trade_ready, account_ready_reason = _account_trade_ready(account)
    equity_scan_ready = account_trade_ready and is_open
    crypto_scan_ready = account_trade_ready and bool(context.config.discovery_crypto_symbols)
    can_scan = equity_scan_ready or crypto_scan_ready
    if not account_trade_ready:
        reason = account_ready_reason
    elif equity_scan_ready:
        reason = "market_open"
    elif crypto_scan_ready:
        reason = "crypto_only_window"
    else:
        reason = "market_closed"

    if not account_trade_ready:
        equity_reason = account_ready_reason
        crypto_reason = account_ready_reason
    else:
        equity_reason = "market_open" if equity_scan_ready else "market_closed"
        crypto_reason = "crypto_open" if crypto_scan_ready else "crypto_unavailable"

    result = {
        "can_scan": can_scan,
        "reason": reason,
        "market_open": is_open,
        "account_active": account_active,
        "account_status": account.get("status"),
        "account_trade_ready": account_trade_ready,
        "next_open": clock.get("next_open"),
        "next_close": clock.get("next_close"),
        "equity_scan_ready": equity_scan_ready,
        "equity_reason": equity_reason,
        "crypto_scan_ready": crypto_scan_ready,
        "crypto_reason": crypto_reason,
        "broker_equity_markets": _broker_equity_market_snapshots(
            context=context,
            account_trade_ready=account_trade_ready,
            account_ready_reason=account_ready_reason,
            alpaca_market_open=is_open,
            alpaca_clock=clock,
        ),
    }
    context.state["market_gate"] = result
    return result
