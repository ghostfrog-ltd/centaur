from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from ..alpaca import (
    AlpacaApiError,
    get_alpaca_client,
    get_alpaca_live_client,
    summarize_account,
    summarize_clock,
    summarize_orders,
    summarize_positions,
)
from app.runtime.models import TickContext
from .base import BrokerAdapter, BrokerAdapterError


class AlpacaBrokerAdapter(BrokerAdapter):
    """Alpaca Paper adapter that preserves the approved micro-order envelope."""

    broker_id = "alpaca_paper"
    label = "Alpaca Paper"
    native_currency = "USD"
    state_prefix = "alpaca"
    supported_asset_classes = ("equity", "crypto")

    def _client(self, context: TickContext):
        return get_alpaca_client(context)

    def get_account(self, context: TickContext) -> dict[str, Any]:
        try:
            return self._client(context).get_account(context)
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_account(self, raw_account: dict[str, Any]) -> dict[str, Any]:
        return summarize_account(raw_account)

    def get_clock(self, context: TickContext) -> dict[str, Any]:
        try:
            return self._client(context).get_clock(context)
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_clock(self, raw_clock: dict[str, Any]) -> dict[str, Any]:
        return summarize_clock(raw_clock)

    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        try:
            return self._client(context).get_positions(context)
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_positions(self, raw_positions: list[dict[str, Any]]) -> dict[str, Any]:
        return summarize_positions(raw_positions)

    def get_orders(
        self,
        context: TickContext,
        *,
        after: datetime | None,
        limit: int,
        status: str = "all",
        nested: bool = True,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        try:
            return self._client(context).get_orders(
                context,
                status=status,
                after=after,
                limit=limit,
                nested=nested,
                direction=direction,
            )
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_orders(self, raw_orders: list[dict[str, Any]]) -> dict[str, Any]:
        return summarize_orders(raw_orders)

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._client(context).submit_order(
                context,
                order_request=order_request,
            )
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        try:
            self._client(context).cancel_order(context, order_id=order_id)
        except AlpacaApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def build_entry_order_request(
        self,
        *,
        proposal: dict[str, Any],
        client_order_id: str,
        notional_usd: float,
        limit_buffer_bps: float,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        """Build a marketable-limit entry without changing size or direction."""
        asset_class = str(proposal.get("asset_class", "")).strip().lower()
        entry_price = _to_float(proposal.get("entry_price"))
        symbol = str(proposal.get("symbol", "")).strip().upper()
        if entry_price is None or entry_price <= 0:
            raise BrokerAdapterError("Alpaca entry request requires a valid entry price.")
        if not symbol:
            raise BrokerAdapterError("Alpaca entry request requires a symbol.")
        return {
            "symbol": symbol,
            "side": "buy",
            "type": "limit",
            "limit_price": _format_order_price(
                _marketable_limit_price(
                    reference_price=entry_price,
                    side="buy",
                    limit_buffer_bps=limit_buffer_bps,
                )
            ),
            "time_in_force": _paper_limit_time_in_force(asset_class),
            "notional": _format_order_notional(notional_usd),
            "client_order_id": client_order_id,
        }

    def build_exit_order_request(
        self,
        *,
        symbol: str,
        asset_class: str,
        qty: float | str,
        reference_price: float,
        client_order_id: str,
        limit_buffer_bps: float,
        entry_order: dict[str, Any] | None = None,
        latest_bar: dict[str, Any] | None = None,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        """Build a marketable-limit sell exit using broker-reported quantity."""
        formatted_qty = _format_order_qty(qty)
        if formatted_qty == "0":
            raise BrokerAdapterError("Alpaca exit request requires a positive quantity.")
        if reference_price <= 0:
            raise BrokerAdapterError("Alpaca exit request requires a valid reference price.")
        return {
            "symbol": str(symbol).strip().upper(),
            "side": "sell",
            "type": "limit",
            "limit_price": _format_order_price(
                _marketable_limit_price(
                    reference_price=reference_price,
                    side="sell",
                    limit_buffer_bps=limit_buffer_bps,
                )
            ),
            "time_in_force": _paper_limit_time_in_force(asset_class),
            "qty": formatted_qty,
            "client_order_id": client_order_id,
        }


class AlpacaLiveBrokerAdapter(AlpacaBrokerAdapter):
    """Guarded Alpaca Live adapter for the dormant real-money readiness lane.

    Live shares the Alpaca transport with paper, but every order action is
    re-gated here so credentials or endpoint changes cannot silently turn paper
    behavior into live-money behavior. Entry buys remain subject to the live
    kill switch; sell/cancel paths are allowed only after explicit activation so
    a future go-live lane can protect or flatten positions.
    """

    broker_id = "alpaca_live"
    label = "Alpaca Live"
    native_currency = "USD"
    state_prefix = "alpaca_live"
    supported_asset_classes = ("equity", "crypto")

    def _client(self, context: TickContext):
        return get_alpaca_live_client(context)

    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        """Return the first live-entry blocker before building a buy order."""
        if not context.config.live_execution_enabled:
            return "live_execution_disabled"
        if context.config.live_execution_kill_switch:
            return "live_kill_switch_on"
        if not context.config.alpaca_live_api_configured:
            return "alpaca_live_credentials_missing"
        if context.config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
            return "activation_ack_missing"
        return super().validate_entry_constraints(
            context=context,
            proposal=proposal,
            notional_usd=notional_usd,
            usd_to_gbp=usd_to_gbp,
        )

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a live order only after the explicit go-live gates pass.

        The kill switch is treated as an entry switch: buy orders stay blocked
        while it is on, but activated sell exits can still protect capital.
        """
        if not context.config.live_execution_enabled:
            raise BrokerAdapterError("live_execution_disabled")
        side = str(order_request.get("side", "")).strip().lower()
        if context.config.live_execution_kill_switch and side == "buy":
            raise BrokerAdapterError("live_kill_switch_on")
        if context.config.live_execution_kill_switch and side != "sell":
            raise BrokerAdapterError("live_kill_switch_on")
        if not context.config.alpaca_live_api_configured:
            raise BrokerAdapterError("alpaca_live_credentials_missing")
        if context.config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
            raise BrokerAdapterError("activation_ack_missing")
        return super().submit_order(context, order_request=order_request)

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        """Cancel a live order only after activation gates prove intent.

        Cancellation is risk-reducing for stale entries and exit refreshes, but
        it still touches a live account, so it requires the same explicit
        enablement and acknowledgement as the live readiness lane.
        """
        if not context.config.live_execution_enabled:
            raise BrokerAdapterError("live_execution_disabled")
        if not context.config.alpaca_live_api_configured:
            raise BrokerAdapterError("alpaca_live_credentials_missing")
        if context.config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
            raise BrokerAdapterError("activation_ack_missing")
        return super().cancel_order(context, order_id=order_id)


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_order_qty(value: float | str) -> str:
    """Round down to Alpaca fractional precision to avoid overselling."""
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise BrokerAdapterError("Alpaca exit request requires a valid quantity.")
    if decimal_value <= 0:
        return "0"
    floored = decimal_value.quantize(Decimal("0.000000001"), rounding=ROUND_DOWN)
    if floored <= 0:
        return "0"
    return format(floored.normalize(), "f")


def _format_order_notional(value: float) -> str:
    return f"{value:.2f}"


def _format_order_price(value: float) -> str:
    precision = 4 if value < 1 else 2
    return f"{value:.{precision}f}"


def _paper_limit_time_in_force(asset_class: str) -> str:
    """Use Alpaca-supported TIF: crypto can IOC, fractional equities use DAY."""
    return "ioc" if str(asset_class).strip().lower() == "crypto" else "day"


def _marketable_limit_price(
    *,
    reference_price: float,
    side: str,
    limit_buffer_bps: float,
) -> float:
    buffer_multiplier = max(0.0, float(limit_buffer_bps or 0.0)) / 10_000.0
    if side == "buy":
        return max(0.0, reference_price * (1.0 + buffer_multiplier))
    return max(0.0, reference_price * (1.0 - buffer_multiplier))
