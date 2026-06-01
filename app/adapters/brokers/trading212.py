from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from app.adapters.trading212 import Trading212ApiError, Trading212PaperClient
from app.runtime.models import TickContext
from app.runtime.settings import RuntimeConfig
from .base import BrokerAdapter, BrokerAdapterError


class Trading212PaperBrokerAdapter(BrokerAdapter):
    """Trading 212 demo-account scaffold for a future paper execution lane.

    Trading 212 paper is a separate experimental account boundary, not a reason
    to blur Centaur's evidence. The adapter can validate fixed-notional equity
    requests and read paper-account state, but order mutation remains fail-closed
    until the lane has explicit approval, idempotency controls, and reporting.
    """

    broker_id = "trading212_paper"
    label = "Trading 212 Paper"
    native_currency = "GBP"
    state_prefix = "trading212_paper"
    supported_asset_classes = ("equity",)

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str,
        timeout_seconds: int,
        primary_currency: str,
        ticker_overrides: dict[str, str],
        api_configured: bool,
    ) -> None:
        self.api_key = str(api_key).strip()
        self.api_secret = str(api_secret).strip()
        self.base_url = str(base_url).strip()
        self.timeout_seconds = int(timeout_seconds)
        self.primary_currency = str(primary_currency or "GBP").strip().upper() or "GBP"
        self.native_currency = self.primary_currency
        self.ticker_overrides = {
            str(symbol).strip().upper(): str(ticker).strip()
            for symbol, ticker in ticker_overrides.items()
            if str(symbol).strip() and str(ticker).strip()
        }
        self.api_configured = bool(api_configured)

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "Trading212PaperBrokerAdapter":
        return cls(
            api_key=config.trading212_paper_api_key,
            api_secret=config.trading212_paper_api_secret,
            base_url=config.trading212_paper_base_url,
            timeout_seconds=config.trading212_paper_request_timeout_seconds,
            primary_currency=config.trading212_paper_primary_currency,
            ticker_overrides=config.trading212_paper_ticker_overrides,
            api_configured=config.trading212_paper_api_configured,
        )

    def _client(self) -> Trading212PaperClient:
        try:
            return Trading212PaperClient(
                api_key=self.api_key,
                api_secret=self.api_secret,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
            )
        except Trading212ApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def resolve_ticker(self, symbol: str) -> str | None:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        return self.ticker_overrides.get(normalized) or f"{normalized}_US_EQ"

    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        base_reason = super().validate_entry_constraints(
            context=context,
            proposal=proposal,
            notional_usd=notional_usd,
            usd_to_gbp=usd_to_gbp,
        )
        if base_reason is not None:
            return base_reason
        if not self.api_configured:
            return "trading212_paper_not_configured"
        if self.primary_currency == "GBP" and float(usd_to_gbp or 0.0) <= 0:
            return "fx_reference_unavailable"
        if self.resolve_ticker(str(proposal.get("symbol", ""))) is None:
            return "trading212_ticker_unmapped"
        return None

    def get_account(self, context: TickContext) -> dict[str, Any]:
        try:
            return self._client().get_account_cash(context)
        except Trading212ApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_account(self, raw_account: dict[str, Any]) -> dict[str, Any]:
        cash = _first_float(raw_account, ("free", "cash", "available", "total"))
        portfolio_value = _first_float(raw_account, ("total", "portfolioValue"))
        return {
            "status": "DEMO",
            "currency": self.primary_currency,
            "cash": cash,
            "equity": portfolio_value if portfolio_value is not None else cash,
            "buying_power": cash,
            "portfolio_value": portfolio_value,
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }

    def get_clock(self, context: TickContext) -> dict[str, Any]:
        raise BrokerAdapterError("Trading 212 paper adapter does not provide market clock yet.")

    def summarize_clock(self, raw_clock: dict[str, Any]) -> dict[str, Any]:
        raise BrokerAdapterError("Trading 212 paper adapter cannot summarize clock data yet.")

    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        try:
            return self._client().get_positions(context)
        except Trading212ApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_positions(self, raw_positions: list[dict[str, Any]]) -> dict[str, Any]:
        open_positions = [
            position
            for position in raw_positions
            if _to_float(position.get("quantity")) not in (None, 0.0)
        ]
        symbols = [
            _centaur_symbol_from_ticker(
                str(position.get("ticker") or position.get("symbol") or "")
            )
            for position in open_positions
        ]
        return {
            "open_positions": len(open_positions),
            "symbols": [symbol for symbol in symbols if symbol],
        }

    def get_orders(
        self,
        context: TickContext,
        *,
        after,
        limit: int,
        status: str = "all",
        nested: bool = True,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        try:
            return self._client().get_orders(context)[: max(0, int(limit))]
        except Trading212ApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc

    def summarize_orders(self, raw_orders: list[dict[str, Any]]) -> dict[str, Any]:
        open_orders = [
            order
            for order in raw_orders
            if str(order.get("status", "")).strip().lower()
            not in {"filled", "cancelled", "canceled", "rejected"}
        ]
        return {
            "open_orders": len(open_orders),
            "open_order_symbols": [
                _centaur_symbol_from_ticker(
                    str(order.get("ticker") or order.get("symbol") or "")
                )
                for order in open_orders
                if str(order.get("ticker") or order.get("symbol") or "").strip()
            ],
        }

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a Trading 212 demo limit order after Centaur gates pass.

        Trading 212 documents the order endpoint as non-idempotent, so this
        adapter refuses a client_order_id already seen in this tick or persisted
        in the order ledger before making the HTTP request.
        """
        client_order_id = str(order_request.get("client_order_id", "")).strip()
        if not client_order_id:
            raise BrokerAdapterError("Trading 212 paper orders require client_order_id.")
        seen = context.state.setdefault("submitted_client_order_ids", set())
        if client_order_id in seen:
            raise BrokerAdapterError("duplicate_client_order_id")
        exists = getattr(context.usage_ledger, "paper_order_client_id_exists", None)
        if callable(exists) and exists(
            broker_id=self.broker_id,
            client_order_id=client_order_id,
        ):
            raise BrokerAdapterError("duplicate_client_order_id")
        try:
            payload = self._client().submit_limit_order(
                context,
                order_request=order_request,
            )
        except Trading212ApiError as exc:
            raise BrokerAdapterError(str(exc)) from exc
        if isinstance(seen, set):
            seen.add(client_order_id)
        request_quantity = _to_float(order_request.get("quantity")) or 0.0
        return self._normalize_order_payload(
            payload,
            request=order_request,
            side="buy" if request_quantity > 0 else "sell",
        )

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        try:
            self._client().cancel_order(context, order_id=order_id)
        except Trading212ApiError as exc:
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
        symbol = str(proposal.get("symbol", "")).strip().upper()
        ticker = self.resolve_ticker(symbol)
        entry_price = _to_float(proposal.get("entry_price"))
        if ticker is None or not symbol:
            raise BrokerAdapterError("Trading 212 entry request requires a mapped ticker.")
        if entry_price is None or entry_price <= 0:
            raise BrokerAdapterError("Trading 212 entry request requires a valid entry price.")
        notional_native = _notional_in_primary_currency(
            notional_usd=notional_usd,
            primary_currency=self.primary_currency,
            usd_to_gbp=usd_to_gbp,
        )
        reference_price_native = _price_in_primary_currency(
            price_usd=entry_price,
            primary_currency=self.primary_currency,
            usd_to_gbp=usd_to_gbp,
        )
        qty = _format_quantity(notional_native / reference_price_native)
        if qty == "0":
            raise BrokerAdapterError("Trading 212 entry request requires a positive quantity.")
        limit_price = reference_price_native * (
            1.0 + (max(0.0, float(limit_buffer_bps or 0.0)) / 10_000.0)
        )
        return {
            "ticker": ticker,
            "quantity": qty,
            "limitPrice": round(limit_price, 4),
            "timeValidity": "DAY",
            "client_order_id": client_order_id,
            "centaur_symbol": symbol,
            "centaur_notional_usd": round(float(notional_usd), 2),
            "centaur_notional_native": round(float(notional_native), 2),
            "centaur_notional_currency": self.primary_currency,
            "centaur_execution_status": "approved_for_paper",
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
        ticker = self.resolve_ticker(symbol)
        formatted_qty = _format_quantity(qty)
        if ticker is None or not str(symbol).strip():
            raise BrokerAdapterError("Trading 212 exit request requires a mapped ticker.")
        if formatted_qty == "0":
            raise BrokerAdapterError("Trading 212 exit request requires a positive quantity.")
        if reference_price <= 0:
            raise BrokerAdapterError("Trading 212 exit request requires a valid reference price.")
        reference_price_native = _price_in_primary_currency(
            price_usd=float(reference_price),
            primary_currency=self.primary_currency,
            usd_to_gbp=usd_to_gbp,
        )
        limit_price = reference_price_native * (
            1.0 - (max(0.0, float(limit_buffer_bps or 0.0)) / 10_000.0)
        )
        return {
            "ticker": ticker,
            "quantity": f"-{formatted_qty}",
            "limitPrice": round(limit_price, 4),
            "timeValidity": "DAY",
            "client_order_id": client_order_id,
            "centaur_symbol": str(symbol).strip().upper(),
            "centaur_execution_status": "approved_for_paper",
        }

    def _normalize_order_payload(
        self,
        payload: dict[str, Any],
        *,
        request: dict[str, Any],
        side: str,
    ) -> dict[str, Any]:
        order_id = str(payload.get("id") or payload.get("orderId") or "").strip()
        ticker = str(payload.get("ticker") or request.get("ticker") or "").strip().upper()
        symbol = str(request.get("centaur_symbol") or ticker.split("_", 1)[0]).strip().upper()
        quantity = _to_float(payload.get("quantity"))
        if quantity is None:
            quantity = abs(_to_float(request.get("quantity")) or 0.0)
        filled_quantity = _to_float(payload.get("filledQuantity")) or 0.0
        limit_price = _to_float(payload.get("limitPrice"))
        if limit_price is None:
            limit_price = _to_float(request.get("limitPrice"))
        return {
            "id": order_id,
            "broker_id": self.broker_id,
            "symbol": symbol,
            "venue": "trading212",
            "venue_symbol": ticker,
            "side": side,
            "type": "limit",
            "time_in_force": str(payload.get("timeInForce") or request.get("timeValidity") or "DAY").lower(),
            "status": str(payload.get("status") or "submitted").lower(),
            "qty": abs(quantity),
            "filled_qty": abs(filled_quantity),
            "notional": request.get("centaur_notional_usd"),
            "notional_native": request.get("centaur_notional_native"),
            "notional_currency": request.get("centaur_notional_currency"),
            "filled_avg_price": payload.get("averagePrice"),
            "limit_price": limit_price,
            "client_order_id": str(request.get("client_order_id", "")),
            "submitted_at": payload.get("createdAt"),
            "updated_at": payload.get("updatedAt"),
            "raw_trading212_order": payload,
        }


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(payload.get(key))
        if value is not None:
            return value
    return None


def _notional_in_primary_currency(
    *,
    notional_usd: float,
    primary_currency: str,
    usd_to_gbp: float | None,
) -> float:
    if str(primary_currency).upper() == "GBP":
        rate = float(usd_to_gbp or 0.0)
        if rate <= 0:
            raise BrokerAdapterError("Trading 212 GBP paper orders require USD/GBP FX.")
        return float(notional_usd) * rate
    return float(notional_usd)


def _price_in_primary_currency(
    *,
    price_usd: float,
    primary_currency: str,
    usd_to_gbp: float | None,
) -> float:
    if str(primary_currency).upper() == "GBP":
        rate = float(usd_to_gbp or 0.0)
        if rate <= 0:
            raise BrokerAdapterError("Trading 212 GBP paper orders require USD/GBP FX.")
        return float(price_usd) * rate
    return float(price_usd)


def _format_quantity(value: float) -> str:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BrokerAdapterError("Trading 212 entry request requires a valid quantity.")
    if decimal_value <= 0:
        return "0"
    floored = decimal_value.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    if floored <= 0:
        return "0"
    return format(floored.normalize(), "f")


def _centaur_symbol_from_ticker(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if "_US_EQ" in normalized:
        return normalized.split("_US_EQ", 1)[0]
    if "_" in normalized:
        return normalized.split("_", 1)[0]
    return normalized
