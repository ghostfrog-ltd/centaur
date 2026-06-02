from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.framework.core.instruments import InstrumentRegistry, default_instrument_registry

from .mode_context import mode_context_from_config

if TYPE_CHECKING:
    from app.framework.runtime.models import TickContext


class LiveRiskGuardError(RuntimeError):
    """Raised when a live order fails the final pre-submit guard."""


class LiveRiskGuard:
    """Final live-order guard immediately before broker mutation.

    Earlier CFO gates decide eligibility and build the order request. This guard
    re-checks the safety-critical live facts at the execution boundary so a
    malformed state handoff cannot silently become a real-money order.
    """

    def __init__(self, *, instrument_registry: InstrumentRegistry | None = None) -> None:
        self.instrument_registry = instrument_registry or default_instrument_registry()

    def assert_entry_allowed(
        self,
        *,
        context: TickContext,
        approval: dict[str, Any],
    ) -> None:
        self.assert_order_action_allowed(
            context=context,
            broker_id=str(approval.get("broker_id", "")),
            action="entry",
            strategy_id=str(approval.get("strategy_id", "")),
            notional_usd=approval.get("notional_usd"),
            order_request=approval.get("order_request"),
        )

    def assert_order_action_allowed(
        self,
        *,
        context: TickContext,
        broker_id: str,
        action: str,
        strategy_id: str | None = None,
        notional_usd: Any = None,
        order_request: dict[str, Any] | None = None,
    ) -> None:
        config = context.config
        mode_context = mode_context_from_config(config)
        if not mode_context.can_mutate_live_broker:
            raise LiveRiskGuardError("runtime_mode_not_live")
        if not bool(getattr(config, "live_execution_enabled", False)):
            raise LiveRiskGuardError("live_execution_disabled")
        if bool(getattr(config, "live_execution_kill_switch", True)):
            raise LiveRiskGuardError("live_kill_switch_on")
        if (
            str(getattr(config, "live_execution_activation_ack", "")).strip()
            != "LIVE_TRADING_APPROVED"
        ):
            raise LiveRiskGuardError("activation_ack_missing")

        normalized_broker_id = str(broker_id).strip().lower()
        allowed_live_brokers = {
            str(getattr(config, "live_execution_equity_broker_id", "")).strip().lower(),
            str(getattr(config, "live_execution_crypto_broker_id", "")).strip().lower(),
        }
        allowed_live_brokers.discard("")
        if normalized_broker_id not in allowed_live_brokers:
            raise LiveRiskGuardError("broker_not_live_enabled")
        if normalized_broker_id == "trading212_live":
            if not bool(getattr(config, "trading212_live_execution_enabled", False)):
                raise LiveRiskGuardError("trading212_live_disabled")
            raise LiveRiskGuardError("trading212_live_not_approved")

        normalized_action = str(action or "").strip().lower()
        if normalized_action in {"entry", "exit"}:
            normalized_strategy_id = str(strategy_id or "").strip().lower()
            allowed_strategies = {
                str(item).strip().lower()
                for item in getattr(config, "live_execution_allowed_strategies", ())
                if str(item).strip()
            }
            if not allowed_strategies:
                raise LiveRiskGuardError("no_live_strategies_allowed")
            if normalized_strategy_id not in allowed_strategies:
                raise LiveRiskGuardError("strategy_not_allowed_live")
            self._assert_instrument_allowed(
                broker_id=normalized_broker_id,
                order_request=order_request,
            )
            self._assert_live_sync_ready(
                context=context,
                broker_id=normalized_broker_id,
            )
            self._assert_latest_bar_available(
                context=context,
                order_request=order_request,
            )

        if normalized_action == "entry":
            self._assert_entry_capacity(
                context=context,
                broker_id=normalized_broker_id,
            )
            parsed_notional_usd = _as_float(notional_usd)
            max_notional_usd = _as_float(
                getattr(config, "live_execution_default_notional_usd", None)
            )
            if parsed_notional_usd is None or parsed_notional_usd <= 0:
                raise LiveRiskGuardError("invalid_live_notional")
            if max_notional_usd is not None and parsed_notional_usd > max_notional_usd:
                raise LiveRiskGuardError("live_notional_above_limit")

    def _assert_instrument_allowed(
        self,
        *,
        broker_id: str,
        order_request: dict[str, Any] | None,
    ) -> None:
        if not isinstance(order_request, dict):
            raise LiveRiskGuardError("missing_order_request")

        symbol = str(order_request.get("symbol") or "").strip().upper()
        if not symbol:
            raise LiveRiskGuardError("missing_live_symbol")

        broker_venue = _venue_for_broker(broker_id)
        explicit_venue = str(order_request.get("venue") or "").strip().lower()
        lookup_venue = explicit_venue or broker_venue

        canonical_id = str(order_request.get("canonical_instrument_id") or "").strip()
        if canonical_id and broker_venue:
            known_instrument = self.instrument_registry.get(canonical_id)
            execution_mapping = self.instrument_registry.execution_symbol_for(
                canonical_instrument_id=canonical_id,
                venue=broker_venue,
            )
            if known_instrument is not None and execution_mapping is None:
                raise LiveRiskGuardError("instrument_not_executable_live")

        if lookup_venue:
            if explicit_venue and broker_venue and explicit_venue != broker_venue:
                raise LiveRiskGuardError("instrument_venue_mismatch_live")
            resolved = self.instrument_registry.resolve_venue_symbol(
                venue=lookup_venue,
                venue_symbol=symbol,
            )
            if resolved is not None and not resolved[1].can_use_for_execution:
                raise LiveRiskGuardError("instrument_not_executable_live")

    def _assert_live_sync_ready(
        self,
        *,
        context: TickContext,
        broker_id: str,
    ) -> None:
        account_state = _state_for_broker(context=context, broker_id=broker_id, kind="account")
        positions_state = _state_for_broker(context=context, broker_id=broker_id, kind="positions")
        orders_state = _state_for_broker(context=context, broker_id=broker_id, kind="orders")
        if not account_state or not positions_state or not orders_state:
            raise LiveRiskGuardError("live_sync_missing")
        account_summary = _as_dict(account_state.get("summary"))
        if not account_summary:
            raise LiveRiskGuardError("live_account_snapshot_missing")
        status = str(account_summary.get("status", "")).strip().upper()
        if status != "ACTIVE":
            raise LiveRiskGuardError("live_account_not_active")
        if bool(account_summary.get("trading_blocked") or account_summary.get("account_blocked")):
            raise LiveRiskGuardError("live_account_blocked")
        if bool(account_summary.get("trade_suspended_by_user")):
            raise LiveRiskGuardError("live_user_trade_suspension")
        if "summary" not in positions_state or "summary" not in orders_state:
            raise LiveRiskGuardError("live_sync_incomplete")

    def _assert_entry_capacity(
        self,
        *,
        context: TickContext,
        broker_id: str,
    ) -> None:
        positions_state = _state_for_broker(context=context, broker_id=broker_id, kind="positions")
        orders_state = _state_for_broker(context=context, broker_id=broker_id, kind="orders")
        positions_summary = _as_dict(positions_state.get("summary") if positions_state else {})
        orders_summary = _as_dict(orders_state.get("summary") if orders_state else {})
        open_positions = int(positions_summary.get("open_positions", 0) or 0)
        open_orders = int(orders_summary.get("open_orders", 0) or 0)
        max_positions = int(getattr(context.config, "live_execution_max_open_positions", 0) or 0)
        if max_positions > 0 and open_positions + open_orders >= max_positions:
            raise LiveRiskGuardError("max_live_positions_reached")

    def _assert_latest_bar_available(
        self,
        *,
        context: TickContext,
        order_request: dict[str, Any] | None,
    ) -> None:
        if not isinstance(order_request, dict):
            raise LiveRiskGuardError("missing_order_request")
        symbol = str(order_request.get("symbol") or "").strip().upper()
        if not symbol:
            raise LiveRiskGuardError("missing_live_symbol")
        bars = _latest_bars_by_symbol(context)
        latest_bar = bars.get(symbol) or bars.get(_normalized_symbol_key(symbol))
        if latest_bar is None:
            raise LiveRiskGuardError("latest_bar_unavailable")
        bar_timestamp = _coerce_datetime(latest_bar.get("t") or latest_bar.get("bar_timestamp"))
        if bar_timestamp is None:
            raise LiveRiskGuardError("latest_bar_timestamp_missing")


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _venue_for_broker(broker_id: str) -> str:
    normalized = str(broker_id or "").strip().lower()
    if "alpaca" in normalized:
        return "alpaca"
    if "binance" in normalized:
        return "binance"
    if "coinbase" in normalized:
        return "coinbase"
    if "ig" in normalized:
        return "ig"
    if "trading212" in normalized:
        return "trading212"
    return ""


def _state_for_broker(
    *,
    context: TickContext,
    broker_id: str,
    kind: str,
) -> dict[str, Any]:
    prefix = "alpaca_live" if broker_id == "alpaca_live" else broker_id
    value = context.state.get(f"{prefix}_{kind}")
    return value if isinstance(value, dict) else {}


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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
