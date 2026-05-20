from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib import error, request
from urllib.parse import urlencode

from .config import RuntimeConfig
from .models import TickContext


class AlpacaApiError(RuntimeError):
    """Raised when the Alpaca Trading API returns an error."""


class AlpacaPaperClient:
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str,
        data_base_url: str,
        timeout_seconds: int,
        usage_source: str = "alpaca_paper",
    ) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = _normalize_base_url(base_url)
        self.data_base_url = _normalize_base_url(data_base_url)
        self.timeout_seconds = timeout_seconds
        self.usage_source = usage_source

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "AlpacaPaperClient":
        if not config.alpaca_api_configured:
            raise AlpacaApiError("Alpaca API credentials are not configured.")

        return cls(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            base_url=config.alpaca_base_url,
            data_base_url=config.alpaca_data_base_url,
            timeout_seconds=config.alpaca_request_timeout_seconds,
            usage_source="alpaca_paper",
        )

    @classmethod
    def from_live_config(cls, config: RuntimeConfig) -> "AlpacaPaperClient":
        if not config.alpaca_live_api_configured:
            raise AlpacaApiError("Alpaca Live API credentials are not configured.")

        return cls(
            api_key=config.alpaca_live_api_key,
            secret_key=config.alpaca_live_secret_key,
            base_url=config.alpaca_live_base_url,
            data_base_url=config.alpaca_data_base_url,
            timeout_seconds=config.alpaca_request_timeout_seconds,
            usage_source="alpaca_live",
        )

    def get_account(self, context: TickContext) -> dict[str, Any]:
        return self._request_json(context=context, path="/v2/account")

    def get_clock(self, context: TickContext) -> dict[str, Any]:
        return self._request_json(context=context, path="/v2/clock")

    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        payload = self._request_json(context=context, path="/v2/positions")
        if isinstance(payload, list):
            return payload
        raise AlpacaApiError("Unexpected Alpaca positions response payload.")

    def get_orders(
        self,
        context: TickContext,
        *,
        status: str = "all",
        after: datetime | None = None,
        limit: int = 100,
        nested: bool = True,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        query_params: dict[str, Any] = {
            "status": status,
            "limit": limit,
            "direction": direction,
            "nested": "true" if nested else "false",
        }
        if after is not None:
            query_params["after"] = _format_api_datetime(after)
        payload = self._request_json(
            context=context,
            path=f"/v2/orders?{urlencode(query_params)}",
        )
        if isinstance(payload, list):
            return _flatten_orders(payload)
        raise AlpacaApiError("Unexpected Alpaca orders response payload.")

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._request_json(
            context=context,
            path="/v2/orders",
            method="POST",
            body_json=order_request,
        )
        if isinstance(payload, dict):
            return payload
        raise AlpacaApiError("Unexpected Alpaca order submission response payload.")

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        self._request_json(
            context=context,
            path=f"/v2/orders/{order_id}",
            method="DELETE",
        )

    def get_latest_bars(
        self,
        context: TickContext,
        *,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        query = urlencode({"symbols": ",".join(symbols)})
        payload = self._request_json(
            context=context,
            path=f"/v2/stocks/bars/latest?{query}",
            base_url=self.data_base_url,
            usage_source="alpaca_market_data",
        )
        if isinstance(payload, dict) and isinstance(payload.get("bars"), dict):
            return payload["bars"]
        raise AlpacaApiError("Unexpected Alpaca latest bars response payload.")

    def get_latest_crypto_bars(
        self,
        context: TickContext,
        *,
        location: str,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        query = urlencode({"symbols": ",".join(symbols)})
        payload = self._request_json(
            context=context,
            path=f"/v1beta3/crypto/{location}/latest/bars?{query}",
            base_url=self.data_base_url,
            usage_source="alpaca_crypto_data",
        )
        if isinstance(payload, dict) and isinstance(payload.get("bars"), dict):
            return payload["bars"]
        raise AlpacaApiError("Unexpected Alpaca latest crypto bars response payload.")

    def get_historical_stock_bars(
        self,
        context: TickContext,
        *,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
        feed: str = "",
        limit: int = 10_000,
    ) -> dict[str, list[dict[str, Any]]]:
        query_params: dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": _format_api_datetime(start),
            "end": _format_api_datetime(end),
            "limit": limit,
        }
        if feed:
            query_params["feed"] = feed
        return self._collect_paginated_bars(
            context=context,
            path="/v2/stocks/bars",
            query_params=query_params,
            usage_source="alpaca_market_data",
            error_message="Unexpected Alpaca historical stock bars response payload.",
        )

    def get_historical_crypto_bars(
        self,
        context: TickContext,
        *,
        location: str,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int = 10_000,
    ) -> dict[str, list[dict[str, Any]]]:
        return self._collect_paginated_bars(
            context=context,
            path=f"/v1beta3/crypto/{location}/bars",
            query_params={
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": _format_api_datetime(start),
                "end": _format_api_datetime(end),
                "limit": limit,
            },
            usage_source="alpaca_crypto_data",
            error_message="Unexpected Alpaca historical crypto bars response payload.",
        )

    def _request_json(
        self,
        *,
        context: TickContext,
        path: str,
        base_url: str | None = None,
        usage_source: str | None = None,
        method: str = "GET",
        body_json: dict[str, Any] | None = None,
    ) -> Any:
        usage_source = usage_source or self.usage_source
        url = f"{base_url or self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "User-Agent": "ghostfrog-centaur/0.1",
        }
        body = None
        if body_json is not None:
            body = json.dumps(body_json).encode("utf-8")
            headers["Content-Type"] = "application/json"
        http_request = request.Request(url=url, headers=headers, data=body, method=method)
        requested_at = datetime.now().astimezone()

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                status_code = getattr(response, "status", 200)

            payload = json.loads(response_body) if response_body else None
            context.record_api_usage(
                source=usage_source,
                endpoint=path,
                success=True,
                metadata={
                    "method": method,
                    "status_code": status_code,
                    "requested_at": requested_at.isoformat(),
                },
            )
            return payload
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            context.record_api_usage(
                source=usage_source,
                endpoint=path,
                success=False,
                metadata={
                    "method": method,
                    "status_code": exc.code,
                    "requested_at": requested_at.isoformat(),
                    "error": _truncate(body, 240),
                },
            )
            raise AlpacaApiError(
                f"Alpaca request failed for {path} with status {exc.code}: {_truncate(body, 240)}"
            ) from exc
        except error.URLError as exc:
            context.record_api_usage(
                source=usage_source,
                endpoint=path,
                success=False,
                metadata={
                    "method": method,
                    "requested_at": requested_at.isoformat(),
                    "error": str(exc.reason),
                },
            )
            raise AlpacaApiError(
                f"Alpaca request failed for {path}: {exc.reason}"
            ) from exc

    def _collect_paginated_bars(
        self,
        *,
        context: TickContext,
        path: str,
        query_params: dict[str, Any],
        usage_source: str,
        error_message: str,
    ) -> dict[str, list[dict[str, Any]]]:
        aggregated: dict[str, list[dict[str, Any]]] = {}
        next_page_token: str | None = None

        while True:
            page_params = dict(query_params)
            if next_page_token:
                page_params["page_token"] = next_page_token

            payload = self._request_json(
                context=context,
                path=f"{path}?{urlencode(page_params)}",
                base_url=self.data_base_url,
                usage_source=usage_source,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
                raise AlpacaApiError(error_message)

            for symbol, bars in payload["bars"].items():
                if not isinstance(symbol, str) or not isinstance(bars, list):
                    raise AlpacaApiError(error_message)
                aggregated.setdefault(symbol, []).extend(
                    [bar for bar in bars if isinstance(bar, dict)]
                )

            next_page_token = payload.get("next_page_token")
            if not next_page_token:
                break

        return aggregated


def get_alpaca_client(context: TickContext) -> AlpacaPaperClient:
    cached = context.metadata.get("alpaca_client")
    if isinstance(cached, AlpacaPaperClient):
        return cached

    client = AlpacaPaperClient.from_config(context.config)
    context.metadata["alpaca_client"] = client
    return client


def get_alpaca_live_client(context: TickContext) -> AlpacaPaperClient:
    cached = context.metadata.get("alpaca_live_client")
    if isinstance(cached, AlpacaPaperClient):
        return cached

    client = AlpacaPaperClient.from_live_config(context.config)
    context.metadata["alpaca_live_client"] = client
    return client


def summarize_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": account.get("status", "unknown"),
        "currency": account.get("currency", "USD"),
        "equity": _parse_decimal(account.get("equity")),
        "cash": _parse_decimal(account.get("cash")),
        "buying_power": _parse_decimal(account.get("buying_power")),
        "portfolio_value": _parse_decimal(account.get("portfolio_value")),
        "trading_blocked": _parse_bool(account.get("trading_blocked")),
        "account_blocked": _parse_bool(account.get("account_blocked")),
        "trade_suspended_by_user": _parse_bool(account.get("trade_suspended_by_user")),
        "shorting_enabled": _parse_bool(account.get("shorting_enabled")),
    }


def summarize_clock(clock: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_open": _parse_bool(clock.get("is_open")),
        "timestamp": clock.get("timestamp"),
        "next_open": clock.get("next_open"),
        "next_close": clock.get("next_close"),
    }


def summarize_positions(positions: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = [item.get("symbol", "?") for item in positions]
    market_values = [
        _parse_decimal(item.get("market_value"), default=0.0) for item in positions
    ]
    total_market_value = round(sum(market_values), 2)
    return {
        "open_positions": len(positions),
        "symbols": symbols,
        "total_market_value": total_market_value,
    }


def summarize_orders(orders: list[dict[str, Any]]) -> dict[str, Any]:
    open_statuses = {
        "new",
        "accepted",
        "pending_new",
        "accepted_for_bidding",
        "partially_filled",
        "held",
        "pending_replace",
        "pending_cancel",
    }
    open_orders = [
        order
        for order in orders
        if str(order.get("status", "")).lower() in open_statuses
    ]
    filled_orders = [
        order for order in orders if str(order.get("status", "")).lower() == "filled"
    ]
    canceled_orders = [
        order
        for order in orders
        if str(order.get("status", "")).lower() in {"canceled", "expired", "rejected"}
    ]
    symbols = sorted(
        {str(order.get("symbol", "")).upper() for order in orders if order.get("symbol")}
    )
    open_symbols = sorted(
        {
            str(order.get("symbol", "")).upper()
            for order in open_orders
            if order.get("symbol")
        }
    )
    return {
        "orders_loaded": len(orders),
        "open_orders": len(open_orders),
        "filled_orders": len(filled_orders),
        "canceled_orders": len(canceled_orders),
        "symbols": symbols,
        "open_order_symbols": open_symbols,
    }


def summarize_latest_bars(bars: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbols = sorted(bars.keys())
    return {
        "bars_received": len(symbols),
        "symbols": symbols,
    }


def _parse_decimal(value: Any, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default

    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return default


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _flatten_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def visit(order: dict[str, Any]) -> None:
        order_id = str(order.get("id", "")).strip()
        if order_id and order_id in seen_ids:
            return
        if order_id:
            seen_ids.add(order_id)
        flattened.append(order)
        legs = order.get("legs", [])
        if isinstance(legs, list):
            for leg in legs:
                if isinstance(leg, dict):
                    visit(leg)

    for order in orders:
        if isinstance(order, dict):
            visit(order)

    return flattened


def _normalize_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    if normalized.endswith("/v2"):
        return normalized[:-3]
    return normalized


def _format_api_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
