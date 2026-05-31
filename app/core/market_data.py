"""Shared market-data payload types for strategy-facing code."""

from typing import Any

MarketBar = dict[str, Any]
MarketSnapshot = dict[str, MarketBar]

__all__ = ["MarketBar", "MarketSnapshot"]

