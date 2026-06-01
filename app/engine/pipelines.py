from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.adapters.execution import ExecutionAdapterError, get_execution_adapter
from app.adapters.market_data import get_market_data_adapter
from app.runtime.execution_router import ExecutionRouter
from app.runtime.mode_context import mode_context_from_config

from app.adapters.alpaca import summarize_latest_bars
from app.adapters.brokers import BrokerAdapterError, get_broker_adapter
from app.core.fx import EcbReferenceRateClient, rate_is_stale
from app.reporting.threshold_advisor import ThresholdAdvisor
from app.runtime.models import TickContext
from app.runtime.slack import SlackNotificationError, SlackWebhookClient
from app.strategies.registry import evaluate_strategies

from .candidate_engine import rank_candidates
from .fitness_engine import allocate_strategy_signals, enrich_strategy_fitness_rows
from .prediction_engine import GeminiApiError, get_gemini_client
from .shadow import build_shadow_proposals, evaluate_shadow_checkpoint
from .technicals import (
    build_live_bar_row,
    compute_volatility_breakout_context,
    merge_bar_rows,
)

PipelineResult = dict[str, Any]
PipelineRunner = Callable[[TickContext], PipelineResult]
ALPACA_PDT_MIN_EQUITY_USD = 25_000.0


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


def _live_runtime_allows_broker_reads(context: TickContext) -> bool:
    return mode_context_from_config(context.config).can_read_live_broker


def _live_runtime_allows_order_mutation(context: TickContext) -> bool:
    return mode_context_from_config(context.config).can_mutate_live_broker


def _symbol_from_broker_payload(payload: dict[str, Any]) -> str:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if symbol:
        return symbol
    ticker = str(payload.get("ticker") or "").strip().upper()
    if "_US_EQ" in ticker:
        return ticker.split("_US_EQ", 1)[0]
    if "_" in ticker:
        return ticker.split("_", 1)[0]
    return ticker


def _empty_live_broker_state(context: TickContext, *, reason: str) -> dict[str, Any]:
    result = {
        "broker_id": "alpaca_live",
        "mode": "skipped",
        "reason": reason,
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


def _empty_trading212_paper_state(
    context: TickContext,
    *,
    reason: str,
    mode: str = "skipped",
) -> dict[str, Any]:
    result = {
        "broker_id": "trading212_paper",
        "mode": mode,
        "reason": reason,
    }
    context.state["trading212_paper_account"] = {
        "broker_id": "trading212_paper",
        "summary": {},
        "raw": {},
    }
    context.state["trading212_paper_positions"] = {
        "broker_id": "trading212_paper",
        "summary": {"open_positions": 0, "symbols": []},
        "raw": [],
    }
    context.state["trading212_paper_orders"] = {
        "broker_id": "trading212_paper",
        "summary": {"open_orders": 0, "open_order_symbols": []},
        "raw": [],
    }
    return result


def _equity_weekend_carry_enabled(config: Any) -> bool:
    return bool(
        getattr(config, "paper_execution_equity_no_weekend_carry_enabled", False)
    )


def _market_session_minutes(
    as_of: datetime,
    market_timezone: str,
    *,
    next_close: Any = None,
) -> tuple[int, int] | None:
    market_now = as_of.astimezone(ZoneInfo(market_timezone))
    if market_now.weekday() != 4:
        return None
    close_at = _coerce_datetime(next_close)
    if close_at is not None:
        market_close = close_at.astimezone(ZoneInfo(market_timezone))
        if market_close.date() == market_now.date():
            regular_close_minutes = (market_close.hour * 60) + market_close.minute
        else:
            regular_close_minutes = 16 * 60
    else:
        regular_close_minutes = 16 * 60
    minutes_since_midnight = (market_now.hour * 60) + market_now.minute
    return minutes_since_midnight, regular_close_minutes


def _equity_friday_entry_cutoff_active(
    config: Any,
    as_of: datetime,
    *,
    next_close: Any = None,
) -> bool:
    """Protect equity entries from creating calendar-weekend hold drift."""
    if not _equity_weekend_carry_enabled(config):
        return False
    session = _market_session_minutes(
        as_of,
        config.market_timezone,
        next_close=next_close,
    )
    if session is None:
        return False
    minutes_since_midnight, regular_close_minutes = session
    cutoff_minutes = max(
        0,
        int(
            getattr(
                config,
                "paper_execution_equity_friday_entry_cutoff_minutes_before_close",
                60,
            )
        ),
    )
    cutoff_at = regular_close_minutes - cutoff_minutes
    return cutoff_at <= minutes_since_midnight < regular_close_minutes


def _equity_friday_flatten_due(
    config: Any,
    *,
    asset_class: str,
    as_of: datetime,
    next_close: Any = None,
) -> bool:
    """Return true when an equity managed exit should avoid weekend carry."""
    if str(asset_class).strip().lower() != "equity":
        return False
    if not _equity_weekend_carry_enabled(config):
        return False
    session = _market_session_minutes(
        as_of,
        config.market_timezone,
        next_close=next_close,
    )
    if session is None:
        return False
    minutes_since_midnight, regular_close_minutes = session
    flatten_minutes = max(
        0,
        int(
            getattr(
                config,
                "paper_execution_equity_friday_flatten_minutes_before_close",
                15,
            )
        ),
    )
    flatten_at = regular_close_minutes - flatten_minutes
    return flatten_at <= minutes_since_midnight < regular_close_minutes


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
    if not _live_runtime_allows_broker_reads(context):
        return _empty_live_broker_state(context, reason="runtime_mode_not_live")
    if not context.config.alpaca_live_api_configured:
        return _empty_live_broker_state(
            context,
            reason="alpaca_live_credentials_missing",
        )

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


def trading212_paper_sync(context: TickContext) -> PipelineResult:
    """Sync the separate Trading 212 demo account without enabling execution.

    This optional paper lane is isolated from Alpaca execution. API/read
    failures are reported in tick state but do not halt the active paper/live
    control path, because Trading 212 order mutation is still fail-closed.
    """
    if not getattr(context.config, "trading212_paper_api_configured", False):
        return _empty_trading212_paper_state(
            context,
            reason="trading212_paper_credentials_missing",
        )

    try:
        adapter = get_broker_adapter(context, "trading212_paper")
        raw_account = {
            **adapter.get_account(context),
            "broker_id": adapter.broker_id,
        }
        account_summary = adapter.summarize_account(raw_account)
        raw_positions = [
            {
                **position,
                "broker_id": adapter.broker_id,
                "symbol": _symbol_from_broker_payload(position),
            }
            for position in adapter.get_positions(context)
        ]
        positions_summary = adapter.summarize_positions(raw_positions)
        raw_orders = [
            {
                **order,
                "broker_id": adapter.broker_id,
                "symbol": _symbol_from_broker_payload(order),
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
    except BrokerAdapterError as exc:
        result = _empty_trading212_paper_state(
            context,
            reason=str(exc),
            mode="sync_error",
        )
        result["error_type"] = type(exc).__name__
        return result

    account_payload = {
        "broker_id": adapter.broker_id,
        "summary": account_summary,
        "raw": raw_account,
    }
    context.state["trading212_paper_account"] = account_payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = account_payload
    context.state["trading212_paper_positions"] = {
        "broker_id": adapter.broker_id,
        "summary": positions_summary,
        "raw": raw_positions,
    }
    context.state["trading212_paper_orders"] = {
        "broker_id": adapter.broker_id,
        "summary": orders_summary,
        "raw": raw_orders,
    }
    return {
        "broker_id": adapter.broker_id,
        "mode": "synced",
        "account_snapshot_saved": 1,
        "orders_saved": orders_saved,
        "open_positions": positions_summary.get("open_positions", 0),
        "open_orders": orders_summary.get("open_orders", 0),
        "equity": account_summary.get("equity"),
        "cash": account_summary.get("cash"),
        "currency": account_summary.get("currency"),
    }


def daily_protection(context: TickContext) -> PipelineResult:
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


def live_daily_protection(context: TickContext) -> PipelineResult:
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


def trading212_paper_daily_protection(context: TickContext) -> PipelineResult:
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


def trailing_drawdown_observer(context: TickContext) -> PipelineResult:
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


def stale_order_reaper(context: TickContext) -> PipelineResult:
    """Cancel stale untouched paper equity entry limits and audit the action.

    The reaper keeps old marketable-limit buys from filling after their signal
    context has aged. It only acts on entry orders that match the stale-entry
    predicate, then persists the cancellation and increments the daily audit
    counter used by status/reporting.
    """
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
    router = ExecutionRouter()

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
        routed_cancel = router.route_cancel_order(
            context=context,
            broker_id=broker_id,
            order_id=order_id,
            lane="paper",
        )
        if routed_cancel.canceled:
            canceled_order = {
                **order,
                "status": "canceled",
                "updated_at": context.started_at.isoformat(),
            }
            canceled_orders.append(canceled_order)
            updated_orders.append(canceled_order)
        else:
            cancel_errors.append(
                {"symbol": symbol, "error": routed_cancel.error or routed_cancel.status}
            )
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
    if not _live_runtime_allows_broker_reads(context):
        result = {
            "broker": "alpaca_live",
            "mode": "skipped",
            "reason": "runtime_mode_not_live",
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
    intended_cancellations: list[dict[str, Any]] = []
    cancel_errors: list[dict[str, Any]] = []
    stale_candidates: list[dict[str, Any]] = []
    updated_orders: list[dict[str, Any]] = []
    router = ExecutionRouter()

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
        routed_cancel = router.route_cancel_order(
            context=context,
            broker_id="alpaca_live",
            order_id=order_id,
            lane="live",
        )
        if routed_cancel.canceled:
            canceled_order = {
                **order,
                "broker_id": "alpaca_live",
                "status": "canceled",
                "updated_at": context.started_at.isoformat(),
            }
            canceled_orders.append(canceled_order)
            updated_orders.append(canceled_order)
        elif routed_cancel.status == "live_dry_intent":
            intended_cancellations.append(
                {
                    "symbol": symbol,
                    "order_id": order_id,
                    "broker_id": "alpaca_live",
                    "intent": routed_cancel.intended_order or {},
                }
            )
            updated_orders.append(order)
        else:
            cancel_errors.append(
                {"symbol": symbol, "error": routed_cancel.error or routed_cancel.status}
            )
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
    if _live_runtime_allows_order_mutation(context):
        revised_summary = get_broker_adapter(context, "alpaca_live").summarize_orders(updated_orders)
    else:
        revised_summary = prior_summary
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
        "orders_intended": len(intended_cancellations),
        "orders_saved": orders_saved,
        "stale_after_minutes": stale_after_minutes,
    }
    if intended_cancellations:
        result["mode"] = "live_dry"
    if stale_candidates:
        result["first_stale_symbol"] = stale_candidates[0]["symbol"]
    if cancel_errors:
        result["error_count"] = len(cancel_errors)
        result["first_error"] = cancel_errors[0]["error"]
    context.state["live_stale_order_reaper"] = {
        **result,
        "canceled_orders": canceled_orders,
        "intended_cancellations": intended_cancellations,
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

    market_data = get_market_data_adapter(context, "alpaca")
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = market_data.get_latest_equity_bars(context, symbols=watchlist)
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

    market_data = get_market_data_adapter(context, "alpaca")
    captured_at = context.started_at
    fx_reference = context.state["fx_gbp_reference"]
    bars = market_data.get_latest_crypto_bars(
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
    """Submit or refresh deterministic managed exits for paper positions.

    This is the protective sell side of paper execution: it reconstructs the
    persisted entry plan, checks stop/profit/time/no-weekend rules, refreshes
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
        symbol = str(position.get("symbol", "")).upper()
        broker_id = str(position.get("broker_id", "alpaca_paper")).strip().lower() or "alpaca_paper"
        if not symbol:
            continue

        entry_order = _find_most_protective_managed_entry_order(
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
            action="exit",
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
                    "linked_order_id": exit_request.get("linked_order_id", ""),
                    "refreshed_exit_order_id": exit_request.get(
                        "refreshed_exit_order_id", ""
                    ),
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


def live_exit_management(context: TickContext) -> PipelineResult:
    """Manage future live exits from the same persisted plan fields as paper.

    The live lane should not be weaker than paper after activation: existing
    sell exits are refreshed if stale or non-marketable, replacement orders keep
    the original stop/target/holding policy, and every broker response is saved
    under `alpaca_live` for later live-vs-paper drift review.
    """
    if not _live_runtime_allows_broker_reads(context):
        result = {
            "broker": "alpaca_live",
            "positions_checked": 0,
            "exit_orders_submitted": 0,
            "mode": "skipped",
            "reason": "runtime_mode_not_live",
        }
        context.state["live_exit_management"] = {
            **result,
            "orders": [],
            "errors": [],
            "skipped": [],
        }
        return result

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

    recent_orders = context.usage_ledger.list_recent_execution_lane_trade_orders(limit=100)
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
    intended_refresh_cancellations: list[dict[str, Any]] = []
    refresh_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        broker_id = str(position.get("broker_id", "alpaca_live")).strip().lower() or "alpaca_live"
        if not symbol:
            continue
        symbol_key = _normalized_symbol_key(symbol)

        entry_order = _find_most_protective_managed_entry_order(
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
            routed_cancel = router.route_cancel_order(
                context=context,
                broker_id=broker_id,
                order_id=order_id,
                lane="live",
            )
            if routed_cancel.canceled:
                refreshed_exit_orders.append(
                    {
                        **open_exit_order,
                        "broker_id": broker_id,
                        "status": "canceled",
                        "updated_at": context.started_at.isoformat(),
                        "exit_refresh_reason": refresh_reason,
                    }
                )
            elif routed_cancel.status == "live_dry_intent":
                intended_refresh_cancellations.append(
                    {
                        "symbol": symbol,
                        "order_id": order_id,
                        "broker_id": broker_id,
                        "reason": refresh_reason,
                        "intent": routed_cancel.intended_order or {},
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
    intended_exit_orders: list[dict[str, Any]] = []
    submission_errors: list[dict[str, Any]] = []
    router = ExecutionRouter()
    for exit_request in exit_requests:
        routed = router.route_order_request(
            context=context,
            broker_id=exit_request["broker_id"],
            order_request=exit_request["order_request"],
            lane="live",
            action="exit",
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
                    "linked_order_id": exit_request.get("linked_order_id", ""),
                    "refreshed_exit_order_id": exit_request.get(
                        "refreshed_exit_order_id", ""
                    ),
                }
            )
        elif routed.status == "live_dry_intent":
            intended_exit_orders.append(
                {
                    "symbol": exit_request["symbol"],
                    "broker_id": exit_request["broker_id"],
                    "strategy_id": exit_request["strategy_id"],
                    "exit_reason": exit_request["exit_reason"],
                    "intent": routed.intended_order or {},
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
        broker_id="alpaca_live",
    )
    result = {
        "broker": "alpaca_live",
        "positions_checked": len(positions),
        "exit_orders_submitted": len(submitted_orders),
        "exit_orders_intended": len(intended_exit_orders),
        "exit_orders_refreshed": len(refreshed_exit_orders),
        "exit_refreshes_intended": len(intended_refresh_cancellations),
        "refreshed_orders_saved": refreshed_orders_saved,
        "orders_saved": orders_saved,
        "execution_status": _paper_execution_status(
            submitted_count=len(submitted_orders),
            error_count=len(submission_errors),
        ),
        "mode": "managed_exits",
    }
    if intended_exit_orders or intended_refresh_cancellations:
        result["execution_status"] = "live_dry"
        result["mode"] = "live_dry"
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
        "intended_orders": intended_exit_orders,
        "errors": submission_errors,
        "skipped": skipped,
        "refreshed_exit_orders": refreshed_exit_orders,
        "intended_refresh_cancellations": intended_refresh_cancellations,
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
        environment=context.config.centaur_environment,
        mode=context.config.centaur_mode,
        source_environment="shadow",
        broker_id=context.config.paper_execution_equity_broker_id,
        data_provider="alpaca",
        execution_provider="shadow",
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
        "rejection_summary": batch.rejection_summary,
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
    for proposal in proposals:
        proposal.setdefault("environment", context.config.centaur_environment)
        proposal.setdefault("mode", context.config.centaur_mode)
        proposal.setdefault("source_environment", "shadow")
        proposal.setdefault("data_provider", proposal.get("source", "alpaca"))
        proposal.setdefault("execution_provider", "shadow")
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
            positions_summary = context.state.get(
                _positions_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            orders_summary = context.state.get(
                _orders_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            open_positions = int(positions_summary.get("open_positions", 0) or 0)
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
            positions_summary = context.state.get(
                _positions_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            orders_summary = context.state.get(
                _orders_state_key_for_broker(broker_id),
                {},
            ).get("summary", {})
            open_positions = int(positions_summary.get("open_positions", 0) or 0)
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
    primary_paper_brokers = {
        str(config.paper_execution_equity_broker_id or "alpaca_paper").strip().lower(),
        str(config.paper_execution_crypto_broker_id or "alpaca_paper").strip().lower(),
    }
    paper_submitted_orders = [
        order
        for order in list(context.state.get("execution", {}).get("orders", []))
        if str(order.get("broker_id", "")).strip().lower() in primary_paper_brokers
    ]
    submitted_paper_proposal_ids = {
        str(order.get("proposal_id", "")).strip()
        for order in paper_submitted_orders
        if str(order.get("proposal_id", "")).strip()
    }
    submitted_paper_approvals = [
        approval
        for approval in paper_approvals
        if str(approval.get("proposal_id", "")).strip() in submitted_paper_proposal_ids
        and str(approval.get("broker_id", "")).strip().lower() in primary_paper_brokers
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
    """Submit only CFO-approved paper entries and persist broker responses.

    Execution does not re-rank or resize proposals. It sends the exact approved
    order request through the selected broker adapter, captures any broker error,
    and writes submitted orders with their planned exits for later management.
    """
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
    """Submit approved live follower entries and persist the live audit trail.

    Live execution is deliberately downstream of paper submission and live CFO.
    This step only sends orders that survived those gates, then stores Alpaca
    Live responses separately so live-vs-paper drift remains reviewable.
    """
    approvals = list(context.state.get("live_risk_cfo", {}).get("approved_order_requests", []))
    if not _live_runtime_allows_order_mutation(context):
        result = {
            "broker": "alpaca_live",
            "orders_submitted": 0,
            "orders_saved": 0,
            "execution_status": "live_dry" if approvals else "idle",
            "mode": "live_dry" if _live_runtime_allows_broker_reads(context) else "skipped",
            "reason": "runtime_mode_not_live_order_mutation",
            "intended_orders": len(approvals),
        }
        context.state["execution_live"] = result
        return result
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
    router = ExecutionRouter()
    for approval in approvals:
        routed = router.route_entry_approval(
            context=context,
            approval=approval,
            lane="live",
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


def slack_notifications(context: TickContext) -> PipelineResult:
    """Send one-way operator alerts to Slack with persisted dedupe.

    Slack is intentionally notification-only. This step reports broker/risk
    conditions but never accepts commands or mutates trading state.
    """
    if not bool(getattr(context.config, "slack_alerts_enabled", False)):
        result = {"channel": "slack", "mode": "disabled", "alerts_built": 0}
        context.state["slack_notifications"] = result
        return result
    webhook_url = str(getattr(context.config, "slack_webhook_url", "") or "").strip()
    if not webhook_url:
        result = {
            "channel": "slack",
            "mode": "not_configured",
            "alerts_built": 0,
            "reason": "slack_webhook_url_missing",
        }
        context.state["slack_notifications"] = result
        return result

    alerts = _build_slack_alerts(context)
    if not alerts:
        result = {"channel": "slack", "mode": "idle", "alerts_built": 0}
        context.state["slack_notifications"] = result
        return result

    sender = context.metadata.get("slack_post_message")
    client = None
    if not callable(sender):
        client = SlackWebhookClient(
            webhook_url=webhook_url,
            timeout_seconds=int(
                getattr(context.config, "slack_request_timeout_seconds", 5) or 5
            ),
        )

    sent: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for alert in alerts:
        event_key = str(alert.get("event_key", "")).strip()
        dedupe_minutes = max(
            1,
            int(
                alert.get("dedupe_minutes")
                or getattr(context.config, "slack_alert_dedupe_minutes", 360)
                or 360
            ),
        )
        dedupe_since = context.started_at - timedelta(minutes=dedupe_minutes)
        if context.usage_ledger.notification_recently_sent(
            channel="slack",
            event_key=event_key,
            since=dedupe_since,
        ):
            skipped.append(
                {
                    "event_key": event_key,
                    "reason": "deduped",
                    "dedupe_minutes": dedupe_minutes,
                }
            )
            continue
        text = _format_slack_alert(alert)
        try:
            if callable(sender):
                sender(webhook_url, text)
            elif client is not None:
                client.post_message(text)
            context.usage_ledger.record_notification_event(
                tick_id=context.tick_id,
                channel="slack",
                event_key=event_key,
                level=str(alert.get("level", "info")),
                summary=str(alert.get("summary", "")),
                detail=str(alert.get("detail", "")),
                status="sent",
                metadata={"dedupe_minutes": dedupe_minutes},
                sent_at=context.started_at,
            )
            context.record_api_usage(
                source="slack",
                endpoint="incoming_webhook",
                success=True,
                metadata={"event_key": event_key},
            )
            sent.append({"event_key": event_key})
        except (SlackNotificationError, Exception) as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            context.usage_ledger.record_notification_event(
                tick_id=context.tick_id,
                channel="slack",
                event_key=event_key,
                level=str(alert.get("level", "info")),
                summary=str(alert.get("summary", "")),
                detail=str(alert.get("detail", "")),
                status="error",
                error=error_text,
                metadata={"dedupe_minutes": dedupe_minutes},
                sent_at=context.started_at,
            )
            context.record_api_usage(
                source="slack",
                endpoint="incoming_webhook",
                success=False,
                metadata={"event_key": event_key, "error": error_text},
            )
            errors.append({"event_key": event_key, "error": error_text})

    result = {
        "channel": "slack",
        "mode": "alerts",
        "alerts_built": len(alerts),
        "alerts_sent": len(sent),
        "alerts_deduped": len(skipped),
        "errors": len(errors),
    }
    if sent:
        result["sent"] = sent
    if skipped:
        result["skipped"] = skipped
    if errors:
        result["first_error"] = errors[0]["error"]
    context.state["slack_notifications"] = result
    return result


def _build_slack_alerts(context: TickContext) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    live_exit = context.state.get("live_exit_management", {})
    if isinstance(live_exit, dict):
        for item in live_exit.get("errors", []) or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "-").upper()
            reason = str(item.get("error") or "live exit error").strip()
            alerts.append(
                {
                    "level": "critical",
                    "event_key": f"live_exit_error:{symbol}:{_alert_key(reason)}",
                    "summary": f"Live exit error for {symbol}",
                    "detail": reason,
                }
            )

    pdt_basis = _live_alpaca_pdt_basis_equity(context)
    if pdt_basis is not None and pdt_basis < ALPACA_PDT_MIN_EQUITY_USD:
        alerts.append(
            {
                "level": "warning",
                "event_key": "alpaca_live_equity_pdt_guard_active",
                "summary": "Alpaca Live equity entries are blocked by PDT guard",
                "detail": (
                    f"PDT basis ${pdt_basis:.2f} is below "
                    f"${ALPACA_PDT_MIN_EQUITY_USD:.2f}; crypto is unaffected."
                ),
            }
        )
        review_start_date = _parse_iso_date(
            getattr(
                context.config,
                "live_equity_pdt_review_reminder_start_date",
                "2026-06-04",
            )
        )
        review_reminders_enabled = bool(
            getattr(context.config, "live_equity_pdt_review_reminders_enabled", True)
        )
        review_interval_minutes = max(
            1,
            int(
                getattr(
                    context.config,
                    "live_equity_pdt_review_reminder_interval_minutes",
                    30,
                )
                or 30
            ),
        )
        if (
            review_reminders_enabled
            and review_start_date is not None
            and context.started_at.date() >= review_start_date
        ):
            alerts.append(
                {
                    "level": "warning",
                    "event_key": "alpaca_intraday_margin_review_due_20260604",
                    "summary": "Action required: review live equity PDT unblock",
                    "detail": (
                        "Alpaca announced the new intraday margin framework for "
                        f"{review_start_date.isoformat()}, but Centaur must observe "
                        "live API/account behavior before explicitly unblocking "
                        "equities. This reminder repeats until "
                        "LIVE_EQUITY_PDT_REVIEW_REMINDERS_ENABLED is turned off "
                        "or the guard is explicitly reviewed."
                    ),
                    "dedupe_minutes": review_interval_minutes,
                }
            )
    return alerts


def _format_slack_alert(alert: dict[str, Any]) -> str:
    level = str(alert.get("level", "info")).upper()
    summary = str(alert.get("summary", "")).strip() or "Centaur alert"
    detail = str(alert.get("detail", "")).strip()
    if detail:
        return f"[Project Centaur] {level}: {summary}\n{detail}"
    return f"[Project Centaur] {level}: {summary}"


def _live_alpaca_pdt_basis_equity(context: TickContext) -> float | None:
    account_state = context.state.get("alpaca_live_account", {})
    if not isinstance(account_state, dict):
        return None
    raw_account = account_state.get("raw", {})
    summary = account_state.get("summary", {})
    if not isinstance(raw_account, dict):
        raw_account = {}
    if not isinstance(summary, dict):
        summary = {}
    return (
        _as_float(raw_account.get("last_equity"))
        or _as_float(summary.get("last_equity"))
        or _as_float(raw_account.get("equity"))
        or _as_float(summary.get("equity"))
    )


def _alert_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80] or "alert"


def _parse_iso_date(value: Any) -> date | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return date.fromisoformat(text)
    except ValueError:
        return None


def build_default_pipeline() -> list[StepDefinition]:
    return [
        StepDefinition(name="control.heartbeat", runner=control_heartbeat),
        StepDefinition(name="alpaca.account", runner=alpaca_account),
        StepDefinition(name="alpaca.clock", runner=alpaca_clock),
        StepDefinition(name="alpaca.positions", runner=alpaca_positions),
        StepDefinition(name="alpaca.orders", runner=alpaca_orders),
        StepDefinition(name="alpaca_live.sync", runner=alpaca_live_sync),
        StepDefinition(name="trading212_paper.sync", runner=trading212_paper_sync),
        StepDefinition(name="risk.daily_protection", runner=daily_protection),
        StepDefinition(name="risk.live_daily_protection", runner=live_daily_protection),
        StepDefinition(name="risk.trailing_drawdown_observer", runner=trailing_drawdown_observer),
        StepDefinition(name="maintenance.stale_orders", runner=stale_order_reaper),
        StepDefinition(name="maintenance.live_stale_orders", runner=live_stale_order_reaper),
        StepDefinition(name="market.gate", runner=market_gate),
        StepDefinition(name="fx.gbp_reference", runner=fx_gbp_reference),
        StepDefinition(name="risk.trading212_paper_daily_protection", runner=trading212_paper_daily_protection),
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
        StepDefinition(name="notifications.slack", runner=slack_notifications),
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
    broker_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Convert one shadow proposal into an auditable paper approval or veto.

    The returned approval carries the broker id, fixed notional, entry/exit plan,
    and order request that will be persisted if submitted. Rejections are kept as
    structured reasons so status can explain why a signal did not become a trade.
    """
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
    if asset_class == "equity" and _equity_friday_entry_cutoff_active(
        config,
        context.started_at,
        next_close=market_gate.get("next_close"),
    ):
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "reason": "friday_entry_cutoff_no_weekend_carry",
        }
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

    notional_usd = _notional_usd_for_broker(context, broker_id)
    if notional_usd <= 0:
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "qty_too_small"}

    broker_id = (
        str(broker_id or "").strip().lower()
        or _paper_execution_broker_id_for_asset_class(
            config=config,
            asset_class=asset_class,
        )
    )
    try:
        adapter = get_execution_adapter(context, broker_id)
    except ExecutionAdapterError:
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
        lane=broker_id,
    )
    try:
        order_request = adapter.build_entry_order_request(
            context=context,
            proposal=proposal,
            client_order_id=client_order_id,
            notional_usd=notional_usd,
            limit_buffer_bps=_paper_limit_buffer_bps(config, asset_class),
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
    except ExecutionAdapterError:
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
    """Apply live follower entry checks without creating an independent strategy.

    Live approvals mirror paper economics but remain gated by the live broker,
    live daily protection, activation acknowledgement, and same-paper-order
    follower rule handled upstream. This helper only builds a candidate request
    after those capital-preservation assumptions are still true.
    """
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
    broker_id = _live_execution_broker_id_for_asset_class(
        config=config,
        asset_class=asset_class,
    )
    if config.live_execution_equity_only and asset_class != "equity":
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "non_equity_blocked_live"}
    if (
        asset_class == "equity"
        and config.live_execution_require_market_open
        and not bool(market_gate.get("market_open"))
    ):
        return None, {"symbol": symbol, "strategy_id": strategy_id, "reason": "market_closed"}
    pdt_rejection = _live_equity_pdt_entry_rejection(
        context=context,
        broker_id=broker_id,
        asset_class=asset_class,
    )
    if pdt_rejection is not None:
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "broker_id": broker_id,
            "reason": pdt_rejection,
        }
    if asset_class == "equity" and _equity_friday_entry_cutoff_active(
        config,
        context.started_at,
        next_close=market_gate.get("next_close"),
    ):
        return None, {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "reason": "friday_entry_cutoff_no_weekend_carry_live",
        }
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

    try:
        adapter = get_execution_adapter(context, broker_id)
    except ExecutionAdapterError:
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
            context=context,
            proposal=proposal,
            client_order_id=client_order_id,
            notional_usd=notional_usd,
            limit_buffer_bps=_live_limit_buffer_bps(config, asset_class),
            usd_to_gbp=_as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp")),
        )
    except ExecutionAdapterError:
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


def _live_equity_pdt_entry_rejection(
    *,
    context: TickContext,
    broker_id: str,
    asset_class: str,
) -> str | None:
    """Fail closed before live equity entries that may become broker-blocked exits.

    Alpaca Live can reject same-day equity exits under pattern-day-trading
    protection when prior closing equity is below the regulatory threshold.
    Centaur's live follower must not enter an equity position unless it can
    prove the account is above that threshold; existing exits still route so the
    operator can reduce exposure whenever the broker permits it.
    """
    if str(asset_class).strip().lower() != "equity":
        return None
    if str(broker_id).strip().lower() != "alpaca_live":
        return None

    account_state = context.state.get("alpaca_live_account", {})
    if not isinstance(account_state, dict):
        return "pdt_equity_status_unknown_live"
    raw_account = account_state.get("raw", {})
    summary = account_state.get("summary", {})
    if not isinstance(raw_account, dict):
        raw_account = {}
    if not isinstance(summary, dict):
        summary = {}

    pdt_basis_equity = (
        _as_float(raw_account.get("last_equity"))
        or _as_float(summary.get("last_equity"))
        or _as_float(raw_account.get("equity"))
        or _as_float(summary.get("equity"))
    )
    if pdt_basis_equity is None:
        return "pdt_equity_status_unknown_live"
    if pdt_basis_equity < ALPACA_PDT_MIN_EQUITY_USD:
        return "pdt_equity_entry_blocked_live"
    return None


def _paper_execution_broker_id_for_asset_class(*, config: Any, asset_class: str) -> str:
    normalized = str(asset_class or "").strip().lower()
    if normalized == "crypto":
        return str(config.paper_execution_crypto_broker_id or "alpaca_paper").strip().lower()
    return str(config.paper_execution_equity_broker_id or "alpaca_paper").strip().lower()


def _paper_execution_broker_ids_for_asset_class(
    *,
    context: TickContext,
    asset_class: str,
) -> list[str]:
    config = context.config
    normalized = str(asset_class or "").strip().lower()
    primary = _paper_execution_broker_id_for_asset_class(
        config=config,
        asset_class=asset_class,
    )
    broker_ids = [primary] if primary else []
    if normalized == "equity" and _paper_trading212_enabled(context):
        broker_ids.append("trading212_paper")
    deduped: list[str] = []
    for broker_id in broker_ids:
        if broker_id and broker_id not in deduped:
            deduped.append(broker_id)
    return deduped


def _active_paper_broker_ids(context: TickContext) -> list[str]:
    broker_ids: list[str] = []
    for asset_class in ("equity", "crypto"):
        for broker_id in _paper_execution_broker_ids_for_asset_class(
            context=context,
            asset_class=asset_class,
        ):
            if broker_id not in broker_ids:
                broker_ids.append(broker_id)
    return broker_ids


def _paper_trading212_enabled(context: TickContext) -> bool:
    return bool(
        getattr(context.config, "trading212_paper_execution_enabled", True)
        and getattr(context.config, "trading212_paper_api_configured", False)
    )


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
    """Calculate dynamic slots from tracked P/L without changing order size.

    The earned-slot rule compounds capacity only in full fixed-notional units
    above the pre-first-order baseline. It never widens per-trade notional, and
    the returned values are recorded so slot changes are auditable.
    """
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


def _account_state_key_for_broker(broker_id: str) -> str:
    normalized = str(broker_id or "").strip().lower()
    if normalized == "alpaca_live":
        return "alpaca_live_account"
    if normalized == "alpaca_paper":
        return "alpaca_account"
    if normalized == "trading212_paper":
        return "trading212_paper_account"
    return f"{normalized}_account"


def _positions_state_key_for_broker(broker_id: str) -> str:
    normalized = str(broker_id or "").strip().lower()
    if normalized == "alpaca_live":
        return "alpaca_live_positions"
    if normalized == "alpaca_paper":
        return "alpaca_positions"
    return f"{normalized}_positions"


def _orders_state_key_for_broker(broker_id: str) -> str:
    normalized = str(broker_id or "").strip().lower()
    if normalized == "alpaca_live":
        return "alpaca_live_orders"
    if normalized == "alpaca_paper":
        return "alpaca_orders"
    return f"{normalized}_orders"


def _paper_protection_state_key_for_broker(broker_id: str) -> str:
    normalized = str(broker_id or "").strip().lower()
    if normalized == "alpaca_paper":
        return "daily_protection"
    return f"{normalized}_daily_protection"


def _slot_size_native_for_broker(context: TickContext, broker_id: str) -> float:
    slot_size_usd = float(context.config.paper_execution_default_notional_usd)
    if str(broker_id or "").strip().lower() == "trading212_paper":
        return float(
            getattr(
                context.config,
                "trading212_paper_default_notional_native",
                10.0,
            )
        )
    return slot_size_usd


def _notional_usd_for_broker(context: TickContext, broker_id: str) -> float:
    if str(broker_id or "").strip().lower() == "trading212_paper":
        native_notional = float(
            getattr(
                context.config,
                "trading212_paper_default_notional_native",
                10.0,
            )
        )
        usd_to_gbp = _as_float(context.state.get("fx_gbp_reference", {}).get("usd_to_gbp"))
        if usd_to_gbp is not None and usd_to_gbp > 0:
            return round(native_notional / usd_to_gbp, 2)
    return round(float(context.config.paper_execution_default_notional_usd), 2)


def _native_equity_to_usd(
    value: float | None,
    *,
    currency: str,
    usd_to_gbp: float | None,
) -> float | None:
    if value is None:
        return None
    if str(currency or "").strip().upper() == "GBP":
        rate = float(usd_to_gbp or 0.0)
        if rate <= 0:
            return None
        return round(float(value) / rate, 6)
    return float(value)


def _build_trailing_drawdown_observation(
    *,
    context: TickContext,
    broker_id: str,
    account_state_key: str,
    session_open_at: datetime,
    threshold_usd: float,
    threshold_pct: float,
) -> dict[str, Any]:
    account_state = context.state.get(account_state_key, {})
    summary = account_state.get("summary", {}) if isinstance(account_state, dict) else {}
    raw_account = account_state.get("raw", {}) if isinstance(account_state, dict) else {}
    current_equity = _as_float(summary.get("equity"))
    if current_equity is None and isinstance(raw_account, dict):
        current_equity = _as_float(raw_account.get("equity"))
    high_water_row = context.usage_ledger.get_broker_account_high_water(
        broker_id=broker_id,
        since=session_open_at,
    )
    high_water_equity = (
        _as_float(high_water_row.get("equity")) if isinstance(high_water_row, dict) else None
    )
    if high_water_equity is None:
        high_water_equity = current_equity
    if current_equity is None or high_water_equity is None or high_water_equity <= 0:
        return {
            "broker_id": broker_id,
            "mode": "observe_only",
            "status": "unknown",
            "reason": "equity_unavailable",
            "threshold_usd": max(0.0, threshold_usd),
            "threshold_pct": max(0.0, threshold_pct),
            "would_block_new_entries": False,
            "affects_execution": False,
        }

    giveback_usd = round(max(0.0, high_water_equity - current_equity), 6)
    giveback_pct = round(giveback_usd / high_water_equity, 8)
    usd_triggered = threshold_usd > 0 and giveback_usd >= threshold_usd
    pct_triggered = threshold_pct > 0 and giveback_pct >= threshold_pct
    would_block = bool(usd_triggered or pct_triggered)
    action = "would_block_new_entries" if would_block else "would_allow_new_entries"
    observation = {
        "broker_id": broker_id,
        "mode": "observe_only",
        "status": "observed",
        "current_equity": current_equity,
        "high_water_equity": high_water_equity,
        "high_water_tick_id": (
            high_water_row.get("tick_id") if isinstance(high_water_row, dict) else None
        ),
        "high_water_at": (
            high_water_row.get("captured_at") if isinstance(high_water_row, dict) else None
        ),
        "giveback_usd": giveback_usd,
        "giveback_pct": giveback_pct,
        "threshold_usd": max(0.0, threshold_usd),
        "threshold_pct": max(0.0, threshold_pct),
        "would_block_new_entries": would_block,
        "would_trigger_usd": bool(usd_triggered),
        "would_trigger_pct": bool(pct_triggered),
        "hypothetical_action": action,
        "affects_execution": False,
    }
    return observation


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


def _find_most_protective_managed_entry_order(
    *,
    symbol: str,
    orders: list[dict[str, Any]],
    broker_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the safest still-open managed entry plan for an aggregated position.

    Alpaca aggregates same-symbol buys into one long position, but Centaur can
    enter that symbol more than once with different persisted stops. The exit
    manager sells the whole broker position, so it must use the highest
    still-open stop for capital preservation instead of simply using the latest
    entry plan and letting an older lot drift past its own stop.
    """
    symbol_upper = symbol.upper()
    symbol_key = _normalized_symbol_key(symbol_upper)
    broker_filter = str(broker_id or "").strip().lower()
    open_lots: list[dict[str, Any]] = []

    ordered = sorted(
        orders,
        key=lambda order: (
            _order_activity_timestamp(order),
            str(order.get("order_id") or order.get("id") or ""),
        ),
    )
    for order in ordered:
        order_symbol = str(order.get("symbol", "")).upper()
        if order_symbol != symbol_upper and _normalized_symbol_key(order_symbol) != symbol_key:
            continue
        if broker_filter and str(order.get("broker_id", "")).strip().lower() != broker_filter:
            continue
        side = str(order.get("side", "")).lower()
        if side not in {"buy", "sell"}:
            continue
        qty = _order_filled_qty(order)
        if qty <= 0:
            continue

        if side == "buy":
            open_lots.append(
                {
                    "qty": qty,
                    "order": order,
                    "managed": _order_has_managed_exit_plan(order),
                }
            )
            continue

        remaining = qty
        while remaining > 0 and open_lots:
            lot = open_lots[0]
            lot_qty = _as_float(lot.get("qty")) or 0.0
            if lot_qty <= 0:
                open_lots.pop(0)
                continue
            matched = min(lot_qty, remaining)
            lot["qty"] = lot_qty - matched
            remaining -= matched
            if (_as_float(lot.get("qty")) or 0.0) <= 0.000000001:
                open_lots.pop(0)

    managed_lots = [
        lot
        for lot in open_lots
        if lot.get("managed") and (_as_float(lot.get("qty")) or 0.0) > 0
    ]
    if not managed_lots:
        return None

    selected = max(
        managed_lots,
        key=lambda lot: (
            _managed_entry_stop_loss_price(lot.get("order", {})) or 0.0,
            _order_activity_timestamp(lot.get("order", {})),
        ),
    )
    selected_order = dict(selected.get("order", {}))
    if len(managed_lots) > 1:
        raw = selected_order.get("raw_json", {})
        if not isinstance(raw, dict):
            raw = {}
        raw = dict(raw)
        raw["managed_entry_selection"] = "most_protective_open_lot"
        raw["managed_open_lots_considered"] = len(managed_lots)
        raw["managed_selected_stop_loss_price"] = _managed_entry_stop_loss_price(
            selected_order
        )
        selected_order["raw_json"] = raw
    return selected_order


def _find_latest_managed_entry_order(
    *,
    symbol: str,
    orders: list[dict[str, Any]],
    broker_id: str | None = None,
) -> dict[str, Any] | None:
    return _find_most_protective_managed_entry_order(
        symbol=symbol,
        orders=orders,
        broker_id=broker_id,
    )


def _order_has_managed_exit_plan(order: dict[str, Any]) -> bool:
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
    return has_planned_raw or has_persisted_plan


def _managed_entry_stop_loss_price(order: dict[str, Any]) -> float | None:
    raw = order.get("raw_json", {})
    if not isinstance(raw, dict):
        raw = {}
    return _as_float(
        raw.get("planned_stop_loss_price", order.get("stop_loss_price"))
    )


def _order_filled_qty(order: dict[str, Any]) -> float:
    return _as_float(order.get("filled_qty")) or _as_float(order.get("qty")) or 0.0


def _order_activity_timestamp(order: dict[str, Any]) -> float:
    activity_at = _coerce_datetime(
        order.get("submitted_at") or order.get("captured_at") or order.get("updated_at")
    )
    if activity_at is None:
        return 0.0
    try:
        return activity_at.timestamp()
    except (OverflowError, OSError, ValueError):
        return 0.0


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
    """Build one managed sell request or a skip reason for audit.

    The decision order is capital-preservation first: stop, profit capture,
    target, Friday no-weekend flatten, and then policy-specific time exits.
    Red max-hold deferrals deliberately avoid realizing a loss solely because a
    timer elapsed while leaving stop/profit rules active.
    """
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
    asset_class = str(entry_order.get("asset_class", "")).strip().lower()

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
        or _as_float(raw.get("filled_avg_price"))
        or _as_float(proposal_plan.get("entry_price"))
        or _as_float(proposal_raw.get("entry_price"))
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
    elif _equity_friday_flatten_due(
        context.config,
        asset_class=asset_class,
        as_of=as_of,
        next_close=context.state.get("market_gate", {}).get("next_close"),
    ):
        exit_reason = "friday_no_weekend_carry"
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
            if (
                profit_reference_price is not None
                and entry_reference_price is not None
                and profit_reference_price < entry_reference_price
            ):
                return None, "max_hold_red_deferred"
            exit_reason = "max_holding_window_elapsed"
        else:
            return None, "exit_not_due"
    elif (
        holding_window_minutes > 0
        and entry_submitted_at is not None
        and as_of >= entry_submitted_at + timedelta(minutes=holding_window_minutes)
    ):
        if managed_exit_policy == "profit_capture_else_1d":
            time_exit_reference_price = close_price or current_price
            if (
                time_exit_reference_price is not None
                and entry_reference_price is not None
                and time_exit_reference_price < entry_reference_price
            ):
                return None, "max_hold_red_deferred"
            exit_reason = "max_holding_window_elapsed"
        else:
            exit_reason = "holding_window_elapsed"
    else:
        return None, "exit_not_due"

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
        adapter = get_execution_adapter(context, broker_id)
        order_request = adapter.build_exit_order_request(
            context=context,
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
    except ExecutionAdapterError:
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
