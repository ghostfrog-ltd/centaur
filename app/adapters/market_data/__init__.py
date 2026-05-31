from __future__ import annotations

from .alpaca_data import AlpacaMarketDataAdapter
from .base import MarketDataAdapter, MarketDataAdapterError, UnsupportedMarketDataAdapterError


def get_market_data_adapter(context, provider_id: str) -> MarketDataAdapter:
    normalized = str(provider_id or "").strip().lower()
    if normalized in {"alpaca", "alpaca_market_data", "alpaca_crypto_data"}:
        return AlpacaMarketDataAdapter()
    raise UnsupportedMarketDataAdapterError(f"Unsupported market-data provider: {provider_id}")


__all__ = [
    "AlpacaMarketDataAdapter",
    "MarketDataAdapter",
    "MarketDataAdapterError",
    "UnsupportedMarketDataAdapterError",
    "get_market_data_adapter",
]
