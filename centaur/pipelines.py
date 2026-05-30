from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .alpaca import (
    get_alpaca_client,
    summarize_latest_bars,
)
from .brokers import BrokerAdapterError, get_broker_adapter
from .discovery import rank_candidates
from .fitness import allocate_strategy_signals, enrich_strategy_fitness_rows
from .fx import EcbReferenceRateClient, rate_is_stale
from .gemini import GeminiApiError, get_gemini_client
from .models import TickContext
from .shadow import build_shadow_proposals, evaluate_shadow_checkpoint
from .strategies import evaluate_strategies
from .technicals import (
    build_live_bar_row,
    compute_volatility_breakout_context,
    merge_bar_rows,
)
from .threshold_advisor import ThresholdAdvisor

PipelineResult = dict[str, Any]
PipelineRunner = Callable[[TickContext], PipelineResult]


def _paper_min_projected_gain_pct(config: Any, asset_class: str) -> float:
    asset = str(asset_class).strip().lower()
    if asset == "crypto":
        return float(config.paper_execution_crypto_min_projected_gain_pct)
    return float(config.paper_execution_min_projected_gain_pct)


def _paper_limit_buffer_bps(config: Any, asset_class: str) -> float:
    asset = str(asset_class).strip().lower()
    if asset == "crypto":
        return float(
            getattr(
                config,
                "paper_execution_crypto_limit_buffer_bps",
                config.paper_execution_limit_buffer_bps,
            )
        )
    return float(config.paper_execution_limit_buffer_bps)


def _live_min_projected_gain_pct(config: Any, asset_class: str) -> float:
    asset = str(asset_class).strip().lower()
    if asset == "crypto":
        return float(
            getattr(
                config,
                "live_execution_crypto_min_projected_gain_pct",
                config.live_execution_min_projected_gain_pct,
            )
        )
    return float(config.live_execution_min_projected_gain_pct)


def _live_limit_buffer_bps(config: Any, asset_class: str) -> float:
    asset = str(asset_class).strip().lower()
    if asset == "crypto":
        return float(
            getattr(
                config,
                "live_execution_crypto_limit_buffer_bps",
                config.live_execution_limit_buffer_bps,
            )
        )
    return float(config.live_execution_limit_buffer_bps)


def _paper_allocation_suppress_thresholds(
    context: TickContext,
    *,
    equity_threshold: float,
) -> dict[str, float]:
    return {
        "equity": float(equity_threshold),
        "crypto": float(context.config.strategy_allocation_crypto_suppress_threshold),
    }


@dataclass(frozen=True, slots=True)
class StepDefinition:
    name: str
    runner: PipelineRunner


def control_heartbeat(context: TickContext) -> PipelineResult:
    heartbeat = {
        "status": "alive",
        "tick_id": context.tick_id,
        "timezone": context.started_at.astimezone().tzname(),
    }
    context.state["heartbeat"] = heartbeat
    return heartbeat


def alpaca_account(context: TickContext) -> PipelineResult:
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_account = {
        **adapter.get_account(context),
        "broker_id": adapter.broker_id,
    }
    summary = adapter.summarize_account(raw_account)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_account,
    }
    context.state["alpaca_account"] = payload
    context.state["execution_account"] = payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = payload
    return {
        "broker_id": adapter.broker_id,
        **summary,
    }


def alpaca_clock(context: TickContext) -> PipelineResult:
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_clock = {
        **adapter.get_clock(context),
        "broker_id": adapter.broker_id,
    }
    summary = adapter.summarize_clock(raw_clock)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_clock,
    }
    context.state["alpaca_clock"] = payload
    context.state["execution_clock"] = payload
    return {
        "broker_id": adapter.broker_id,
        **summary,
    }


def alpaca_positions(context: TickContext) -> PipelineResult:
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_positions = [
        {
            **position,
            "broker_id": adapter.broker_id,
        }
        for position in adapter.get_positions(context)
    ]
    summary = adapter.summarize_positions(raw_positions)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_positions,
    }
    context.state["alpaca_positions"] = payload
    context.state["execution_positions"] = payload
    snapshot_saved = 0
    account_payload = context.state.get("alpaca_account")
    if isinstance(account_payload, dict):
        account_summary = account_payload.get("summary")
        raw_account = account_payload.get("raw")
        if isinstance(account_summary, dict) and isinstance(raw_account, dict):
            context.usage_ledger.record_broker_account_snapshot(
                tick_id=context.tick_id,
                captured_at=context.started_at,
                broker_id=adapter.broker_id,
                summary=account_summary,
                raw_account=raw_account,
                positions=raw_positions,
            )
            snapshot_saved = 1
    return {
        "broker_id": adapter.broker_id,
        "account_snapshot_saved": snapshot_saved,
        **summary,
    }


def alpaca_orders(context: TickContext) -> PipelineResult:
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_orders = [
        {
            **order,
            "broker_id": adapter.broker_id,
        }
        for order in adapter.get_orders(
            context,
            status="all",
            after=context.started_at - timedelta(days=7),
            limit=100,
            nested=True,
        )
    ]
    orders_saved = context.usage_ledger.record_paper_trade_orders(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        orders=raw_orders,
        broker_id=adapter.broker_id,
    )
    summary = adapter.summarize_orders(raw_orders)
    result = {
        "broker_id": adapter.broker_id,
        **summary,
        "orders_saved": orders_saved,
        "mode": "recent_orders",
    }
    payload = {
        "broker_id": adapter.broker_id,
        "summary": result,
        "raw": raw_orders,
    }
    context.state["alpaca_orders"] = payload
    context.state["execution_orders"] = payload
    return result


def alpaca_live_sync(context: TickContext) -> PipelineResult:
    if not context.config.alpaca_live_api_configured:
        result = {
            "broker_id": "alpaca_live",
            "mode": "skipped",
            "reason": "alpaca_live_credentials_missing",
        }
        context.state["alpaca_live_account"] = {
            "broker_id": "alpaca_live",
            "summary": {},
            "raw": {},
        }
        context.state["alpaca_live_positions"] = {
            "broker_id": "alpaca_live",
            "summary": {"open_positions": 0, "symbols": []},
            "raw": [],
        }
        context.state["alpaca_live_orders"] = {
            "broker_id": "alpaca_live",
            "summary": {"open_orders": 0, "open_order_symbols": []},
            "raw": [],
        }
        return result

    adapter = get_broker_adapter(context, "alpaca_live")
    raw_account = {
        **adapter.get_account(context),
        "broker_id": adapter.broker_id,
    }
    account_summary = adapter.summarize_account(raw_account)
    raw_positions = [
        {
            **position,
            "broker_id": adapter.broker_id,
        }
        for position in adapter.get_positions(context)
    ]
    positions_summary = adapter.summarize_positions(raw_positions)
    raw_orders = [
        {
            **order,
            "broker_id": adapter.broker_id,
        }
        for order in adapter.get_orders(
            context,
            status="all",
            after=context.started_at - timedelta(days=7),
            limit=100,
            nested=True,
        )
    ]
    orders_saved = context.usage_ledger.record_paper_trade_orders(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        orders=raw_orders,
        broker_id=adapter.broker_id,
    )
    orders_summary = adapter.summarize_orders(raw_orders)
    context.usage_ledger.record_broker_account_snapshot(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        broker_id=adapter.broker_id,
        summary=account_summary,
        raw_account=raw_account,
        positions=raw_positions,
    )
    account_payload = {
        "broker_id": adapter.broker_id,
        "summary": account_summary,
        "raw": raw_account,
    }
    context.state["alpaca_live_account"] = account_payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = account_payload
    context.state["alpaca_live_positions"] = {
        "broker_id": adapter.broker_id,
        "summary": positions_summary,
        "raw": raw_positions,
    }
    context.state["alpaca_live_orders"] = {
        "broker_id": adapter.broker_id,
        "summary": orders_summary,
        "raw": raw_orders,
    }
    return {
        "broker_id": adapter.broker_id,
        "mode": "synced",
        "orders_saved": orders_saved,
        "open_positions": positions_summary.get("open_positions", 0),
        "open_orders": orders_summary.get("open_orders", 0),
        "equity": account_summary.get("equity"),
        "cash": account_summary.get("cash"),
    }


def daily_protection(context: TickContext) -> PipelineResult:
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


def live_daily_protection(context: TickContext) -> PipelineResult:
    """Persist and latch Alpaca Live daily drawdown protection by session.

    Paper already has a durable daily protector; live readiness needs the same
    audit trail so a future real-money lane cannot reset its baseline mid-session
    or forget that protection has already triggered.
    """
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


def stale_order_reaper(context: TickContext) -> PipelineResult:
    raw_orders = list(context.state.get("alpaca_orders", {}).get("raw", []))
    stale_after_minutes = max(1, int(context.config.paper_execution_stale_order_minutes))
    if not raw_orders:
        result = {
            "mode": "idle",
            "orders_checked": 0,
            "stale_candidates": 0,
            "orders_canceled": 0,
        }
        context.state["stale_order_reaper"] = {**result, "canceled_orders": [], "errors": []}
        return result

    canceled_orders: list[dict[str, Any]] = []
    cancel_errors: list[dict[str, Any]] = []
    stale_candidates: list[dict[str, Any]] = []
    updated_orders: list[dict[str, Any]] = []

    for order in raw_orders:
        symbol = str(order.get("symbol", "")).upper()
        broker_id = str(order.get("broker_id", "alpaca_paper")).strip().lower() or "alpaca_paper"
        if not _is_stale_entry_order(
            order=order,
            as_of=context.started_at,
            stale_after_minutes=stale_after_minutes,
        ):
            updated_orders.append(order)
            continue
        stale_candidates.append(
            {
                "symbol": symbol,
                "order_id": str(order.get("id", "")).strip(),
                "broker_id": broker_id,
            }
        )
        order_id = str(order.get("id", "")).strip()
        if not order_id:
            cancel_errors.append({"symbol": symbol, "error": "missing_order_id"})
            updated_orders.append(order)
            continue
        try:
            adapter = get_broker_adapter(context, broker_id)
            adapter.cancel_order(context, order_id=order_id)
            canceled_order = {
                **order,
                "status": "canceled",
                "updated_at": context.started_at.isoformat(),
            }
            canceled_orders.append(canceled_order)
            updated_orders.append(canceled_order)
        except BrokerAdapterError as exc:
            cancel_errors.append({"symbol": symbol, "error": str(exc)})
            updated_orders.append(order)

    orders_saved = 0
    if canceled_orders:
        orders_saved = context.usage_ledger.record_paper_trade_orders(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            orders=canceled_orders,
            broker_id="alpaca_paper",
        )
        protection = context.state.get("daily_protection", {})
        session_date = protection.get("session_date")
        if session_date:
            stale_count = context.usage_ledger.increment_daily_stale_order_count(
                session_date=date.fromisoformat(str(session_date)),
                tick_id=context.tick_id,
                checked_at=context.started_at,
                count=len(canceled_orders),
            )
            if isinstance(protection, dict):
                protection["stale_orders_reaped_count"] = stale_count
                if isinstance(protection.get("raw"), dict):
                    protection["raw"]["stale_orders_reaped_count"] = stale_count

    prior_summary = context.state.get("alpaca_orders", {}).get("summary", {})
    revised_summary = get_broker_adapter(context, "alpaca_paper").summarize_orders(updated_orders)
    context.state["alpaca_orders"] = {
        "summary": {
            **revised_summary,
            "orders_saved": int(prior_summary.get("orders_saved", 0) or 0) + orders_saved,
            "mode": str(prior_summary.get("mode", "recent_orders")),
        },
        "raw": updated_orders,
    }

    result = {
        "mode": "monitoring",
        "orders_checked": len(raw_orders),
        "stale_candidates": len(stale_candidates),
        "orders_canceled": len(canceled_orders),
        "orders_saved": orders_saved,
        "stale_after_minutes": stale_after_minutes,
    }
    if stale_candidates:
        result["first_stale_symbol"] = stale_candidates[0]["symbol"]
    if cancel_errors:
        result["error_count"] = len(cancel_errors)
        result["first_error"] = cancel_errors[0]["error"]
    context.state["stale_order_reaper"] = {
        **result,
        "canceled_orders": canceled_orders,
        "errors": cancel_errors,
        "stale_candidates_detail": stale_candidates,
    }
    return result


def live_stale_order_reaper(context: TickContext) -> PipelineResult:
    """Cancel stale untouched live equity entry limits after activation gates.

    This mirrors the paper stale-order reaper for the future live lane. It only
    targets unfilled equity buy limits, records the cancellation in the order
    audit trail, and relies on the live adapter to enforce credentials and
    activation acknowledgement before any live account mutation.
    """
    raw_orders = list(context.state.get("alpaca_live_orders", {}).get("raw", []))
    stale_after_minutes = max(1, int(context.config.paper_execution_stale_order_minutes))
    if not raw_orders:
        result = {
            "broker": "alpaca_live",
            "mode": "idle",
            "orders_checked": 0,
            "stale_candidates": 0,
            "orders_canceled": 0,
        }
        context.state["live_stale_order_reaper"] = {
            **result,
            "canceled_orders": [],
            "errors": [],
        }
        return result

    canceled_orders: list[dict[str, Any]] = []
    cancel_errors: list[dict[str, Any]] = []
    stale_candidates: list[dict[str, Any]] = []
    updated_orders: list[dict[str, Any]] = []

    for order in raw_orders:
        symbol = str(order.get("symbol", "")).upper()
        if not _is_stale_entry_order(
            order=order,
            as_of=context.started_at,
            stale_after_minutes=stale_after_minutes,
        ):
            updated_orders.append(order)
            continue
        stale_candidates.append(
            {
                "symbol": symbol,
                "order_id": str(order.get("id", "")).strip(),
                "broker_id": "alpaca_live",
            }
        )
        order_id = str(order.get("id", "")).strip()
        if not order_id:
            cancel_errors.append({"symbol": symbol, "error": "missing_order_id"})
            updated_orders.append(order)
            continue
        try:
            adapter = get_broker_adapter(context, "alpaca_live")
            adapter.cancel_order(context, order_id=order_id)
            canceled_order = {
                **order,
                "broker_id": "alpaca_live",
                "status": "canceled",
                "updated_at": context.started_at.isoformat(),
            }
            canceled_orders.append(canceled_order)
            updated_orders.append(canceled_order)
        except BrokerAdapterError as exc:
            cancel_errors.append({"symbol": symbol, "error": str(exc)})
            updated_orders.append(order)

    orders_saved = 0
    if canceled_orders:
        orders_saved = context.usage_ledger.record_paper_trade_orders(
            tick_id=context.tick_id,
            captured_at=context.started_at,
            orders=canceled_orders,
            broker_id="alpaca_live",
        )
        protection = context.state.get("live_daily_protection", {})
        session_date = protection.get("session_date") if isinstance(protection, dict) else None
        if session_date:
            stale_count = context.usage_ledger.increment_broker_daily_stale_order_count(
                session_date=date.fromisoformat(str(session_date)),
                broker_id="alpaca_live",
                tick_id=context.tick_id,
                checked_at=context.started_at,
                count=len(canceled_orders),
            )
            if isinstance(protection, dict):
                protection["stale_orders_reaped_count"] = stale_count
                if isinstance(protection.get("raw"), dict):
                    protection["raw"]["stale_orders_reaped_count"] = stale_count

    prior_summary = context.state.get("alpaca_live_orders", {}).get("summary", {})
    revised_summary = get_broker_adapter(context, "alpaca_live").summarize_orders(updated_orders)
    context.state["alpaca_live_orders"] = {
        "summary": {
            **revised_summary,
            "orders_saved": int(prior_summary.get("orders_saved", 0) or 0) + orders_saved,
            "mode": str(prior_summary.get("mode", "recent_orders")),
        },
        "raw": updated_orders,
    }

    result = {
        "broker": "alpaca_live",
        "mode": "monitoring",
        "orders_checked": len(raw_orders),
        "stale_candidates": len(stale_candidates),
        "orders_canceled": len(canceled_orders),
        "orders_saved": orders_saved,
        "stale_after_minutes": stale_after_minutes,
    }
    if stale_candidates:
        result["first_stale_symbol"] = stale_candidates[0]["symbol"]
    if cancel_errors:
        result["error_count"] = len(cancel_errors)
        result["first_error"] = cancel_errors[0]["error"]
    context.state["live_stale_order_reaper"] = {
        **result,
        "canceled_orders": canceled_orders,
        "errors": cancel_errors,
        "stale_candidates_detail": stale_candidates,
    }
    return result


def _account_trade_ready(summary: dict[str, Any]) -> tuple[bool, str]:
    """Normalize Alpaca account readiness checks for paper and live gates."""
    status = str(summary.get("status", "")).upper()
    account_active = status == "ACTIVE"
    trading_blocked = bool(
        summary.get("trading_blocked") or summary.get("account_blocked")
    )
    user_suspended = bool(summary.get("trade_suspended_by_user"))
    if not account_active:
        return False, "account_not_active"
    if trading_blocked:
        return False, "account_blocked"
    if user_suspended:
        return False, "user_trade_suspension"
    return True, "account_trade_ready"


def market_gate(context: TickContext) -> PipelineResult:
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
        "equity_scan_ready": equity_scan_ready,
        "equity_reason": equity_reason,
        "crypto_scan_ready": crypto_scan_ready,
        "crypto_reason": crypto_reason,
    }
    context.state["market_gate"] = result
    return result


def fx_gbp_reference(context: TickContext) -> PipelineResult:
    cached = context.usage_ledger.get_latest_fx_reference(source="ecb_fx")
    if cached is not None and not rate_is_stale(
        fetched_at=cached["fetched_at"],
        cache_minutes=context.config.ecb_reference_cache_minutes,
    ):
        result = {
            "source": cached["source"],
            "provider_date": cached["provider_date"],
            "usd_to_gbp": round(float(cached["usd_to_gbp"]), 6),
            "gbp_to_usd": round(float(cached["gbp_to_usd"]), 6),
            "mode": "cache",
        }
        context.state["fx_gbp_reference"] = {**result, "raw": cached}
        return result

    if cached is not None:
        try:
            fetched = EcbReferenceRateClient.from_config(context.config).get_gbp_reference_rate(context)
        except Exception:
            result = {
                "source": cached["source"],
                "provider_date": cached["provider_date"],
                "usd_to_gbp": round(float(cached["usd_to_gbp"]), 6),
                "gbp_to_usd": round(float(cached["gbp_to_usd"]), 6),
                "mode": "stale_cache",
            }
            context.state["fx_gbp_reference"] = {**result, "raw": cached}
            return result
    else:
        fetched = EcbReferenceRateClient.from_config(context.config).get_gbp_reference_rate(
            context
        )

    rate_payload = {
        "source": fetched.source,
        "provider_date": fetched.provider_date,
        "fetched_at": fetched.fetched_at.isoformat(),
        "base_currency": fetched.base_currency,
        "usd_per_eur": fetched.usd_per_eur,
        "gbp_per_eur": fetched.gbp_per_eur,
        "usd_to_gbp": fetched.usd_to_gbp,
        "gbp_to_usd": fetched.gbp_to_usd,
        "mode": fetched.mode,
        "raw_payload": fetched.raw_payload,
    }
    context.usage_ledger.record_fx_reference_rate(rate=rate_payload)
    result = {
        "source": fetched.source,
        "provider_date": fetched.provider_date,
        "usd_to_gbp": round(fetched.usd_to_gbp, 6),
        "gbp_to_usd": round(fetched.gbp_to_usd, 6),
        "mode": fetched.mode,
    }
    context.state["fx_gbp_reference"] = {**result, "raw": rate_payload}
    return result


def market_scan(context: TickContext) -> PipelineResult:
    gate = context.state["market_gate"]
    equity_universe = list(context.config.discovery_equity_symbols)
    crypto_universe = list(context.config.discovery_crypto_symbols)
    current_rows = context.usage_ledger.get_latest_bars_for_tick(
        tick_id=context.tick_id,
        sources=["alpaca_market_data", "alpaca_crypto_data"],
    )

    result = {
        "equity_universe": len(equity_universe),
        "crypto_universe": len(crypto_universe),
        "bars_available": len(current_rows),
        "candidates_found": 0,
        "selected_candidates": 0,
        "mode": "pending",
        "scan_ready": gate["can_scan"],
    }
    if not current_rows:
        result["mode"] = "skipped"
        result["scan_ready"] = False
        result["skip_reason"] = gate["reason"] if gate["can_scan"] else gate["reason"]
        context.state["market_scan"] = {
            "result": result,
            "ranked_candidates": [],
            "selected_candidates": [],
        }
        return result

    previous_rows = context.usage_ledger.get_previous_bars(
        tick_id=context.tick_id,
        symbol_keys=[(row["source"], row["symbol"]) for row in current_rows],
    )
    ranked_candidates = rank_candidates(
        current_rows=current_rows,
        previous_by_symbol=previous_rows,
        target_count=context.config.discovery_target_count,
    )
    ranked_candidate_dicts = [item.as_dict() for item in ranked_candidates]
    selected_candidates = [item for item in ranked_candidate_dicts if item["selected"]]
    context.usage_ledger.record_discovery_candidates(
        tick_id=context.tick_id,
        candidates=ranked_candidate_dicts,
    )

    result["candidates_found"] = len(ranked_candidate_dicts)
    result["selected_candidates"] = len(selected_candidates)
    result["mode"] = "dynamic_discovery"
    if selected_candidates:
        result["top_symbol"] = selected_candidates[0]["symbol"]
        result["top_score"] = selected_candidates[0]["discovery_score"]

    context.state["market_scan"] = {
        "result": result,
        "ranked_candidates": ranked_candidate_dicts,
        "selected_candidates": selected_candidates,
    }
    return result


def context_enrichment(context: TickContext) -> PipelineResult:
    ranked_candidates = list(context.state["market_scan"].get("ranked_candidates", []))
    selected_candidates = list(context.state["market_scan"].get("selected_candidates", []))
    candidates = ranked_candidates or selected_candidates

    if not candidates:
        result = {
            "candidates_enriched": 0,
            "selected_candidates": 0,
            "news_items": 0,
            "sentiment_ready": False,
            "mode": "skipped",
            "reason": "no_selected_candidates",
        }
        context.state["context_enrichment"] = result
        return result

    enriched_candidates = _enrich_candidates_with_technicals(
        context,
        candidates=candidates,
        lookback_periods=20,
    )
    selected_enriched = [item for item in enriched_candidates if bool(item.get("selected"))]
    technical_ready = sum(
        1 for item in enriched_candidates if bool(item.get("technical_context_ready"))
    )
    breakout_ready = sum(
        1
        for item in enriched_candidates
        if bool(item.get("price_trigger_20"))
        and bool(item.get("volume_surge_20"))
        and bool(item.get("volatility_floor_pass_20"))
    )
    result = {
        "candidates_enriched": len(enriched_candidates),
        "selected_candidates": len(selected_enriched),
        "technical_context_ready": technical_ready,
        "breakout_ready_candidates": breakout_ready,
        "news_items": 0,
        "sentiment_ready": False,
        "mode": "market_metrics_only",
        "top_symbol": (selected_enriched[0]["symbol"] if selected_enriched else enriched_candidates[0]["symbol"]),
    }
    context.state["context_enrichment"] = {
        **result,
        "candidates": enriched_candidates,
        "selected_candidates": selected_enriched,
    }
    return result


def market_latest_bars(context: TickContext) -> PipelineResult:
    gate = context.state["market_gate"]
    watchlist = list(context.config.discovery_equity_symbols)

    if not gate["equity_scan_ready"]:
        result = {
            "bars_requested": len(watchlist),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "skipped",
            "reason": gate["equity_reason"],
        }
        context.state["market_data_latest_bars"] = result
        return result

    client = get_alpaca_client(context)
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = client.get_latest_bars(context, symbols=watchlist)
    bars_saved = context.usage_ledger.record_latest_bars(
        tick_id=context.tick_id,
        captured_at=captured_at,
        source="alpaca_market_data",
        bars_by_symbol=bars,
        quote_currency="USD",
        usd_to_gbp=float(fx_reference["usd_to_gbp"]),
    )
    result = {
        "bars_requested": len(watchlist),
        "bars_saved": bars_saved,
        "mode": "latest_bars",
        **summarize_latest_bars(bars),
    }
    context.state["market_data_latest_bars"] = {
        **result,
        "raw": bars,
    }
    return result


def crypto_latest_bars(context: TickContext) -> PipelineResult:
    gate = context.state["market_gate"]
    symbols = list(context.config.discovery_crypto_symbols)

    if not symbols:
        result = {
            "bars_requested": 0,
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "disabled",
        }
        context.state["crypto_data_latest_bars"] = result
        return result

    if not gate["crypto_scan_ready"]:
        result = {
            "bars_requested": len(symbols),
            "bars_received": 0,
            "bars_saved": 0,
            "mode": "skipped",
            "reason": gate["crypto_reason"],
        }
        context.state["crypto_data_latest_bars"] = result
        return result

    client = get_alpaca_client(context)
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = client.get_latest_crypto_bars(
        context,
        location=context.config.alpaca_crypto_location,
        symbols=symbols,
    )
    bars_saved = context.usage_ledger.record_latest_bars(
        tick_id=context.tick_id,
        captured_at=captured_at,
        source="alpaca_crypto_data",
        bars_by_symbol=bars,
        quote_currency="USD",
        usd_to_gbp=float(fx_reference["usd_to_gbp"]),
    )
    result = {
        "bars_requested": len(symbols),
        "bars_saved": bars_saved,
        "mode": "latest_crypto_bars",
        **summarize_latest_bars(bars),
    }
    context.state["crypto_data_latest_bars"] = {
        **result,
        "raw": bars,
    }
    return result


def paper_exit_management(context: TickContext) -> PipelineResult:
    positions = list(context.state.get("alpaca_positions", {}).get("raw", []))
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

    recent_orders = context.usage_ledger.list_recent_paper_trade_orders(limit=100)
    raw_open_orders = list(context.state.get("alpaca_orders", {}).get("raw", []))
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
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        broker_id = str(position.get("broker_id", "alpaca_paper")).strip().lower() or "alpaca_paper"
        if not symbol:
            continue

        entry_order = _find_latest_managed_entry_order(
            symbol=symbol,
            orders=recent_orders,
            broker_id=broker_id,
        )
        if entry_order is None:
            skipped.append({"symbol": symbol, "reason": "missing_entry_plan"})
            continue

        symbol_key = _normalized_symbol_key(symbol)
        latest_bar = latest_bars.get(symbol) or latest_bars.get(symbol_key)
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
            try:
                adapter = get_broker_adapter(context, broker_id)
                adapter.cancel_order(context, order_id=order_id)
                refreshed_exit_orders.append(
                    {
                        **open_exit_order,
                        "status": "canceled",
                        "updated_at": context.started_at.isoformat(),
                        "exit_refresh_reason": refresh_reason,
                    }
                )
            except BrokerAdapterError as exc:
                refresh_errors.append(
                    {
                        "symbol": symbol,
                        "order_id": order_id,
                        "reason": refresh_reason,
                        "error": str(exc),
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
    for exit_request in exit_requests:
        try:
            adapter = get_broker_adapter(context, exit_request["broker_id"])
            broker_order = adapter.submit_order(
                context,
                order_request=exit_request["order_request"],
            )
            submitted_orders.append(
                {
                    **broker_order,
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
                    "linked_order_id": exit_request.get("linked_order_id", ""),
                    "refreshed_exit_order_id": exit_request.get(
                        "refreshed_exit_order_id", ""
                    ),
                }
            )
        except BrokerAdapterError as exc:
            submission_errors.append(
                {
                    "symbol": exit_request["symbol"],
                    "broker_id": exit_request["broker_id"],
                    "strategy_id": exit_request["strategy_id"],
                    "error": str(exc),
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


def live_exit_management(context: TickContext) -> PipelineResult:
    """Manage future live exits from the same persisted plan fields as paper.

    The live lane should not be weaker than paper after activation: existing
    sell exits are refreshed if stale or non-marketable, replacement orders keep
    the original stop/target/holding policy, and every broker response is saved
    under `alpaca_live` for later live-vs-paper drift review.
    """
    positions = list(context.state.get("alpaca_live_positions", {}).get("raw", []))
    if not positions:
        result = {
            "broker": "alpaca_live",
            "positions_checked": 0,
            "exit_orders_submitted": 0,
            "mode": "idle",
        }
        context.state["live_exit_management"] = {
            **result,
            "orders": [],
            "errors": [],
            "skipped": [],
        }
        return result

    recent_orders = context.usage_ledger.list_recent_paper_trade_orders(limit=100)
    raw_open_orders = list(context.state.get("alpaca_live_orders", {}).get("raw", []))
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
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        broker_id = str(position.get("broker_id", "alpaca_live")).strip().lower() or "alpaca_live"
        if not symbol:
            continue
        symbol_key = _normalized_symbol_key(symbol)

        entry_order = _find_latest_managed_entry_order(
            symbol=symbol,
            orders=recent_orders,
            broker_id=broker_id,
        )
        if entry_order is None:
            skipped.append({"symbol": symbol, "reason": "missing_entry_plan"})
            continue

        latest_bar = latest_bars.get(symbol) or latest_bars.get(symbol_key)
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
            try:
                adapter = get_broker_adapter(context, broker_id)
                adapter.cancel_order(context, order_id=order_id)
                refreshed_exit_orders.append(
                    {
                        **open_exit_order,
                        "broker_id": broker_id,
                        "status": "canceled",
                        "updated_at": context.started_at.isoformat(),
                        "exit_refresh_reason": refresh_reason,
                    }
                )
            except BrokerAdapterError as exc:
                refresh_errors.append(
                    {
                        "symbol": symbol,
                        "order_id": order_id,
                        "reason": refresh_reason,
                        "error": str(exc),
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
            limit_buffer_bps=_live_limit_buffer_bps(
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
            broker_id="alpaca_live",
        )

    if not exit_requests:
        result = {
            "broker": "alpaca_live",
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
        context.state["live_exit_management"] = {
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
    for exit_request in exit_requests:
        try:
            adapter = get_broker_adapter(context, exit_request["broker_id"])
            broker_order = adapter.submit_order(
                context,
                order_request=exit_request["order_request"],
            )
            submitted_orders.append(
                {
                    **broker_order,
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
                    "linked_order_id": exit_request.get("linked_order_id", ""),
                    "refreshed_exit_order_id": exit_request.get(
                        "refreshed_exit_order_id", ""
                    ),
                }
            )
        except BrokerAdapterError as exc:
            submission_errors.append(
                {
                    "symbol": exit_request["symbol"],
                    "broker_id": exit_request["broker_id"],
                    "strategy_id": exit_request["strategy_id"],
                    "error": str(exc),
                    "exit_reason": exit_request["exit_reason"],
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
    context.state["live_exit_management"] = {
        **result,
        "orders": submitted_orders,
        "errors": submission_errors,
        "skipped": skipped,
        "refreshed_exit_orders": refreshed_exit_orders,
        "refresh_errors": refresh_errors,
    }
    return result


def shadow_trade_outcomes(context: TickContext) -> PipelineResult:
    if not context.config.shadow_enabled:
        result = {
            "checkpoints_due": 0,
            "checkpoints_evaluated": 0,
            "mode": "disabled",
        }
        context.state["shadow_trade_outcomes"] = {
            **result,
            "outcomes": [],
        }
        return result

    due_checkpoints = context.usage_ledger.list_due_shadow_trade_outcomes(
        as_of=context.started_at,
    )
    outcomes: list[dict[str, Any]] = []
    bars_loaded = 0

    for checkpoint in due_checkpoints:
        proposed_at = checkpoint.get("proposed_at")
        if proposed_at is None:
            continue
        bars = context.usage_ledger.get_market_bars_for_window(
            source=str(checkpoint["source"]),
            symbol=str(checkpoint["symbol"]),
            start_at=proposed_at,
            end_at=context.started_at,
        )
        bars_loaded += len(bars)
        outcome = evaluate_shadow_checkpoint(
            checkpoint=checkpoint,
            bars=bars,
            as_of=context.started_at,
            execution_spread_bps=context.config.shadow_execution_spread_bps,
            entry_slippage_bps=context.config.shadow_entry_slippage_bps,
            exit_slippage_bps=context.config.shadow_exit_slippage_bps,
            fixed_round_trip_cost_usd=context.config.shadow_fixed_round_trip_cost_usd,
            reference_notional_usd=context.config.paper_execution_default_notional_usd,
            profit_target_ladder_pct=context.config.shadow_profit_target_ladder_pct,
        )
        if outcome is not None:
            outcomes.append(outcome)

    checkpoints_evaluated = context.usage_ledger.record_shadow_trade_outcomes(
        outcomes=outcomes,
    )
    average_fitness = (
        round(
            sum(float(item["fitness_score"]) for item in outcomes) / len(outcomes),
            6,
        )
        if outcomes
        else 0.0
    )
    result = {
        "checkpoints_due": len(due_checkpoints),
        "checkpoints_evaluated": checkpoints_evaluated,
        "waiting_for_future_bars": max(0, len(due_checkpoints) - checkpoints_evaluated),
        "bars_loaded": bars_loaded,
        "average_fitness_score": average_fitness,
        "mode": "evaluated" if due_checkpoints else "idle",
    }
    context.state["shadow_trade_outcomes"] = {
        **result,
        "outcomes": outcomes,
    }
    return result


def strategy_fitness(context: TickContext) -> PipelineResult:
    raw_rows = context.usage_ledger.list_strategy_fitness_rows(
        as_of=context.started_at,
        lookback_days=context.config.strategy_fitness_lookback_days,
    )
    summaries = enrich_strategy_fitness_rows(
        rows=raw_rows,
        min_checkpoints=context.config.strategy_fitness_min_checkpoints,
    )
    saved_count = context.usage_ledger.record_strategy_fitness_snapshots(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        summaries=summaries,
    )
    result = {
        "strategy_summaries": len(summaries),
        "summaries_saved": saved_count,
        "lookback_days": context.config.strategy_fitness_lookback_days,
        "min_checkpoints": context.config.strategy_fitness_min_checkpoints,
        "mode": "scorecard" if summaries else "insufficient_data",
    }
    if summaries:
        top_summary = summaries[0]
        result["top_strategy"] = top_summary["strategy_id"]
        result["top_checkpoint"] = top_summary["checkpoint_code"]
        result["top_composite_score"] = top_summary["composite_fitness_score"]
        result["top_win_rate"] = top_summary["win_rate"]
    context.state["strategy_fitness"] = {
        **result,
        "summaries": summaries,
    }
    return result


def strategy_signals(context: TickContext) -> PipelineResult:
    candidates = context.state["context_enrichment"].get("candidates", [])
    if not candidates:
        result = {
            "strategy_families": 0,
            "profiles_tested": 0,
            "candidates_evaluated": 0,
            "signals_generated": 0,
            "mode": "skipped",
        }
        context.state["strategy_signals"] = {
            **result,
            "signals": [],
        }
        return result

    batch = evaluate_strategies(
        tick_id=context.tick_id,
        candidates=candidates,
        config=context.config,
        market_context={
            "market_gate": context.state["market_gate"],
            "account_equity": context.state["alpaca_account"]["summary"]["equity"],
        },
    )
    base_signal_dicts = [item.as_dict(tick_id=context.tick_id) for item in batch.signals]
    fitness_summaries = context.state.get("strategy_fitness", {}).get("summaries", [])
    _, preliminary_allocation_stats = allocate_strategy_signals(
        signals=base_signal_dicts,
        fitness_summaries=fitness_summaries,
        min_checkpoints=context.config.strategy_allocation_min_checkpoints,
        favor_threshold=context.config.strategy_allocation_favor_threshold,
        suppress_threshold=-999.0,
        asset_class_suppress_thresholds={"equity": -999.0, "crypto": -999.0},
    )
    threshold_state = ThresholdAdvisor(
        config=context.config,
        usage_ledger=context.usage_ledger,
    ).effective_threshold(
        tick_id=context.tick_id,
        now=context.started_at,
        current_signal_preview=preliminary_allocation_stats.get("raw_signals", []),
    )
    suppress_threshold = float(
        threshold_state.get(
            "effective_threshold",
            context.config.strategy_allocation_suppress_threshold,
        )
    )
    suppress_thresholds = _paper_allocation_suppress_thresholds(
        context,
        equity_threshold=suppress_threshold,
    )
    signal_dicts, allocation_stats = allocate_strategy_signals(
        signals=base_signal_dicts,
        fitness_summaries=fitness_summaries,
        min_checkpoints=context.config.strategy_allocation_min_checkpoints,
        favor_threshold=context.config.strategy_allocation_favor_threshold,
        suppress_threshold=suppress_threshold,
        asset_class_suppress_thresholds=suppress_thresholds,
        high_score_override_enabled=(
            bool(context.config.paper_execution_enabled)
            and not bool(context.config.paper_execution_kill_switch)
            and bool(context.config.paper_execution_high_score_override_enabled)
        ),
        high_score_override_min_score=(
            context.config.paper_execution_high_score_override_min_score
        ),
        high_score_override_fitness_margin=(
            context.config.paper_execution_high_score_override_fitness_margin
        ),
        high_score_override_allowed_strategies={
            strategy_id.lower()
            for strategy_id in context.config.paper_execution_allowed_strategies
            if strategy_id
        },
    )
    allocation_stats["suppress_threshold"] = suppress_threshold
    allocation_stats["suppress_thresholds"] = suppress_thresholds
    allocation_stats["threshold_adaptive"] = threshold_state
    context.usage_ledger.record_strategy_candidate_signals(
        tick_id=context.tick_id,
        signals=signal_dicts,
    )
    result = {
        "strategy_families": batch.family_count,
        "profiles_tested": batch.profile_count,
        "candidates_evaluated": len(candidates),
        "signals_generated": len(signal_dicts),
        "signals_suppressed": allocation_stats["suppressed"],
        "signals_high_score_overridden": allocation_stats["high_score_overrides"],
        "signals_favored": allocation_stats["favored"],
        "allocation_min_checkpoints": context.config.strategy_allocation_min_checkpoints,
        "allocation_suppress_threshold": suppress_threshold,
        "allocation_suppress_thresholds": suppress_thresholds,
        "threshold_adaptive": threshold_state,
        "mode": "fitness_weighted_rule_based",
    }
    raw_signal_preview = allocation_stats.get("raw_signals", [])
    suppressed_signal_preview = allocation_stats.get("suppressed_signals", [])
    if raw_signal_preview:
        result["raw_signal_preview"] = raw_signal_preview
    if suppressed_signal_preview:
        result["suppressed_signal_preview"] = suppressed_signal_preview
    if signal_dicts:
        result["top_symbol"] = signal_dicts[0]["symbol"]
        result["top_strategy"] = signal_dicts[0]["strategy_id"]
        result["top_score"] = signal_dicts[0]["signal_score"]
    context.state["strategy_signals"] = {
        **result,
        "signals": signal_dicts,
        "allocation": allocation_stats,
    }
    return result


def gemini_analysis(context: TickContext) -> PipelineResult:
    enrichment = context.state["context_enrichment"]
    selected_candidates = enrichment.get("selected_candidates", [])
    candidates_enriched = enrichment["candidates_enriched"]
    if candidates_enriched == 0:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "skipped",
        }
        context.state["gemini_analysis"] = result
        return result

    if not context.config.gemini_analysis_enabled:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "disabled",
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": [],
        }
        return result

    if not context.config.gemini_api_configured:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "not_configured",
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": [],
        }
        return result

    candidates_for_llm = selected_candidates[
        : context.config.gemini_analysis_candidate_limit
    ]
    fx_reference = context.state["fx_gbp_reference"]
    market_context = {
        "market_gate": context.state["market_gate"],
        "fx_gbp_reference": {
            "source": fx_reference["source"],
            "provider_date": fx_reference["provider_date"],
            "usd_to_gbp": fx_reference["usd_to_gbp"],
            "gbp_to_usd": fx_reference["gbp_to_usd"],
            "mode": fx_reference["mode"],
        },
        "account_equity": context.state["alpaca_account"]["summary"]["equity"],
    }

    try:
        gemini_response = get_gemini_client(context).analyze_candidates(
            context=context,
            candidates=candidates_for_llm,
            market_context=market_context,
        )
        normalized_analyses = _normalize_gemini_analyses(
            requested_candidates=candidates_for_llm,
            analysis_payload=gemini_response["analysis"],
        )
        context.usage_ledger.record_gemini_analyses(
            tick_id=context.tick_id,
            analyses=normalized_analyses,
        )
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": len(normalized_analyses),
            "analysis_mode": "live",
            "top_symbol": normalized_analyses[0]["symbol"]
            if normalized_analyses
            else "",
            "top_score": normalized_analyses[0]["opportunity_score"]
            if normalized_analyses
            else 0,
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": normalized_analyses,
            "usage_metadata": gemini_response["usage_metadata"],
            "raw_response": gemini_response["raw_response"],
        }
        return result
    except GeminiApiError as exc:
        fallback_analyses = _build_fallback_analyses(
            requested_candidates=candidates_for_llm,
            error=str(exc),
        )
        context.usage_ledger.record_gemini_analyses(
            tick_id=context.tick_id,
            analyses=fallback_analyses,
        )
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": len(fallback_analyses),
            "analysis_mode": "fallback",
            "error": str(exc),
            "top_symbol": fallback_analyses[0]["symbol"] if fallback_analyses else "",
            "top_score": fallback_analyses[0]["opportunity_score"] if fallback_analyses else 0,
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": fallback_analyses,
        }
        return result

    result = {
        "provider": "gemini_api",
        "candidates_analyzed": candidates_enriched,
        "analysis_mode": "adapter_pending",
    }
    context.state["gemini_analysis"] = result
    return result


def shadow_trade_proposals(context: TickContext) -> PipelineResult:
    if not context.config.shadow_enabled:
        result = {
            "strategy_signals": 0,
            "proposals_created": 0,
            "mode": "disabled",
        }
        context.state["shadow_trade_proposals"] = {
            **result,
            "proposals": [],
        }
        return result

    strategy_state = context.state.get("strategy_signals", {})
    signals = strategy_state.get("signals", [])
    if not signals:
        result = {
            "strategy_signals": 0,
            "proposals_created": 0,
            "mode": "skipped",
        }
        context.state["shadow_trade_proposals"] = {
            **result,
            "proposals": [],
        }
        return result

    recent_strategy_keys = context.usage_ledger.list_recent_shadow_proposal_keys(
        since=context.started_at
        - timedelta(minutes=context.config.shadow_proposal_cooldown_minutes)
    )
    proposals = build_shadow_proposals(
        tick_id=context.tick_id,
        proposed_at=context.started_at,
        strategy_signals=signals,
        recent_strategy_keys=recent_strategy_keys,
        proposal_limit=context.config.shadow_proposal_limit,
        min_signal_score=context.config.shadow_min_opportunity_score,
        checkpoint_windows=context.config.shadow_checkpoint_windows,
    )
    context.usage_ledger.record_shadow_trade_proposals(proposals=proposals)

    result = {
        "strategy_signals": len(signals),
        "proposals_created": len(proposals),
        "cooldown_minutes": context.config.shadow_proposal_cooldown_minutes,
        "score_threshold": context.config.shadow_min_opportunity_score,
        "mode": "created" if proposals else "idle",
    }
    if proposals:
        result["top_symbol"] = proposals[0]["symbol"]
        result["top_strategy"] = proposals[0]["strategy_id"]
        result["holding_window"] = proposals[0]["holding_window_code"]
    context.state["shadow_trade_proposals"] = {
        **result,
        "proposals": proposals,
    }
    return result


def risk_cfo_gate(context: TickContext) -> PipelineResult:
    config = context.config
    gate = context.state["market_gate"]
    protection = context.state.get("daily_protection", {})
    proposals = list(context.state.get("shadow_trade_proposals", {}).get("proposals", []))
    positions_summary = context.state.get("alpaca_positions", {}).get("summary", {})
    orders_summary = context.state.get("alpaca_orders", {}).get("summary", {})
    open_positions = int(positions_summary.get("open_positions", 0) or 0)
    open_orders = int(orders_summary.get("open_orders", 0) or 0)
    occupied_slots = open_positions + open_orders
    slot_policy = _earned_slot_policy(
        context=context,
        broker_id="alpaca_paper",
        account_state_key="alpaca_account",
        base_max_positions=int(config.paper_execution_max_open_positions),
        slot_size_usd=float(config.paper_execution_default_notional_usd),
    )
    effective_max_positions = int(slot_policy["effective_max_open_positions"])
    available_slots = max(0, effective_max_positions - occupied_slots)
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
    elif available_slots <= 0:
        reason = "max_open_positions_reached"
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
            for strategy_id in config.paper_execution_allowed_strategies
            if strategy_id
        }
        for proposal in proposals:
            approval, rejection = _build_paper_trade_approval(
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
                continue
            approved.append(approval)
            if len(approved) >= min(config.paper_execution_max_orders_per_tick, available_slots):
                break

        if approved:
            decision = "submit_paper"
            reason = "paper_trade_approved"
        elif rejected:
            reason = rejected[0]["reason"]
        else:
            reason = "no_paper_eligible_proposals"

    result = {
        "approved_trades": len(approved),
        "rejected_trades": len(rejected),
        "decision": decision,
        "reason": reason,
        "watch_candidates": len(proposals),
        "open_positions": open_positions,
        "open_orders": open_orders,
        "available_slots": available_slots,
        "base_max_open_positions": int(config.paper_execution_max_open_positions),
        "effective_max_open_positions": effective_max_positions,
        "earned_slots": int(slot_policy["earned_slots"]),
        "earned_slot_pnl_usd": slot_policy["total_pnl_usd"],
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


def live_risk_cfo_gate(context: TickContext) -> PipelineResult:
    """Gate live entry follows after paper has actually submitted the trade.

    Live uses the same strategy/fitness brain as paper, but it still has its own
    account, slot, drawdown, allowlist, activation, and broker-validation checks.
    Requiring a submitted paper order prevents live from following a proposal
    that paper approved but failed to place.
    """
    config = context.config
    gate = context.state["market_gate"]
    protection = context.state.get("live_daily_protection", {})
    paper_approvals = list(context.state.get("risk_cfo", {}).get("approved_order_requests", []))
    paper_submitted_orders = list(context.state.get("execution", {}).get("orders", []))
    submitted_paper_proposal_ids = {
        str(order.get("proposal_id", "")).strip()
        for order in paper_submitted_orders
        if str(order.get("proposal_id", "")).strip()
    }
    submitted_paper_approvals = [
        approval
        for approval in paper_approvals
        if str(approval.get("proposal_id", "")).strip() in submitted_paper_proposal_ids
    ]
    proposals = list(context.state.get("shadow_trade_proposals", {}).get("proposals", []))
    proposal_by_id = {
        str(proposal.get("proposal_id", "")): proposal
        for proposal in proposals
        if str(proposal.get("proposal_id", ""))
    }
    live_account_summary = context.state.get("alpaca_live_account", {}).get("summary", {})
    live_account_trade_ready, live_account_reason = _account_trade_ready(live_account_summary)
    positions_summary = context.state.get("alpaca_live_positions", {}).get("summary", {})
    orders_summary = context.state.get("alpaca_live_orders", {}).get("summary", {})
    open_positions = int(positions_summary.get("open_positions", 0) or 0)
    open_orders = int(orders_summary.get("open_orders", 0) or 0)
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

    if not config.live_execution_enabled:
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
    elif not paper_approvals:
        reason = "no_paper_approved_trade_to_follow"
    elif not submitted_paper_approvals:
        reason = "no_submitted_paper_order_to_follow"
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
        for paper_approval in submitted_paper_approvals:
            proposal = proposal_by_id.get(str(paper_approval.get("proposal_id", "")))
            if proposal is None:
                rejected.append(
                    {
                        "symbol": str(paper_approval.get("symbol", "")).upper(),
                        "broker_id": "alpaca_live",
                        "strategy_id": str(paper_approval.get("strategy_id", "")),
                        "reason": "paper_proposal_not_found",
                    }
                )
                continue
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
        "watch_candidates": len(paper_approvals),
        "submitted_paper_follow_candidates": len(submitted_paper_approvals),
        "open_positions": open_positions,
        "open_orders": open_orders,
        "available_slots": available_slots,
        "base_max_open_positions": int(config.live_execution_max_open_positions),
        "effective_max_open_positions": effective_max_positions,
        "earned_slots": int(slot_policy["earned_slots"]),
        "earned_slot_pnl_usd": slot_policy["total_pnl_usd"],
    }
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


def execution_paper(context: TickContext) -> PipelineResult:
    approvals = list(context.state["risk_cfo"].get("approved_order_requests", []))
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
    for approval in approvals:
        try:
            adapter = get_broker_adapter(context, approval["broker_id"])
            broker_order = adapter.submit_order(
                context,
                order_request=approval["order_request"],
            )
            submitted_orders.append(
                {
                    **broker_order,
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
                }
            )
        except BrokerAdapterError as exc:
            submission_errors.append(
                {
                    "symbol": approval["symbol"],
                    "broker_id": approval["broker_id"],
                    "strategy_id": approval["strategy_id"],
                    "error": str(exc),
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
    if submission_errors:
        result["error_count"] = len(submission_errors)
        result["first_error"] = submission_errors[0]["error"]
    context.state["execution"] = {
        **result,
        "orders": submitted_orders,
        "errors": submission_errors,
    }
    return result


def execution_live(context: TickContext) -> PipelineResult:
    approvals = list(context.state.get("live_risk_cfo", {}).get("approved_order_requests", []))
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
    for approval in approvals:
        try:
            adapter = get_broker_adapter(context, approval["broker_id"])
            broker_order = adapter.submit_order(
                context,
                order_request=approval["order_request"],
            )
            submitted_orders.append(
                {
                    **broker_order,
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
        except BrokerAdapterError as exc:
            submission_errors.append(
                {
                    "symbol": approval["symbol"],
                    "broker_id": approval["broker_id"],
                    "strategy_id": approval["strategy_id"],
                    "error": str(exc),
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


def _count_reason_occurrences(items: list[dict[str, Any]], *, key: str = "reason") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        reason = str(item.get(key, "")).strip() or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _top_reason(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return max(
        counts.items(),
        key=lambda item: (int(item[1]), str(item[0])),
    )[0]


def _build_tick_blocker_summary(context: TickContext) -> dict[str, Any]:
    market_gate_state = context.state.get("market_gate", {})
    strategy_state = context.state.get("strategy_signals", {})
    allocation_state = strategy_state.get("allocation", {})
    shadow_proposals_state = context.state.get("shadow_trade_proposals", {})
    risk_cfo_state = context.state.get("risk_cfo", {})
    exit_state = context.state.get("paper_exit_management", {})

    rejected_candidates = list(risk_cfo_state.get("rejected_candidates", []))
    rejected_reason_counts = _count_reason_occurrences(rejected_candidates)
    skipped_positions = list(exit_state.get("skipped", []))
    exit_skip_reason_counts = _count_reason_occurrences(skipped_positions)

    raw_signals = int(allocation_state.get("signals_in", 0) or 0)
    suppressed_signals = int(
        allocation_state.get(
            "suppressed",
            strategy_state.get("signals_suppressed", 0),
        )
        or 0
    )
    high_score_overrides = int(allocation_state.get("high_score_overrides", 0) or 0)
    surviving_signals = int(
        allocation_state.get(
            "signals_out",
            strategy_state.get("signals_generated", 0),
        )
        or 0
    )
    proposals_created = int(shadow_proposals_state.get("proposals_created", 0) or 0)
    approved_trades = int(risk_cfo_state.get("approved_trades", 0) or 0)
    rejected_trades = int(risk_cfo_state.get("rejected_trades", 0) or 0)

    primary_entry_blocker = str(risk_cfo_state.get("reason", "")).strip() or "unknown"
    if raw_signals <= 0:
        primary_stage = "no_raw_signals"
    elif suppressed_signals >= raw_signals and raw_signals > 0:
        primary_stage = "all_signals_suppressed"
    elif proposals_created <= 0:
        primary_stage = "no_shadow_proposals"
    elif approved_trades <= 0 and rejected_trades > 0:
        primary_stage = "proposal_rejected"
    elif approved_trades > 0:
        primary_stage = "trade_approved"
    else:
        primary_stage = "hold"

    summary = {
        "primary_stage": primary_stage,
        "market_reason": str(market_gate_state.get("reason", "")).strip() or "unknown",
        "cfo_reason": primary_entry_blocker,
        "raw_signals": raw_signals,
        "suppressed_signals": suppressed_signals,
        "high_score_overrides": high_score_overrides,
        "surviving_signals": surviving_signals,
        "proposals_created": proposals_created,
        "approved_trades": approved_trades,
        "rejected_trades": rejected_trades,
        "rejection_reason_counts": rejected_reason_counts,
        "top_rejection_reason": _top_reason(rejected_reason_counts),
        "positions_checked_for_exit": int(exit_state.get("positions_checked", 0) or 0),
        "exit_orders_submitted": int(exit_state.get("exit_orders_submitted", 0) or 0),
        "exit_skip_reason_counts": exit_skip_reason_counts,
        "top_exit_skip_reason": _top_reason(exit_skip_reason_counts),
    }
    return summary


def post_trade_evaluation(context: TickContext) -> PipelineResult:
    orders_submitted = context.state["execution"]["orders_submitted"]
    shadow_outcomes = context.state.get("shadow_trade_outcomes", {})
    shadow_proposals = context.state.get("shadow_trade_proposals", {})
    strategy_state = context.state.get("strategy_signals", {})
    strategy_fitness_state = context.state.get("strategy_fitness", {})
    result = {
        "trades_reviewed": orders_submitted,
        "fitness_inputs": shadow_outcomes.get("checkpoints_evaluated", 0),
        "memory_updates": shadow_outcomes.get("checkpoints_evaluated", 0),
        "strategy_signals_generated": strategy_state.get("signals_generated", 0),
        "shadow_proposals_created": shadow_proposals.get("proposals_created", 0),
        "shadow_outcomes_evaluated": shadow_outcomes.get("checkpoints_evaluated", 0),
        "average_fitness_score": shadow_outcomes.get("average_fitness_score", 0.0),
        "strategy_scorecards": strategy_fitness_state.get("strategy_summaries", 0),
        "top_strategy": strategy_fitness_state.get("top_strategy", ""),
        "top_composite_fitness_score": strategy_fitness_state.get(
            "top_composite_score",
            0.0,
        ),
        "paper_execution_status": context.state["execution"].get("execution_status", "idle"),
    }
    context.state["tick_blockers"] = _build_tick_blocker_summary(context)
    context.state["post_trade_evaluation"] = result
    return result


def build_default_pipeline() -> list[StepDefinition]:
    return [
        StepDefinition(name="control.heartbeat", runner=control_heartbeat),
        StepDefinition(name="alpaca.account", runner=alpaca_account),
        StepDefinition(name="alpaca.clock", runner=alpaca_clock),
        StepDefinition(name="alpaca.positions", runner=alpaca_positions),
        StepDefinition(name="alpaca.orders", runner=alpaca_orders),
        StepDefinition(name="alpaca_live.sync", runner=alpaca_live_sync),
        StepDefinition(name="risk.daily_protection", runner=daily_protection),
        StepDefinition(name="risk.live_daily_protection", runner=live_daily_protection),
        StepDefinition(name="maintenance.stale_orders", runner=stale_order_reaper),
        StepDefinition(name="maintenance.live_stale_orders", runner=live_stale_order_reaper),
        StepDefinition(name="market.gate", runner=market_gate),
        StepDefinition(name="fx.gbp_reference", runner=fx_gbp_reference),
        StepDefinition(name="market.latest_bars", runner=market_latest_bars),
        StepDefinition(name="crypto.latest_bars", runner=crypto_latest_bars),
        StepDefinition(name="execution.paper_exits", runner=paper_exit_management),
        StepDefinition(name="execution.live_exits", runner=live_exit_management),
        StepDefinition(name="shadow.outcomes", runner=shadow_trade_outcomes),
        StepDefinition(name="strategy.fitness", runner=strategy_fitness),
        StepDefinition(name="market.scan", runner=market_scan),
        StepDefinition(name="context.enrichment", runner=context_enrichment),
        StepDefinition(name="strategy.signals", runner=strategy_signals),
        StepDefinition(name="analysis.gemini", runner=gemini_analysis),
        StepDefinition(name="shadow.proposals", runner=shadow_trade_proposals),
        StepDefinition(name="risk.cfo", runner=risk_cfo_gate),
        StepDefinition(name="execution.paper", runner=execution_paper),
        StepDefinition(name="risk.live_cfo", runner=live_risk_cfo_gate),
        StepDefinition(name="execution.live", runner=execution_live),
        StepDefinition(name="evaluation.post_trade", runner=post_trade_evaluation),
    ]


def _build_paper_trade_approval(
    *,
    context: TickContext,
    proposal: dict[str, Any],
    tick_id: str,
    config: Any,
    market_gate: dict[str, Any],
    position_symbols: set[str],
    open_order_symbols: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    symbol = str(proposal.get("symbol", "")).upper()
    strategy_id = str(proposal.get("strategy_id", ""))
    asset_class = str(proposal.get("asset_class", "")).lower()
    direction = str(proposal.get("direction", "long")).lower()
    entry_price = _as_float(proposal.get("entry_price"))
    stop_loss_price = _as_float(proposal.get("stop_loss_price"))
    target_price = _as_float(proposal.get("target_price"))

    if not symbol:
        return None, {"symbol": "", "strategy_id": strategy_id, "reason": "missing_symbol"}
    if asset_class not in {"equity", "crypto"}:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "unsupported_asset_class"}
    if config.paper_execution_equity_only and asset_class != "equity":
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "non_equity_blocked"}
    if (
        asset_class == "equity"
        and config.paper_execution_require_market_open
        and not bool(market_gate.get("market_open"))
    ):
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "market_closed"}
    if asset_class == "crypto" and not bool(market_gate.get("crypto_scan_ready")):
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "crypto_unavailable"}
    if direction != "long":
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "direction_not_supported"}
    if symbol in position_symbols:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "position_already_open"}
    if symbol in open_order_symbols:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "order_already_open"}
    if entry_price is None or entry_price <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_entry_price"}
    if stop_loss_price is None or stop_loss_price <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_stop_loss"}
    if target_price is None or target_price <= entry_price:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_target_price"}
    projected_gain_pct = (target_price - entry_price) / entry_price
    min_projected_gain_pct = _paper_min_projected_gain_pct(config, asset_class)
    if projected_gain_pct < min_projected_gain_pct:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "reason": "projected_gain_too_thin",
        }

    notional_usd = round(float(config.paper_execution_default_notional_usd), 2)
    if notional_usd <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "qty_too_small"}

    broker_id = _paper_execution_broker_id_for_asset_class(
        config=config,
        asset_class=asset_class,
    )
    try:
        adapter = get_broker_adapter(context, broker_id)
    except BrokerAdapterError:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": "broker_unavailable",
        }

    broker_rejection = adapter.validate_entry_constraints(
        context=context,
        proposal=proposal,
        notional_usd=notional_usd,
        usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
    )
    if broker_rejection is not None:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": broker_rejection,
        }

    client_order_id = _build_client_order_id(
        tick_id=tick_id,
        symbol=symbol,
        strategy_id=strategy_id,
    )
    try:
        order_request = adapter.build_entry_order_request(
            proposal=proposal,
            client_order_id=client_order_id,
            notional_usd=notional_usd,
            limit_buffer_bps=_paper_limit_buffer_bps(config, asset_class),
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
    except BrokerAdapterError:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": "broker_order_build_failed",
        }
    return (
        {
            "broker_id": broker_id,
            "proposal_id": str(proposal.get("proposal_id", "")),
            "strategy_id": strategy_id,
            "strategy_family": str(proposal.get("strategy_family", "")),
            "profile_id": str(proposal.get("profile_id", "")),
            "source": str(proposal.get("source", "")),
            "symbol": symbol,
            "asset_class": asset_class,
            "notional_usd": notional_usd,
            "client_order_id": client_order_id,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "projected_gain_pct": round(projected_gain_pct, 6),
            "holding_window_code": _paper_exit_policy_holding_window_code(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "holding_window_minutes": _paper_exit_policy_holding_window_minutes(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "managed_exit_policy": _paper_managed_exit_policy(strategy_id=strategy_id),
            "profit_exit_window_minutes": _paper_profit_exit_window_minutes(
                strategy_id=strategy_id,
            ),
            "max_hold_window_minutes": _paper_max_hold_window_minutes(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "order_request": order_request,
        },
        None,
    )


def _build_live_trade_approval(
    *,
    context: TickContext,
    proposal: dict[str, Any],
    tick_id: str,
    config: Any,
    market_gate: dict[str, Any],
    position_symbols: set[str],
    open_order_symbols: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    symbol = str(proposal.get("symbol", "")).upper()
    strategy_id = str(proposal.get("strategy_id", ""))
    asset_class = str(proposal.get("asset_class", "")).lower()
    direction = str(proposal.get("direction", "long")).lower()
    entry_price = _as_float(proposal.get("entry_price"))
    stop_loss_price = _as_float(proposal.get("stop_loss_price"))
    target_price = _as_float(proposal.get("target_price"))

    if not symbol:
        return None, {"symbol": "", "strategy_id": strategy_id, "reason": "missing_symbol"}
    if asset_class not in {"equity", "crypto"}:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "unsupported_asset_class"}
    if config.live_execution_equity_only and asset_class != "equity":
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "non_equity_blocked_live"}
    if (
        asset_class == "equity"
        and config.live_execution_require_market_open
        and not bool(market_gate.get("market_open"))
    ):
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "market_closed"}
    if asset_class == "crypto" and not bool(market_gate.get("crypto_scan_ready")):
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "crypto_unavailable"}
    if direction != "long":
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "direction_not_supported"}
    if symbol in position_symbols:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "position_already_open_live"}
    if symbol in open_order_symbols:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "order_already_open_live"}
    if entry_price is None or entry_price <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_entry_price"}
    if stop_loss_price is None or stop_loss_price <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_stop_loss"}
    if target_price is None or target_price <= entry_price:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "invalid_target_price"}
    projected_gain_pct = (target_price - entry_price) / entry_price
    min_projected_gain_pct = _live_min_projected_gain_pct(config, asset_class)
    if projected_gain_pct < min_projected_gain_pct:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "reason": "projected_gain_too_thin_live",
        }

    notional_usd = round(float(config.live_execution_default_notional_usd), 2)
    if notional_usd <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "qty_too_small"}

    broker_id = _live_execution_broker_id_for_asset_class(
        config=config,
        asset_class=asset_class,
    )
    try:
        adapter = get_broker_adapter(context, broker_id)
    except BrokerAdapterError:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": "broker_unavailable",
        }

    broker_rejection = adapter.validate_entry_constraints(
        context=context,
        proposal=proposal,
        notional_usd=notional_usd,
        usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
    )
    if broker_rejection is not None:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": broker_rejection,
        }

    client_order_id = _build_client_order_id(
        tick_id=tick_id,
        symbol=symbol,
        strategy_id=strategy_id,
        lane="live",
    )
    try:
        order_request = adapter.build_entry_order_request(
            proposal=proposal,
            client_order_id=client_order_id,
            notional_usd=notional_usd,
            limit_buffer_bps=_live_limit_buffer_bps(config, asset_class),
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
    except BrokerAdapterError:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": "broker_order_build_failed",
        }
    return (
        {
            "broker_id": broker_id,
            "proposal_id": str(proposal.get("proposal_id", "")),
            "strategy_id": strategy_id,
            "strategy_family": str(proposal.get("strategy_family", "")),
            "profile_id": str(proposal.get("profile_id", "")),
            "source": str(proposal.get("source", "")),
            "symbol": symbol,
            "asset_class": asset_class,
            "notional_usd": notional_usd,
            "client_order_id": client_order_id,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "projected_gain_pct": round(projected_gain_pct, 6),
            "holding_window_code": _paper_exit_policy_holding_window_code(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "holding_window_minutes": _paper_exit_policy_holding_window_minutes(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "managed_exit_policy": _paper_managed_exit_policy(strategy_id=strategy_id),
            "profit_exit_window_minutes": _paper_profit_exit_window_minutes(
                strategy_id=strategy_id,
            ),
            "max_hold_window_minutes": _paper_max_hold_window_minutes(
                strategy_id=strategy_id,
                proposal=proposal,
            ),
            "order_request": order_request,
        },
        None,
    )


def _paper_execution_status(*, submitted_count: int, error_count: int) -> str:
    if submitted_count and error_count:
        return "partial"
    if submitted_count:
        return "submitted"
    if error_count:
        return "error"
    return "idle"


def _build_client_order_id(
    *,
    tick_id: str,
    symbol: str,
    strategy_id: str,
    lane: str = "paper",
) -> str:
    lane_part = re.sub(r"[^a-z0-9]+", "", lane.lower())[:5]
    symbol_part = re.sub(r"[^a-z0-9]+", "", symbol.lower())[:8]
    strategy_part = re.sub(r"[^a-z0-9]+", "", strategy_id.lower())[:12]
    return f"centaur-{lane_part}-{tick_id[-6:]}-{symbol_part}-{strategy_part}"[:48]


def _paper_execution_broker_id_for_asset_class(*, config: Any, asset_class: str) -> str:
    normalized = str(asset_class or "").strip().lower()
    if normalized == "crypto":
        return str(config.paper_execution_crypto_broker_id or "alpaca_paper").strip().lower()
    return str(config.paper_execution_equity_broker_id or "alpaca_paper").strip().lower()


def _live_execution_broker_id_for_asset_class(*, config: Any, asset_class: str) -> str:
    normalized = str(asset_class or "").strip().lower()
    if normalized == "crypto":
        return str(config.live_execution_crypto_broker_id or "alpaca_live").strip().lower()
    return str(config.live_execution_equity_broker_id or "alpaca_live").strip().lower()


def _earned_slot_policy(
    *,
    context: TickContext,
    broker_id: str,
    account_state_key: str,
    base_max_positions: int,
    slot_size_usd: float,
) -> dict[str, Any]:
    base_slots = max(0, int(base_max_positions))
    slot_size = max(0.0, float(slot_size_usd or 0.0))
    account_state = context.state.get(account_state_key, {})
    summary = account_state.get("summary", {}) if isinstance(account_state, dict) else {}
    raw_account = account_state.get("raw", {}) if isinstance(account_state, dict) else {}
    current_equity = _as_float(summary.get("equity"))
    if current_equity is None:
        current_equity = _as_float(raw_account.get("equity"))

    baseline_equity: float | None = None
    tracking_started_at: datetime | None = None
    first_order = context.usage_ledger.get_first_paper_trade_order(broker_id=broker_id)
    if first_order is not None:
        started_at = first_order.get("submitted_at") or first_order.get("captured_at")
        if isinstance(started_at, datetime):
            tracking_started_at = started_at
            baseline_tick = context.usage_ledger.get_latest_tick_run_before(
                started_before=started_at
            )
            baseline_snapshot = (
                baseline_tick.get("state_snapshot_json", {})
                if isinstance(baseline_tick, dict)
                else {}
            )
            if isinstance(baseline_snapshot, dict):
                baseline_account_state = baseline_snapshot.get(account_state_key, {})
                if isinstance(baseline_account_state, dict):
                    baseline_summary = baseline_account_state.get("summary", {})
                    baseline_raw = baseline_account_state.get("raw", {})
                    if isinstance(baseline_summary, dict):
                        baseline_equity = _as_float(baseline_summary.get("equity"))
                    if baseline_equity is None and isinstance(baseline_raw, dict):
                        baseline_equity = _as_float(baseline_raw.get("last_equity"))
                    if baseline_equity is None and isinstance(baseline_raw, dict):
                        baseline_equity = _as_float(baseline_raw.get("equity"))

    total_pnl_usd = 0.0
    if baseline_equity is not None and current_equity is not None:
        total_pnl_usd = round(current_equity - baseline_equity, 6)
    earned_slots = int(max(total_pnl_usd, 0.0) // slot_size) if slot_size > 0 else 0
    return {
        "broker_id": broker_id,
        "base_max_open_positions": base_slots,
        "slot_size_usd": slot_size,
        "baseline_equity": baseline_equity,
        "current_equity": current_equity,
        "total_pnl_usd": total_pnl_usd,
        "earned_slots": earned_slots,
        "effective_max_open_positions": base_slots + earned_slots,
        "tracking_started_at": tracking_started_at,
    }


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_bars_by_symbol(context: TickContext) -> dict[str, dict[str, Any]]:
    bars: dict[str, dict[str, Any]] = {}
    for state_key in ("market_data_latest_bars", "crypto_data_latest_bars"):
        raw = context.state.get(state_key, {}).get("raw", {})
        if isinstance(raw, dict):
            for symbol, bar in raw.items():
                if isinstance(symbol, str) and isinstance(bar, dict):
                    symbol_upper = symbol.upper()
                    bars[symbol_upper] = bar
                    bars[_normalized_symbol_key(symbol_upper)] = bar
    return bars


def _normalized_symbol_key(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


def _latest_raw_bars_by_key(context: TickContext) -> dict[tuple[str, str], dict[str, Any]]:
    bars: dict[tuple[str, str], dict[str, Any]] = {}
    source_map = {
        "market_data_latest_bars": "alpaca_market_data",
        "crypto_data_latest_bars": "alpaca_crypto_data",
    }
    for state_key, source in source_map.items():
        raw = context.state.get(state_key, {}).get("raw", {})
        if isinstance(raw, dict):
            for symbol, bar in raw.items():
                if isinstance(symbol, str) and isinstance(bar, dict):
                    bars[(source, symbol.upper())] = bar
    return bars


def _enrich_candidates_with_technicals(
    context: TickContext,
    *,
    candidates: list[dict[str, Any]],
    lookback_periods: int,
) -> list[dict[str, Any]]:
    raw_bars = _latest_raw_bars_by_key(context)
    enriched: list[dict[str, Any]] = []
    history_window_minutes = max(60, lookback_periods * 3)

    for candidate in candidates:
        source = str(candidate.get("source", "")).strip()
        symbol = str(candidate.get("symbol", "")).upper()
        if not source or not symbol:
            enriched.append(dict(candidate))
            continue

        end_at = _coerce_datetime(candidate.get("bar_timestamp")) or context.started_at
        start_at = end_at - timedelta(minutes=history_window_minutes)
        historical_rows = context.usage_ledger.get_market_bars_for_window(
            source=source,
            symbol=symbol,
            start_at=start_at,
            end_at=end_at,
        )
        live_bar = raw_bars.get((source, symbol))
        live_row = None
        if isinstance(live_bar, dict):
            live_row = build_live_bar_row(
                source=source,
                symbol=symbol,
                raw_bar=live_bar,
                close_price_gbp=_as_float(candidate.get("close_price_gbp")),
            )
        technical_rows = merge_bar_rows(
            historical_rows=historical_rows,
            live_row=live_row,
        )
        technical_context = compute_volatility_breakout_context(
            bars=technical_rows,
            lookback_periods=lookback_periods,
        )
        enriched.append(
            {
                **candidate,
                **technical_context,
            }
        )

    return enriched


def _find_latest_managed_entry_order(
    *,
    symbol: str,
    orders: list[dict[str, Any]],
    broker_id: str | None = None,
) -> dict[str, Any] | None:
    symbol_upper = symbol.upper()
    symbol_key = _normalized_symbol_key(symbol_upper)
    broker_filter = str(broker_id or "").strip().lower()
    for order in orders:
        order_symbol = str(order.get("symbol", "")).upper()
        if order_symbol != symbol_upper and _normalized_symbol_key(order_symbol) != symbol_key:
            continue
        if broker_filter and str(order.get("broker_id", "")).strip().lower() != broker_filter:
            continue
        if str(order.get("side", "")).lower() != "buy":
            continue
        raw = order.get("raw_json", {})
        if not isinstance(raw, dict):
            raw = {}
        has_planned_raw = any(
            value not in (None, "", 0, 0.0)
            for key in (
                "planned_stop_loss_price",
                "planned_take_profit_price",
                "planned_holding_window_minutes",
            )
            for value in (raw.get(key),)
        )
        has_persisted_plan = (
            order.get("stop_loss_price") not in (None, "", 0, 0.0)
            or order.get("take_profit_price") not in (None, "", 0, 0.0)
        )
        if not has_planned_raw and not has_persisted_plan:
            continue
        return order
    return None


def _build_exit_order_request(
    *,
    context: TickContext,
    tick_id: str,
    position: dict[str, Any],
    entry_order: dict[str, Any],
    latest_bar: dict[str, Any],
    bar_history: list[dict[str, Any]],
    as_of: datetime,
    limit_buffer_bps: float,
) -> tuple[dict[str, Any] | None, str | None]:
    symbol = str(position.get("symbol", "")).upper()
    broker_symbol = str(entry_order.get("symbol") or symbol).upper()
    raw_qty = str(position.get("qty", "")).strip()
    qty = _as_float(raw_qty)
    if qty is None or qty <= 0:
        return None, "invalid_position_qty"

    raw = entry_order.get("raw_json", {})
    if not isinstance(raw, dict):
        raw = {}
    proposal_plan = _lookup_entry_proposal_plan(
        context=context,
        proposal_id=str(entry_order.get("proposal_id", "")).strip(),
    )
    proposal_raw = proposal_plan.get("raw_json", {})
    if not isinstance(proposal_raw, dict):
        proposal_raw = {}
    stop_loss_price = _as_float(
        raw.get(
            "planned_stop_loss_price",
            entry_order.get("stop_loss_price", proposal_plan.get("stop_loss_price")),
        )
    )
    target_price = _as_float(
        raw.get(
            "planned_take_profit_price",
            entry_order.get("take_profit_price", proposal_plan.get("target_price")),
        )
    )
    break_even_trigger_price = _as_float(
        raw.get(
            "planned_break_even_trigger_price",
            proposal_raw.get("break_even_trigger_price"),
        )
    )
    trailing_stop_mode = str(
        raw.get(
            "planned_trailing_stop_mode",
            proposal_raw.get("trailing_stop_mode", ""),
        )
    ).strip()
    holding_window_minutes = int(
        raw.get(
            "planned_holding_window_minutes",
            proposal_plan.get("holding_window_minutes", 0),
        )
        or 0
    )
    holding_window_code = str(
        raw.get(
            "planned_holding_window_code",
            proposal_plan.get("holding_window_code", ""),
        )
        or ""
    ).strip()
    if stop_loss_price is None:
        stop_loss_price = _as_float(proposal_raw.get("stop_loss_price"))
    if target_price is None:
        target_price = _as_float(proposal_raw.get("target_price"))
    if holding_window_minutes <= 0:
        holding_window_minutes = int(proposal_raw.get("holding_window_minutes", 0) or 0)
    if not holding_window_code:
        holding_window_code = str(proposal_raw.get("holding_window_code", "") or "").strip()
    strategy_id = str(entry_order.get("strategy_id", "")).strip()
    managed_exit_policy = str(
        raw.get(
            "planned_managed_exit_policy",
            proposal_raw.get(
                "managed_exit_policy",
                _paper_managed_exit_policy(strategy_id=strategy_id),
            ),
        )
        or ""
    ).strip()
    profit_exit_window_minutes = int(
        raw.get(
            "planned_profit_exit_window_minutes",
            proposal_raw.get(
                "profit_exit_window_minutes",
                _paper_profit_exit_window_minutes(strategy_id=strategy_id),
            ),
        )
        or 0
    )
    max_hold_window_minutes = int(
        raw.get(
            "planned_max_hold_window_minutes",
            proposal_raw.get(
                "max_hold_window_minutes",
                _paper_max_hold_window_minutes(
                    strategy_id=strategy_id,
                    proposal=proposal_plan,
                ),
            ),
        )
        or holding_window_minutes
        or 0
    )
    if strategy_id == "crypto_momentum.trend":
        managed_exit_policy = _paper_managed_exit_policy(strategy_id=strategy_id)
        holding_window_code = _paper_exit_policy_holding_window_code(
            strategy_id=strategy_id,
            proposal=proposal_plan,
        )
        holding_window_minutes = _paper_exit_policy_holding_window_minutes(
            strategy_id=strategy_id,
            proposal=proposal_plan,
        )
        max_hold_window_minutes = _paper_max_hold_window_minutes(
            strategy_id=strategy_id,
            proposal=proposal_plan,
        )
    profit_capture_pct = _as_float(
        raw.get(
            "planned_profit_capture_pct",
            proposal_raw.get(
                "profit_capture_pct",
                getattr(context.config, "paper_execution_profit_capture_pct", 0.0),
            ),
        )
    )
    entry_submitted_at = _coerce_datetime(
        entry_order.get("submitted_at") or entry_order.get("captured_at")
    )

    low_price = _as_float(latest_bar.get("l"))
    high_price = _as_float(latest_bar.get("h"))
    close_price = _as_float(latest_bar.get("c"))
    current_price = _as_float(position.get("current_price"))
    current_bar_timestamp = _coerce_datetime(latest_bar.get("t")) or as_of

    effective_stop_loss = stop_loss_price
    if (
        trailing_stop_mode == "break_even_next_bar"
        and break_even_trigger_price is not None
        and entry_submitted_at is not None
        and _break_even_active_before_bar(
            entry_submitted_at=entry_submitted_at,
            current_bar_timestamp=current_bar_timestamp,
            break_even_trigger_price=break_even_trigger_price,
            bars=bar_history,
        )
    ):
        effective_stop_loss = (
            _as_float(entry_order.get("filled_avg_price"))
            or _as_float(position.get("avg_entry_price"))
            or _as_float(raw.get("entry_price"))
            or stop_loss_price
        )

    entry_reference_price = (
        _as_float(entry_order.get("filled_avg_price"))
        or _as_float(position.get("avg_entry_price"))
        or _as_float(raw.get("entry_price"))
        or _as_float(proposal_plan.get("entry_price"))
    )
    profit_capture_price = (
        round(entry_reference_price * (1.0 + profit_capture_pct), 8)
        if entry_reference_price is not None
        and profit_capture_pct is not None
        and profit_capture_pct > 0
        else None
    )

    exit_reason: str | None = None
    if effective_stop_loss is not None and low_price is not None and low_price <= effective_stop_loss:
        exit_reason = "stop_loss_hit"
    elif (
        profit_capture_price is not None
        and high_price is not None
        and high_price >= profit_capture_price
    ):
        exit_reason = "profit_capture_hit"
    elif target_price is not None and high_price is not None and high_price >= target_price:
        exit_reason = "take_profit_hit"
    elif (
        managed_exit_policy == "profit_after_1h_else_1d"
        and entry_submitted_at is not None
        and profit_exit_window_minutes > 0
        and as_of >= entry_submitted_at + timedelta(minutes=profit_exit_window_minutes)
    ):
        profit_reference_price = (
            close_price
            or current_price
        )
        if (
            profit_reference_price is not None
            and entry_reference_price is not None
            and profit_reference_price > entry_reference_price
        ):
            exit_reason = "profit_after_one_hour"
        elif (
            max_hold_window_minutes > 0
            and as_of >= entry_submitted_at + timedelta(minutes=max_hold_window_minutes)
        ):
            exit_reason = "max_holding_window_elapsed"
        else:
            return None, "exit_not_due"
    elif (
        holding_window_minutes > 0
        and entry_submitted_at is not None
        and as_of >= entry_submitted_at + timedelta(minutes=holding_window_minutes)
    ):
        if managed_exit_policy == "profit_capture_else_1d":
            exit_reason = "max_holding_window_elapsed"
        else:
            exit_reason = "holding_window_elapsed"
    else:
        return None, "exit_not_due"

    asset_class = str(entry_order.get("asset_class", "")).strip().lower()
    reference_exit_price = (
        close_price
        or current_price
        or _as_float(position.get("avg_entry_price"))
        or target_price
        or effective_stop_loss
    )
    if reference_exit_price is None or reference_exit_price <= 0:
        return None, "invalid_exit_reference_price"
    client_order_id = _build_client_order_id(
        tick_id=tick_id,
        symbol=symbol,
        strategy_id=f"{strategy_id or 'paper'}exit",
    )
    broker_id = str(
        entry_order.get("broker_id") or position.get("broker_id") or "alpaca_paper"
    ).strip().lower() or "alpaca_paper"
    try:
        adapter = get_broker_adapter(context, broker_id)
        order_request = adapter.build_exit_order_request(
            symbol=broker_symbol,
            asset_class=asset_class,
            qty=raw_qty,
            reference_price=reference_exit_price,
            client_order_id=client_order_id,
            limit_buffer_bps=limit_buffer_bps,
            entry_order=entry_order,
            latest_bar=latest_bar,
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
    except BrokerAdapterError:
        return None, "broker_order_build_failed"
    return (
        {
            "broker_id": broker_id,
            "proposal_id": str(entry_order.get("proposal_id", "")).strip(),
            "strategy_id": strategy_id,
            "strategy_family": str(entry_order.get("strategy_family", "")).strip(),
            "profile_id": str(entry_order.get("profile_id", "")).strip(),
            "source": str(entry_order.get("source", "")).strip(),
            "symbol": broker_symbol,
            "asset_class": asset_class,
            "linked_order_id": str(entry_order.get("order_id", "")).strip(),
            "planned_take_profit_price": target_price,
            "planned_stop_loss_price": effective_stop_loss,
            "planned_holding_window_code": holding_window_code,
            "planned_holding_window_minutes": holding_window_minutes,
            "planned_managed_exit_policy": managed_exit_policy,
            "planned_profit_exit_window_minutes": profit_exit_window_minutes,
            "planned_max_hold_window_minutes": max_hold_window_minutes,
            "planned_profit_capture_pct": profit_capture_pct,
            "planned_profit_capture_price": profit_capture_price,
            "planned_break_even_trigger_price": break_even_trigger_price,
            "planned_trailing_stop_mode": trailing_stop_mode,
            "exit_reason": exit_reason,
            "latest_close_price": close_price,
            "order_request": order_request,
        },
        None,
    )


def _lookup_entry_proposal_plan(
    *,
    context: TickContext,
    proposal_id: str,
) -> dict[str, Any]:
    if not proposal_id:
        return {}
    try:
        proposal = context.usage_ledger.get_shadow_trade_proposal(
            proposal_id=proposal_id
        )
    except Exception:
        return {}
    return proposal if isinstance(proposal, dict) else {}


def _paper_managed_exit_policy(*, strategy_id: str) -> str:
    if strategy_id == "mean_reversion.snapback":
        return "profit_after_1h_else_1d"
    if strategy_id == "crypto_momentum.trend":
        return "profit_capture_else_1d"
    return "time_exit"


def _paper_profit_exit_window_minutes(*, strategy_id: str) -> int:
    if strategy_id == "mean_reversion.snapback":
        return 60
    return 0


def _paper_max_hold_window_minutes(*, strategy_id: str, proposal: dict[str, Any]) -> int:
    if strategy_id == "mean_reversion.snapback":
        return 1440
    if strategy_id == "crypto_momentum.trend":
        return 1440
    return int(proposal.get("holding_window_minutes", 0) or 0)


def _paper_exit_policy_holding_window_code(
    *,
    strategy_id: str,
    proposal: dict[str, Any],
) -> str:
    if strategy_id == "mean_reversion.snapback":
        return "profit_after_1h_else_1d"
    if strategy_id == "crypto_momentum.trend":
        return "profit_capture_else_1d"
    return str(proposal.get("holding_window_code", ""))


def _paper_exit_policy_holding_window_minutes(
    *,
    strategy_id: str,
    proposal: dict[str, Any],
) -> int:
    if strategy_id == "mean_reversion.snapback":
        return 1440
    if strategy_id == "crypto_momentum.trend":
        return 1440
    return int(proposal.get("holding_window_minutes", 0) or 0)


def _break_even_active_before_bar(
    *,
    entry_submitted_at: datetime,
    current_bar_timestamp: datetime,
    break_even_trigger_price: float,
    bars: list[dict[str, Any]],
) -> bool:
    if break_even_trigger_price <= 0:
        return False

    prior_bars: list[dict[str, Any]] = []
    for row in bars:
        captured_at = _coerce_datetime(row.get("captured_at") or row.get("bar_timestamp"))
        if captured_at is None:
            continue
        if captured_at < entry_submitted_at or captured_at >= current_bar_timestamp:
            continue
        prior_bars.append(
            {
                "captured_at": captured_at,
                "high_price": _as_float(row.get("high_price")),
            }
        )

    prior_bars.sort(key=lambda item: item["captured_at"])
    return any(
        bar["high_price"] is not None and bar["high_price"] >= break_even_trigger_price
        for bar in prior_bars
    )


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _current_market_session(*, started_at: datetime, market_timezone: str) -> tuple[date, datetime]:
    market_tz = ZoneInfo(market_timezone)
    market_now = started_at.astimezone(market_tz)
    market_date = market_now.date()
    market_open = market_now.replace(hour=9, minute=30, second=0, microsecond=0)

    if market_now.weekday() >= 5:
        market_date = _previous_business_date(market_date)
    elif market_now < market_open:
        market_date = _previous_business_date(market_date)

    session_open = datetime(
        year=market_date.year,
        month=market_date.month,
        day=market_date.day,
        hour=9,
        minute=30,
        tzinfo=market_tz,
    ).astimezone(started_at.tzinfo)
    return market_date, session_open


def _previous_business_date(value: date) -> date:
    prior = value - timedelta(days=1)
    while prior.weekday() >= 5:
        prior -= timedelta(days=1)
    return prior


def _is_stale_entry_order(
    *,
    order: dict[str, Any],
    as_of: datetime,
    stale_after_minutes: int,
) -> bool:
    status = str(order.get("status", "")).strip().lower()
    side = str(order.get("side", "")).strip().lower()
    order_type = str(order.get("type", "")).strip().lower()
    symbol = str(order.get("symbol", "")).upper()
    asset_class = str(order.get("asset_class", "")).strip().lower()
    if not asset_class:
        asset_class = "crypto" if "/" in symbol else "equity"
    if not _order_status_is_open(status):
        return False
    if asset_class != "equity":
        return False
    if side != "buy" or order_type != "limit":
        return False
    filled_qty = _as_float(order.get("filled_qty")) or 0.0
    if filled_qty > 0:
        return False
    submitted_at = _coerce_datetime(order.get("submitted_at") or order.get("created_at"))
    if submitted_at is None:
        return False
    return as_of >= submitted_at + timedelta(minutes=max(1, stale_after_minutes))


def _open_exit_order_refresh_reason(
    *,
    order: dict[str, Any],
    position: dict[str, Any],
    latest_bar: dict[str, Any],
    as_of: datetime,
    stale_after_minutes: int,
) -> str | None:
    status = str(order.get("status", "")).strip().lower()
    side = str(order.get("side", "")).strip().lower()
    order_type = str(order.get("type") or order.get("order_type") or "").strip().lower()
    if not _order_status_is_open(status):
        return None
    if side != "sell" or order_type != "limit":
        return None

    limit_price = _as_float(order.get("limit_price"))
    current_price = (
        _as_float(position.get("current_price"))
        or _as_float(latest_bar.get("c"))
    )
    if (
        limit_price is not None
        and current_price is not None
        and limit_price > current_price
    ):
        return "exit_limit_not_marketable"

    submitted_at = _coerce_datetime(
        order.get("submitted_at") or order.get("created_at") or order.get("captured_at")
    )
    if (
        submitted_at is not None
        and as_of >= submitted_at + timedelta(minutes=max(1, stale_after_minutes))
    ):
        return "exit_limit_stale"
    return None


def _order_status_is_open(status: str) -> bool:
    return str(status).strip().lower() in {
        "new",
        "accepted",
        "pending_new",
        "accepted_for_bidding",
        "partially_filled",
        "held",
        "pending_replace",
        "pending_cancel",
    }


def _normalize_gemini_analyses(
    *,
    requested_candidates: list[dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    requested_by_symbol = {
        str(candidate["symbol"]).upper(): candidate for candidate in requested_candidates
    }
    returned_candidates = analysis_payload.get("candidates", [])
    normalized: list[dict[str, Any]] = []
    used_symbols: set[str] = set()

    for item in returned_candidates:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol or symbol not in requested_by_symbol or symbol in used_symbols:
            continue

        normalized.append(
            {
                "symbol": symbol,
                "action_bias": str(item.get("action_bias", "hold")).lower(),
                "opportunity_score": float(item.get("opportunity_score", 0)),
                "confidence": float(item.get("confidence", 0)),
                "thesis": str(item.get("thesis", "")).strip(),
                "risks": [str(risk) for risk in item.get("risks", [])][:5],
            }
        )
        used_symbols.add(symbol)

    for candidate in requested_candidates:
        symbol = str(candidate["symbol"]).upper()
        if symbol in used_symbols:
            continue
        normalized.append(
            {
                "symbol": symbol,
                "action_bias": "hold",
                "opportunity_score": 0.0,
                "confidence": 0.0,
                "thesis": "No structured Gemini output returned for this symbol.",
                "risks": ["insufficient_model_output"],
            }
        )

    normalized.sort(
        key=lambda item: (item["opportunity_score"], item["confidence"], item["symbol"]),
        reverse=True,
    )
    return normalized


def _build_fallback_analyses(
    *,
    requested_candidates: list[dict[str, Any]],
    error: str,
) -> list[dict[str, Any]]:
    if not requested_candidates:
        return []

    max_discovery_score = max(
        float(item.get("discovery_score", 0) or 0) for item in requested_candidates
    )
    normalized: list[dict[str, Any]] = []
    for rank, candidate in enumerate(requested_candidates, start=1):
        symbol = str(candidate.get("symbol", "")).upper()
        discovery_score = float(candidate.get("discovery_score", 0) or 0)
        opportunity_score = 0.0
        if max_discovery_score > 0:
            opportunity_score = round((discovery_score / max_discovery_score) * 100.0, 3)
        action_bias = "watch" if rank <= 2 and opportunity_score >= 50.0 else "hold"
        normalized.append(
            {
                "symbol": symbol,
                "action_bias": action_bias,
                "opportunity_score": opportunity_score,
                "confidence": 0.2,
                "thesis": "Fallback analysis from discovery ranking because Gemini output was unusable.",
                "risks": ["gemini_output_unstructured", error[:120]],
            }
        )

    normalized.sort(
        key=lambda item: (item["opportunity_score"], item["confidence"], item["symbol"]),
        reverse=True,
    )
    return normalized
