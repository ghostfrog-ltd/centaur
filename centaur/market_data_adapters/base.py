"""Compatibility wrapper for market-data adapter base types."""

from app.adapters.market_data.base import (
    MarketDataAdapter,
    MarketDataAdapterError,
    UnsupportedMarketDataAdapterError,
)

__all__ = [
    "MarketDataAdapter",
    "MarketDataAdapterError",
    "UnsupportedMarketDataAdapterError",
]

