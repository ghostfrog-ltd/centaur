from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.reporting.historical_coverage_report import HistoricalCoverageReport


class _CoverageLedger:
    backend = "sqlite"

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def summarize_historical_bar_coverage(
        self,
        *,
        asset_class: str | None = None,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        symbol_filter = set(symbols or [])
        timeframe_filter = set(timeframes or [])
        for row in self.rows:
            if asset_class and str(row.get("asset_class", "")) != asset_class:
                continue
            if symbol_filter and str(row.get("symbol", "")) not in symbol_filter:
                continue
            if timeframe_filter and str(row.get("timeframe", "")) not in timeframe_filter:
                continue
            result.append(dict(row))
        return result


class _FailingCoverageLedger(_CoverageLedger):
    def summarize_historical_bar_coverage(
        self,
        *,
        asset_class: str | None = None,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        raise RuntimeError("LockNotAvailable: canceling statement due to lock timeout")


class HistoricalCoverageReportTests(unittest.TestCase):
    def test_reports_only_1min_backfilled_when_replay_timeframes_are_missing(self) -> None:
        tz = ZoneInfo("UTC")
        report = HistoricalCoverageReport(
            config=self._config(("AAPL", "TSLA")),
            usage_ledger=_CoverageLedger(
                [
                    self._row("AAPL", "1Min", 1200, datetime(2026, 1, 1, tzinfo=tz), datetime(2026, 6, 1, tzinfo=tz)),
                    self._row("TSLA", "1Min", 1400, datetime(2026, 1, 1, tzinfo=tz), datetime(2026, 6, 1, tzinfo=tz)),
                ]
            ),
        ).build_report()

        self.assertEqual(report["verdict"], "only_1min_backfilled")
        summary = {item["timeframe"]: item for item in report["timeframe_summary"]}
        self.assertEqual(summary["1Min"]["symbols_with_rows"], 2)
        self.assertEqual(summary["15Min"]["symbols_with_rows"], 0)
        self.assertEqual(summary["1Hour"]["symbols_with_rows"], 0)

    def test_reports_symbol_coverage_gap_when_symbol_has_no_rows_in_any_timeframe(self) -> None:
        tz = ZoneInfo("UTC")
        report = HistoricalCoverageReport(
            config=self._config(("AAPL", "TSLA")),
            usage_ledger=_CoverageLedger(
                [
                    self._row("AAPL", "15Min", 50, datetime(2026, 1, 1, tzinfo=tz), datetime(2026, 6, 1, tzinfo=tz)),
                ]
            ),
        ).build_report()

        self.assertEqual(report["verdict"], "symbol_coverage_gap")
        self.assertEqual(report["symbol_coverage_gap_count"], 1)

    def test_render_includes_source_and_venue_for_symbol_timeframe_rows(self) -> None:
        tz = ZoneInfo("UTC")
        rendered = HistoricalCoverageReport(
            config=self._config(("AAPL",)),
            usage_ledger=_CoverageLedger(
                [
                    self._row("AAPL", "15Min", 400, datetime(2021, 1, 1, tzinfo=tz), datetime(2026, 6, 1, tzinfo=tz)),
                ]
            ),
        ).render()

        self.assertIn("symbol=AAPL | timeframe=15Min | row_count=400", rendered)
        self.assertIn("source=alpaca_market_data", rendered)
        self.assertIn("venue=ALPACA", rendered)

    def test_lock_timeout_returns_temporarily_unavailable_report(self) -> None:
        report = HistoricalCoverageReport(
            config=self._config(("AAPL",)),
            usage_ledger=_FailingCoverageLedger([]),
        ).build_report()

        self.assertEqual(report["status"], "temporarily_unavailable")
        self.assertEqual(report["reason"], "historical_coverage_query_lock_timeout")

    def test_render_shows_operator_safe_failure_reason(self) -> None:
        rendered = HistoricalCoverageReport(
            config=self._config(("AAPL",)),
            usage_ledger=_FailingCoverageLedger([]),
        ).render()

        self.assertIn("Historical Coverage Report", rendered)
        self.assertIn("status=temporarily_unavailable", rendered)
        self.assertIn("reason=historical_coverage_query_lock_timeout", rendered)

    def _config(self, symbols: tuple[str, ...]) -> SimpleNamespace:
        return SimpleNamespace(
            discovery_equity_symbols=symbols,
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            shadow_min_opportunity_score=55.0,
            crypto_momentum_stop_loss_pct=0.02,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=55.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=3.0,
            crypto_momentum_min_trade_count=1,
            crypto_momentum_min_volume_gbp=50_000.0,
            crypto_momentum_max_spread_pct=0.25,
        )

    def _row(
        self,
        symbol: str,
        timeframe: str,
        row_count: int,
        earliest: datetime,
        latest: datetime,
    ) -> dict[str, object]:
        return {
            "asset_class": "equity",
            "symbol": symbol,
            "timeframe": timeframe,
            "row_count": row_count,
            "earliest_bar_timestamp": earliest,
            "latest_bar_timestamp": latest,
            "sources": ["alpaca_market_data"],
            "venues": ["ALPACA"],
            "distinct_bar_days": 40,
        }


if __name__ == "__main__":
    unittest.main()
