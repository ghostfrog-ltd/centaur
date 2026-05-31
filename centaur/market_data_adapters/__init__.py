"""Compatibility wrapper for market-data adapters.

Implementation ownership has moved to `app.adapters.market_data`.
"""

from app.adapters.market_data import (
    AlpacaMarketDataAdapter,
    MarketDataAdapter,
    MarketDataAdapterError,
    UnsupportedMarketDataAdapterError,
    get_market_data_adapter,
)

__all__ = [
    "AlpacaMarketDataAdapter",
    "MarketDataAdapter",
    "MarketDataAdapterError",
    "UnsupportedMarketDataAdapterError",
    "get_market_data_adapter",
]

