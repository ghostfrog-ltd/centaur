from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.framework.runtime.models import TickContext


class MarketDataAdapterError(RuntimeError):
    """Raised when a market-data adapter cannot fetch or normalize data."""


class UnsupportedMarketDataAdapterError(MarketDataAdapterError):
    """Raised when Centaur is asked for an unknown market-data provider."""


class MarketDataAdapter(ABC):
    """Market-data boundary for vendor-specific bar fetches.

    Strategy and discovery code should consume Centaur bar payloads rather than
    calling vendor clients directly. Adapters keep the current provider-specific
    transport and symbol quirks behind one small interface.
    """

    provider_id = "unknown"

    @abstractmethod
    def get_latest_equity_bars(
        self,
        context: TickContext,
        *,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_crypto_bars(
        self,
        context: TickContext,
        *,
        location: str,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
