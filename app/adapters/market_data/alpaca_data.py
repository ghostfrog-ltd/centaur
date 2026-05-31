from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.instruments import InstrumentRegistry, default_instrument_registry

from .base import MarketDataAdapter, MarketDataAdapterError

if TYPE_CHECKING:
    from centaur.models import TickContext


def get_alpaca_client(context: "TickContext"):
    from centaur.alpaca import get_alpaca_client as _get_alpaca_client

    return _get_alpaca_client(context)


class AlpacaMarketDataAdapter(MarketDataAdapter):
    """Alpaca market-data adapter for current paper/live shared data feeds."""

    provider_id = "alpaca"

    def __init__(self, *, instrument_registry: InstrumentRegistry | None = None) -> None:
        self.instrument_registry = instrument_registry or default_instrument_registry()

    def get_latest_equity_bars(
        self,
        context: TickContext,
        *,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        from centaur.alpaca import AlpacaApiError

        try:
            bars = get_alpaca_client(context).get_latest_bars(context, symbols=symbols)
            return self._with_instrument_metadata(bars, asset_class="equity")
        except AlpacaApiError as exc:
            raise MarketDataAdapterError(str(exc)) from exc

    def get_latest_crypto_bars(
        self,
        context: TickContext,
        *,
        location: str,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        from centaur.alpaca import AlpacaApiError

        try:
            bars = get_alpaca_client(context).get_latest_crypto_bars(
                context,
                location=location,
                symbols=symbols,
            )
            return self._with_instrument_metadata(bars, asset_class="crypto")
        except AlpacaApiError as exc:
            raise MarketDataAdapterError(str(exc)) from exc

    def get_historical_equity_bars(
        self,
        context: TickContext,
        *,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
        feed: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        from centaur.alpaca import AlpacaApiError

        try:
            bars = get_alpaca_client(context).get_historical_stock_bars(
                context,
                symbols=symbols,
                timeframe=timeframe,
                start=start,
                end=end,
                feed=feed,
            )
            return self._with_historical_instrument_metadata(
                bars,
                asset_class="equity",
            )
        except AlpacaApiError as exc:
            raise MarketDataAdapterError(str(exc)) from exc

    def get_historical_crypto_bars(
        self,
        context: TickContext,
        *,
        location: str,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        from centaur.alpaca import AlpacaApiError

        try:
            bars = get_alpaca_client(context).get_historical_crypto_bars(
                context,
                location=location,
                symbols=symbols,
                timeframe=timeframe,
                start=start,
                end=end,
            )
            return self._with_historical_instrument_metadata(
                bars,
                asset_class="crypto",
            )
        except AlpacaApiError as exc:
            raise MarketDataAdapterError(str(exc)) from exc

    def _with_instrument_metadata(
        self,
        bars_by_symbol: dict[str, dict[str, Any]],
        *,
        asset_class: str,
    ) -> dict[str, dict[str, Any]]:
        enriched: dict[str, dict[str, Any]] = {}
        for symbol, bar in bars_by_symbol.items():
            if not isinstance(bar, dict):
                continue
            enriched[symbol] = {
                **bar,
                "asset_class": asset_class,
                **self._instrument_metadata(symbol=symbol, asset_class=asset_class),
            }
        return enriched

    def _with_historical_instrument_metadata(
        self,
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        *,
        asset_class: str,
    ) -> dict[str, list[dict[str, Any]]]:
        enriched: dict[str, list[dict[str, Any]]] = {}
        for symbol, bars in bars_by_symbol.items():
            metadata = self._instrument_metadata(symbol=symbol, asset_class=asset_class)
            enriched[symbol] = [
                {
                    **bar,
                    "asset_class": asset_class,
                    **metadata,
                }
                for bar in bars
                if isinstance(bar, dict)
            ]
        return enriched

    def _instrument_metadata(self, *, symbol: str, asset_class: str) -> dict[str, str]:
        ref = self.instrument_registry.reference_for(
            venue="alpaca",
            venue_symbol=str(symbol or ""),
            asset_class=asset_class,
        )
        metadata = ref.as_metadata()
        if not metadata["canonical_instrument_id"]:
            metadata["canonical_instrument_id"] = _fallback_canonical_instrument_id(
                symbol=symbol,
                asset_class=asset_class,
            )
        return metadata


def _fallback_canonical_instrument_id(*, symbol: str, asset_class: str) -> str:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        return ""
    if asset_class == "crypto":
        if "/" in normalized_symbol:
            base, quote = normalized_symbol.split("/", 1)
            return f"{base}-{quote}-SPOT"
        if normalized_symbol.endswith("USD"):
            return f"{normalized_symbol[:-3]}-USD-SPOT"
        return f"{normalized_symbol}-SPOT"
    return f"{normalized_symbol}-US-EQUITY"
