from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.adapters.market_data import (
    MarketDataAdapterError,
    UnsupportedMarketDataAdapterError,
    get_market_data_adapter,
)
from app.adapters.market_data.alpaca_data import AlpacaMarketDataAdapter
from centaur.models import TickContext


class MarketDataAdapterTests(unittest.TestCase):
    def _context(self) -> TickContext:
        return TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(),
            usage_ledger=SimpleNamespace(),
        )

    def test_registry_returns_alpaca_market_data_adapter(self) -> None:
        adapter = get_market_data_adapter(self._context(), "alpaca_market_data")

        self.assertIsInstance(adapter, AlpacaMarketDataAdapter)

    def test_registry_rejects_unknown_provider(self) -> None:
        with self.assertRaises(UnsupportedMarketDataAdapterError):
            get_market_data_adapter(self._context(), "unknown_provider")

    def test_alpaca_adapter_wraps_latest_equity_bars(self) -> None:
        from app.adapters.market_data import alpaca_data as alpaca_adapter_module

        class FakeClient:
            def get_latest_bars(self, context, *, symbols):
                return {symbols[0]: {"c": 100.0}}

        original = alpaca_adapter_module.get_alpaca_client
        alpaca_adapter_module.get_alpaca_client = lambda _context: FakeClient()
        try:
            rows = AlpacaMarketDataAdapter().get_latest_equity_bars(
                self._context(),
                symbols=["AAPL"],
            )
        finally:
            alpaca_adapter_module.get_alpaca_client = original

        self.assertEqual(rows["AAPL"]["c"], 100.0)
        self.assertEqual(rows["AAPL"]["asset_class"], "equity")
        self.assertEqual(rows["AAPL"]["canonical_instrument_id"], "AAPL-US-EQUITY")
        self.assertEqual(rows["AAPL"]["venue"], "alpaca")
        self.assertEqual(rows["AAPL"]["venue_symbol"], "AAPL")

    def test_alpaca_adapter_wraps_historical_equity_bars(self) -> None:
        from app.adapters.market_data import alpaca_data as alpaca_adapter_module

        class FakeClient:
            def get_historical_stock_bars(
                self,
                context,
                *,
                symbols,
                timeframe,
                start,
                end,
                feed="",
            ):
                return {symbols[0]: [{"c": 100.0, "t": start.isoformat()}]}

        original = alpaca_adapter_module.get_alpaca_client
        alpaca_adapter_module.get_alpaca_client = lambda _context: FakeClient()
        try:
            now = datetime.now().astimezone()
            rows = AlpacaMarketDataAdapter().get_historical_equity_bars(
                self._context(),
                symbols=["AAPL"],
                timeframe="1Min",
                start=now,
                end=now,
                feed="iex",
            )
        finally:
            alpaca_adapter_module.get_alpaca_client = original

        self.assertEqual(rows["AAPL"][0]["c"], 100.0)
        self.assertEqual(rows["AAPL"][0]["asset_class"], "equity")
        self.assertEqual(rows["AAPL"][0]["canonical_instrument_id"], "AAPL-US-EQUITY")

    def test_alpaca_adapter_wraps_historical_crypto_bars(self) -> None:
        from app.adapters.market_data import alpaca_data as alpaca_adapter_module

        class FakeClient:
            def get_historical_crypto_bars(
                self,
                context,
                *,
                location,
                symbols,
                timeframe,
                start,
                end,
            ):
                return {symbols[0]: [{"c": 100.0, "location": location}]}

        original = alpaca_adapter_module.get_alpaca_client
        alpaca_adapter_module.get_alpaca_client = lambda _context: FakeClient()
        try:
            now = datetime.now().astimezone()
            rows = AlpacaMarketDataAdapter().get_historical_crypto_bars(
                self._context(),
                location="us",
                symbols=["BTC/USD"],
                timeframe="1Min",
                start=now,
                end=now,
            )
        finally:
            alpaca_adapter_module.get_alpaca_client = original

        self.assertEqual(rows["BTC/USD"][0]["location"], "us")
        self.assertEqual(rows["BTC/USD"][0]["asset_class"], "crypto")
        self.assertEqual(
            rows["BTC/USD"][0]["canonical_instrument_id"],
            "BTC-USD-SPOT",
        )
        self.assertEqual(rows["BTC/USD"][0]["venue"], "alpaca")
        self.assertEqual(rows["BTC/USD"][0]["venue_symbol"], "BTC/USD")

    def test_alpaca_adapter_wraps_vendor_errors(self) -> None:
        from centaur.alpaca import AlpacaApiError
        from app.adapters.market_data import alpaca_data as alpaca_adapter_module

        class FakeClient:
            def get_latest_bars(self, context, *, symbols):
                raise AlpacaApiError("boom")

        original = alpaca_adapter_module.get_alpaca_client
        alpaca_adapter_module.get_alpaca_client = lambda _context: FakeClient()
        try:
            with self.assertRaises(MarketDataAdapterError):
                AlpacaMarketDataAdapter().get_latest_equity_bars(
                    self._context(),
                    symbols=["AAPL"],
                )
        finally:
            alpaca_adapter_module.get_alpaca_client = original


if __name__ == "__main__":
    unittest.main()
