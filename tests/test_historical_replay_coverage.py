from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.reporting.historical_replay_coverage import HistoricalReplayCoverageReport
from app.framework.engine.research_cycle import ResearchCycleRunner


class _Ledger:
    backend = "postgres"
    backend_detail = "test"

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def summarize_historical_bars(self, *, as_of: datetime | None = None) -> dict[str, object]:
        ordered = sorted(self.rows, key=lambda row: row["bar_timestamp"])
        return {
            "backend": self.backend,
            "backend_detail": self.backend_detail,
            "historical": {
                "rows_by_source": [{"source": "alpaca_crypto_data", "rows": len(self.rows)}],
                "rows_by_timeframe": [{"timeframe": "15Min", "rows": len(self.rows)}],
                "symbol_rows": [{"symbol": "AVAX/USD"}],
                "min_bar_timestamp": ordered[0]["bar_timestamp"],
                "max_bar_timestamp": ordered[-1]["bar_timestamp"],
                "distinct_symbols": 1,
            },
            "latest": {},
            "replay_readiness": {},
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
        _ = (sources, start_at, end_at, symbols)
        return [dict(row) for row in self.rows if str(row.get("timeframe", "")) == timeframe]


class HistoricalReplayCoverageReportTests(unittest.TestCase):
    def test_render_reports_latest_valid_replay_window_end(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 5, 9, 45, tzinfo=tz)
        rows = []
        current = latest_bar - timedelta(days=12)
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _CoverageLedger(_Ledger):
            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                _ = (sources, symbols)
                selected = [dict(row) for row in self.rows if str(row.get("timeframe", "")) == timeframe]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        report = HistoricalReplayCoverageReport(
            config=SimpleNamespace(
                research_replay_days=5,
                research_replay_timeframe="15Min",
                research_min_windows=4,
                discovery_equity_symbols=(),
                discovery_crypto_symbols=("AVAX/USD",),
                historical_replay_default_days=5,
                historical_replay_default_timeframe="15Min",
                shadow_checkpoint_windows=("15m", "1h", "1d", "7d"),
            ),
            usage_ledger=_CoverageLedger(rows),
        )

        rendered = report.render()

        self.assertIn("latest_valid_replay_window_end=2026-05-29T09:45:00+00:00", rendered)
        self.assertIn("window_anchor_mode=latest_historical_bar_minus_future_horizon", rendered)
        self.assertIn("replay_window_candidates_accepted=4", rendered)

    def test_render_includes_rejected_replay_window_reason(self) -> None:
        tz = ZoneInfo("UTC")
        rows = [
            {
                "source": "alpaca_crypto_data",
                "asset_class": "crypto",
                "symbol": "AVAX/USD",
                "timeframe": "15Min",
                "bar_timestamp": datetime(2026, 6, 5, 12, 0, tzinfo=tz),
            }
        ]
        report = HistoricalReplayCoverageReport(
            config=SimpleNamespace(
                research_replay_days=1,
                research_replay_timeframe="1Min",
                research_min_windows=2,
                discovery_equity_symbols=(),
                discovery_crypto_symbols=("AVAX/USD",),
                historical_replay_default_days=1,
                historical_replay_default_timeframe="1Min",
                shadow_checkpoint_windows=("15m", "1h", "1d", "7d"),
            ),
            usage_ledger=_Ledger(rows),
        )

        rendered = report.render()

        self.assertIn("timeframe_exists_15Min=yes", rendered)
        self.assertIn("timeframe_exists_1Min=no", rendered)
        self.assertIn("replay_window_candidates_rejected=4", rendered)
        self.assertIn("reason=timeframe_not_present_in_historical_store", rendered)


if __name__ == "__main__":
    unittest.main()
