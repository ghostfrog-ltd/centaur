from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.reporting.historical_bars_status import HistoricalBarsStatusReport


class _HistoricalBarsLedger:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def summarize_historical_bars(self, *, as_of: datetime | None = None) -> dict[str, object]:
        distinct_symbols = sorted({str(row.get("symbol", "")) for row in self.rows})
        rows_by_source: dict[str, int] = {}
        rows_by_timeframe: dict[str, int] = {}
        for row in self.rows:
            rows_by_source[str(row.get("source", ""))] = (
                rows_by_source.get(str(row.get("source", "")), 0) + 1
            )
            rows_by_timeframe[str(row.get("timeframe", ""))] = (
                rows_by_timeframe.get(str(row.get("timeframe", "")), 0) + 1
            )
        ordered = sorted(self.rows, key=lambda row: row["bar_timestamp"])
        return {
            "backend": "sqlite",
            "backend_detail": "test",
            "as_of": as_of,
            "historical": {
                "total_rows": len(self.rows),
                "rows_by_source": [
                    {"source": key, "rows": value}
                    for key, value in sorted(rows_by_source.items())
                ],
                "rows_by_timeframe": [
                    {"timeframe": key, "rows": value}
                    for key, value in sorted(rows_by_timeframe.items())
                ],
                "min_bar_timestamp": ordered[0]["bar_timestamp"] if ordered else None,
                "max_bar_timestamp": ordered[-1]["bar_timestamp"] if ordered else None,
                "last_1_day_rows": len(self.rows),
                "last_5_day_rows": len(self.rows),
                "distinct_symbols": len(distinct_symbols),
                "symbol_rows": [
                    {"symbol": symbol, "rows": 1, "last_bar_timestamp": ordered[-1]["bar_timestamp"]}
                    for symbol in distinct_symbols
                ],
                "newest_bar_age_seconds": 0.0,
            },
            "latest": {
                "total_rows": 3,
                "rows_by_source": [
                    {"source": "alpaca_crypto_data", "rows": 3},
                ],
                "min_bar_timestamp": ordered[0]["bar_timestamp"] if ordered else None,
                "max_bar_timestamp": ordered[-1]["bar_timestamp"] if ordered else None,
            },
        }

    def list_historical_bars(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, object]]:
        filtered = []
        for row in self.rows:
            if str(row.get("timeframe", "")) != timeframe:
                continue
            if str(row.get("source", "")) not in sources:
                continue
            if start_at is not None and row["bar_timestamp"] < start_at:
                continue
            if end_at is not None and row["bar_timestamp"] > end_at:
                continue
            if symbols and str(row.get("symbol", "")) not in symbols:
                continue
            filtered.append(dict(row))
        return filtered


class HistoricalBarsStatusReportTests(unittest.TestCase):
    def test_report_explains_timeframe_mismatch(self) -> None:
        tz = ZoneInfo("UTC")
        ledger = _HistoricalBarsLedger(
            [
                self._bar(datetime(2026, 6, 5, 12, 0, tzinfo=tz), "15Min"),
                self._bar(datetime(2026, 6, 5, 12, 15, tzinfo=tz), "15Min"),
                self._bar(datetime(2026, 6, 5, 13, 0, tzinfo=tz), "1Hour"),
            ]
        )
        report = HistoricalBarsStatusReport(
            config=self._config(),
            usage_ledger=ledger,
        ).build_report(
            days=1,
            timeframe="1Min",
            end_at=datetime(2026, 6, 6, 0, 25, 49, tzinfo=tz),
            equity_symbols=(),
            crypto_symbols=("AVAX/USD",),
        )

        replay = report["replay_readiness"]
        self.assertEqual(replay["matching_rows"], 0)
        self.assertFalse(replay["can_replay_requested_range"])
        self.assertEqual(replay["reason"], "timeframe_not_present_in_historical_store")

    def test_report_confirms_replay_ready_window(self) -> None:
        tz = ZoneInfo("UTC")
        ledger = _HistoricalBarsLedger(
            [
                self._bar(datetime(2026, 6, 5, 12, 0, tzinfo=tz), "15Min"),
                self._bar(datetime(2026, 6, 5, 12, 15, tzinfo=tz), "15Min"),
                self._bar(datetime(2026, 6, 5, 12, 30, tzinfo=tz), "15Min"),
                self._bar(datetime(2026, 6, 5, 12, 45, tzinfo=tz), "15Min"),
            ]
        )
        report = HistoricalBarsStatusReport(
            config=self._config(),
            usage_ledger=ledger,
        ).build_report(
            days=1,
            timeframe="15Min",
            start_at=datetime(2026, 6, 5, 12, 0, tzinfo=tz),
            end_at=datetime(2026, 6, 5, 12, 31, tzinfo=tz),
            equity_symbols=(),
            crypto_symbols=("AVAX/USD",),
        )

        replay = report["replay_readiness"]
        self.assertGreaterEqual(replay["matching_rows"], 3)
        self.assertGreaterEqual(replay["replay_timestamps"], 3)
        self.assertGreaterEqual(replay["eligible_timestamps"], 2)
        self.assertTrue(replay["can_replay_requested_range"])
        self.assertEqual(replay["reason"], "ok")

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            historical_replay_default_days=1,
            historical_replay_default_timeframe="15Min",
            discovery_equity_symbols=(),
            discovery_crypto_symbols=("AVAX/USD",),
            shadow_checkpoint_windows=("15m",),
        )

    def _bar(self, ts: datetime, timeframe: str) -> dict[str, object]:
        return {
            "batch_id": "batch",
            "captured_at": ts,
            "source": "alpaca_crypto_data",
            "asset_class": "crypto",
            "symbol": "AVAX/USD",
            "timeframe": timeframe,
            "bar_timestamp": ts,
            "canonical_instrument_id": "AVAX-USD-SPOT",
            "venue": "ALPACA",
            "venue_symbol": "AVAX/USD",
            "quote_currency": "USD",
            "usd_to_gbp_rate": 0.79,
            "open_price": 10.0,
            "high_price": 10.1,
            "low_price": 9.9,
            "close_price": 10.0,
            "open_price_gbp": 7.9,
            "high_price_gbp": 7.98,
            "low_price_gbp": 7.82,
            "close_price_gbp": 7.9,
            "volume": 1000,
            "trade_count": 10,
            "vwap": 10.0,
        }


if __name__ == "__main__":
    unittest.main()
