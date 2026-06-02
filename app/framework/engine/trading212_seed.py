from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
import re
from typing import Any, Callable

from app.framework.adapters.trading212 import Trading212ApiError, Trading212PaperClient
from app.framework.reporting.trading212_instruments import (
    _load_instrument_cache,
    _match_configured_symbols,
    _save_instrument_cache,
)
from app.framework.runtime.models import TickContext
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

DEFAULT_SEED_QUANTITY = Decimal("0.01")
MAX_SEED_QUANTITY = Decimal("0.01")
MAX_BROKER_MINIMUM_SEED_QUANTITY = Decimal("1.0")


class Trading212PriceSeeder:
    """Create tiny Trading 212 paper holdings for API-backed price discovery.

    Trading 212's public API does not support value-based orders, so this
    operator tool places deliberately tiny quantity-based market buys in the
    demo account. The orders are audit-recorded as `price_seed_only`, and normal
    risk/exit code treats them as data seeds rather than managed strategy lots.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        ledger: UsageLedger | None = None,
        client_factory: Callable[[RuntimeConfig], Trading212PaperClient] | None = None,
        instrument_cache_path: Any = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.ledger = ledger or UsageLedger(config=self.config)
        self.client_factory = client_factory or Trading212PaperClient.from_config
        self.instrument_cache_path = instrument_cache_path

    def run(
        self,
        *,
        confirm: bool = False,
        quantity: str | float | Decimal = DEFAULT_SEED_QUANTITY,
        symbols: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now().astimezone()
        tick_id = f"trading212-price-seed-{started_at:%Y%m%d%H%M%S}"
        normalized_quantity = _normalize_seed_quantity(quantity)
        configured_symbols = _seed_symbols(self.config, symbols=symbols)
        result: dict[str, Any] = {
            "mode": "dry_run" if not confirm else "seed_orders",
            "broker_id": "trading212_paper",
            "tick_id": tick_id,
            "symbols_requested": len(configured_symbols),
            "quantity": str(normalized_quantity),
            "orders_submitted": 0,
            "orders_saved": 0,
            "skipped": [],
            "orders": [],
            "errors": [],
        }

        if not configured_symbols:
            result["mode"] = "skipped"
            result["reason"] = "trading212_seed_symbols_missing"
            return result
        if not getattr(self.config, "trading212_paper_api_configured", False):
            result["mode"] = "skipped"
            result["reason"] = "trading212_paper_credentials_missing"
            return result
        if not getattr(self.config, "trading212_paper_execution_enabled", False):
            result["mode"] = "skipped"
            result["reason"] = "trading212_paper_execution_disabled"
            return result
        if getattr(self.config, "trading212_live_execution_enabled", False):
            result["mode"] = "skipped"
            result["reason"] = "trading212_live_must_be_disabled_for_seed"
            return result

        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.ledger,
        )
        try:
            client = self.client_factory(self.config)
            positions = client.get_positions(context)
            open_orders = client.get_orders(context)
        except Trading212ApiError as exc:
            result["mode"] = "error"
            result["reason"] = str(exc)
            return result
        instruments = _load_instrument_cache(path=self.instrument_cache_path) if self.instrument_cache_path else _load_instrument_cache()
        overrides = dict(getattr(self.config, "trading212_paper_ticker_overrides", {}) or {})
        mapped = _match_configured_symbols(
            configured_symbols=configured_symbols,
            overrides=overrides,
            instruments=instruments,
        )
        mapped = _apply_configured_ticker_overrides(mapped=mapped, overrides=overrides)
        if _has_unmapped(mapped):
            try:
                instruments = client.get_instruments(context)
            except Trading212ApiError as exc:
                result["mode"] = "error"
                result["reason"] = str(exc)
                return result
            if self.instrument_cache_path:
                _save_instrument_cache(instruments, path=self.instrument_cache_path)
            else:
                _save_instrument_cache(instruments)
            mapped = _match_configured_symbols(
                configured_symbols=configured_symbols,
                overrides=overrides,
                instruments=instruments,
            )
            mapped = _apply_configured_ticker_overrides(mapped=mapped, overrides=overrides)

        ticker_symbol_map = {
            str(item.get("ticker", "")).strip().upper(): str(item.get("symbol", "")).strip().upper()
            for item in mapped
            if str(item.get("ticker", "")).strip() and str(item.get("symbol", "")).strip()
        }
        held_symbols = _held_symbols(positions, ticker_symbol_map=ticker_symbol_map)
        open_order_symbols = _open_order_symbols(open_orders, ticker_symbol_map=ticker_symbol_map)
        order_rows: list[dict[str, Any]] = []
        for item in mapped:
            symbol = str(item.get("symbol", "")).strip().upper()
            ticker = str(item.get("ticker", "")).strip()
            if not symbol:
                continue
            if item.get("status") != "mapped" or not ticker:
                result["skipped"].append(
                    {"symbol": symbol, "reason": "trading212_ticker_unmapped"}
                )
                continue
            if symbol in held_symbols:
                result["skipped"].append(
                    {"symbol": symbol, "ticker": ticker, "reason": "already_held"}
                )
                continue
            if symbol in open_order_symbols:
                result["skipped"].append(
                    {"symbol": symbol, "ticker": ticker, "reason": "order_already_open"}
                )
                continue

            client_order_id = _seed_client_order_id(tick_id=tick_id, symbol=symbol)
            order_request = {
                "ticker": ticker,
                "quantity": str(normalized_quantity),
                "extendedHours": False,
                "client_order_id": client_order_id,
                "centaur_symbol": symbol,
                "centaur_execution_status": "price_seed_only",
            }
            if not confirm:
                result["orders"].append(
                    {
                        "symbol": symbol,
                        "ticker": ticker,
                        "quantity": str(normalized_quantity),
                        "status": "would_submit",
                    }
                )
                continue

            try:
                payload = client.submit_market_order(
                    context,
                    order_request=order_request,
                )
            except Trading212ApiError as exc:
                retry_quantity = _minimum_quantity_from_error(str(exc))
                if (
                    retry_quantity is not None
                    and retry_quantity > normalized_quantity
                    and retry_quantity <= MAX_BROKER_MINIMUM_SEED_QUANTITY
                ):
                    retry_request = {
                        **order_request,
                        "quantity": str(retry_quantity),
                        "client_order_id": f"{client_order_id}-r1"[:48],
                    }
                    try:
                        payload = client.submit_market_order(
                            context,
                            order_request=retry_request,
                        )
                    except Trading212ApiError as retry_exc:
                        result["errors"].append(
                            {"symbol": symbol, "ticker": ticker, "error": str(retry_exc)}
                        )
                        continue
                    order = _normalize_seed_order(
                        payload=payload,
                        request=retry_request,
                        submitted_at=started_at,
                    )
                    result["orders"].append(order)
                    order_rows.append(order)
                    continue
                result["errors"].append(
                    {"symbol": symbol, "ticker": ticker, "error": str(exc)}
                )
                continue
            order = _normalize_seed_order(
                payload=payload,
                request=order_request,
                submitted_at=started_at,
            )
            result["orders"].append(order)
            order_rows.append(order)

        if order_rows:
            result["orders_saved"] = self.ledger.record_paper_trade_orders(
                tick_id=tick_id,
                captured_at=started_at,
                orders=order_rows,
                broker_id="trading212_paper",
            )
        result["orders_submitted"] = len(order_rows)
        if not confirm:
            result["reason"] = "confirmation_required"
        elif result["errors"]:
            result["reason"] = "seed_orders_partially_failed"
        elif result["orders_submitted"] == 0:
            result["reason"] = "no_seed_orders_needed"
        else:
            result["reason"] = "seed_orders_submitted"
        return result

    def render(self, *, result: dict[str, Any]) -> str:
        lines = ["Trading 212 Price Seeder"]
        lines.append(
            (
                f"mode={result.get('mode', 'unknown')} | "
                f"broker={result.get('broker_id', '-')} | "
                f"quantity={result.get('quantity', '-')}"
            )
        )
        lines.append(
            (
                f"symbols_requested={result.get('symbols_requested', 0)} | "
                f"orders_submitted={result.get('orders_submitted', 0)} | "
                f"orders_saved={result.get('orders_saved', 0)} | "
                f"reason={result.get('reason', '-')}"
            )
        )
        orders = result.get("orders", [])
        if orders:
            lines.append("Orders:")
            for order in orders:
                lines.append(
                    (
                        f"- {order.get('symbol', '-')}"
                        f" -> {order.get('venue_symbol') or order.get('ticker', '-')}"
                        f" | qty={order.get('qty') or order.get('quantity', '-')}"
                        f" | status={order.get('status', '-')}"
                    )
                )
        skipped = result.get("skipped", [])
        if skipped:
            lines.append("Skipped:")
            for item in skipped:
                lines.append(
                    (
                        f"- {item.get('symbol', '-')}"
                        f" | ticker={item.get('ticker', '-')}"
                        f" | reason={item.get('reason', '-')}"
                    )
                )
        errors = result.get("errors", [])
        if errors:
            lines.append("Errors:")
            for item in errors:
                lines.append(
                    (
                        f"- {item.get('symbol', '-')}"
                        f" | ticker={item.get('ticker', '-')}"
                        f" | error={item.get('error', '-')}"
                    )
                )
        return "\n".join(lines)


def _seed_symbols(config: RuntimeConfig, *, symbols: tuple[str, ...] | None) -> list[str]:
    configured = symbols
    if configured is None:
        configured = getattr(config, "trading212_paper_price_seed_symbols", tuple())
    if not configured:
        configured = getattr(config, "trading212_paper_equity_symbols", tuple())
    return [str(symbol).strip().upper() for symbol in configured or () if str(symbol).strip()]


def _has_unmapped(mapped: list[dict[str, Any]]) -> bool:
    return any(str(item.get("status", "")) != "mapped" for item in mapped)


def _apply_configured_ticker_overrides(
    *,
    mapped: list[dict[str, Any]],
    overrides: dict[str, str],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for item in mapped:
        symbol = str(item.get("symbol", "")).strip().upper()
        override = str(overrides.get(symbol, "")).strip()
        if item.get("status") == "mapped" or not symbol or not override:
            resolved.append(item)
            continue
        resolved.append(
            {
                "symbol": symbol,
                "status": "mapped",
                "ticker": override,
                "name": "-",
                "currency": "-",
                "exchange": "-",
                "mapping_source": "ticker_override",
            }
        )
    return resolved


def _normalize_seed_quantity(value: str | float | Decimal) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Trading 212 seed quantity must be numeric.") from exc
    if decimal_value <= 0:
        raise ValueError("Trading 212 seed quantity must be positive.")
    if decimal_value > MAX_SEED_QUANTITY:
        raise ValueError(f"Trading 212 seed quantity is capped at {MAX_SEED_QUANTITY}.")
    return decimal_value.quantize(Decimal("0.000001"), rounding=ROUND_DOWN).normalize()


def _minimum_quantity_from_error(message: str) -> Decimal | None:
    match = re.search(r"must trade at least\s+([0-9]+(?:\.[0-9]+)?)", message)
    if match is None:
        return None
    return _normalize_broker_minimum_quantity(match.group(1))


def _normalize_broker_minimum_quantity(value: str) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if decimal_value <= 0:
        return None
    return decimal_value.quantize(Decimal("0.01"), rounding=ROUND_UP).normalize()


def _held_symbols(
    positions: list[dict[str, Any]],
    *,
    ticker_symbol_map: dict[str, str] | None = None,
) -> set[str]:
    ticker_symbol_map = ticker_symbol_map or {}
    held: set[str] = set()
    for position in positions:
        if not isinstance(position, dict):
            continue
        quantity = _to_decimal(position.get("quantity"))
        if quantity is not None and quantity <= 0:
            continue
        ticker = str(position.get("ticker") or position.get("venue_symbol") or "").strip()
        instrument = position.get("instrument")
        if isinstance(instrument, dict) and not ticker:
            ticker = str(instrument.get("ticker") or "").strip()
        symbol = ticker_symbol_map.get(ticker.upper()) or _symbol_from_trading212_ticker(
            ticker or str(position.get("symbol", ""))
        )
        if symbol:
            held.add(symbol)
    return held


def _open_order_symbols(
    orders: list[dict[str, Any]],
    *,
    ticker_symbol_map: dict[str, str] | None = None,
) -> set[str]:
    ticker_symbol_map = ticker_symbol_map or {}
    open_symbols: set[str] = set()
    closed_statuses = {"filled", "cancelled", "canceled", "rejected", "expired"}
    for order in orders:
        if not isinstance(order, dict):
            continue
        status = str(order.get("status") or "").strip().lower()
        if status in closed_statuses:
            continue
        ticker = str(order.get("ticker") or order.get("venue_symbol") or "").strip()
        symbol = ticker_symbol_map.get(ticker.upper()) or _symbol_from_trading212_ticker(
            ticker or str(order.get("symbol", ""))
        )
        if symbol:
            open_symbols.add(symbol)
    return open_symbols


def _normalize_seed_order(
    *,
    payload: dict[str, Any],
    request: dict[str, Any],
    submitted_at: datetime,
) -> dict[str, Any]:
    ticker = str(payload.get("ticker") or request.get("ticker") or "").strip()
    symbol = str(request.get("centaur_symbol") or _symbol_from_trading212_ticker(ticker)).upper()
    quantity = _to_decimal(payload.get("quantity"))
    if quantity is None:
        quantity = _to_decimal(request.get("quantity")) or Decimal("0")
    filled_quantity = _to_decimal(payload.get("filledQuantity")) or Decimal("0")
    order_id = str(payload.get("id") or payload.get("orderId") or "").strip()
    return {
        "id": order_id,
        "broker_id": "trading212_paper",
        "symbol": symbol,
        "venue": "trading212",
        "venue_symbol": ticker,
        "side": "buy",
        "type": "market",
        "time_in_force": str(payload.get("timeInForce") or "day").lower(),
        "status": str(payload.get("status") or "submitted").lower(),
        "qty": abs(float(quantity)),
        "filled_qty": abs(float(filled_quantity)),
        "notional": None,
        "notional_native": payload.get("filledValue") or payload.get("value"),
        "notional_currency": payload.get("currency") or "GBP",
        "filled_avg_price": payload.get("averagePrice"),
        "client_order_id": str(request.get("client_order_id") or ""),
        "submitted_at": payload.get("createdAt") or submitted_at.isoformat(),
        "updated_at": payload.get("updatedAt"),
        "raw_trading212_order": payload,
        "raw_json": {
            "centaur_execution_status": "price_seed_only",
            "price_seed_only": True,
        },
    }


def _seed_client_order_id(*, tick_id: str, symbol: str) -> str:
    suffix = "".join(ch.lower() for ch in symbol if ch.isalnum())[:8]
    return f"centaur-seed-{tick_id[-6:]}-{suffix}"[:48]


def _symbol_from_trading212_ticker(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    prefix = normalized.split("_", 1)[0]
    if prefix.lower().endswith("l") and len(prefix) > 1:
        prefix = prefix[:-1]
    return prefix.upper()


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
