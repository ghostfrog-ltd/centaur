from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from app.framework.reporting.trading212_instruments import Trading212InstrumentReport


class Trading212InstrumentReportTests(unittest.TestCase):
    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            trading212_paper_api_configured=True,
            trading212_paper_equity_symbols=("VOD", "SHEL", "UK_GOLD"),
            trading212_paper_market_data_provider="disabled",
            trading212_paper_ticker_overrides={},
            operations_db_backend_preference="sqlite",
            usage_ledger_db_path=Path(":memory:"),
            database_url="",
            postgres_configured=False,
            paper_execution_enabled=False,
            live_execution_enabled=False,
            provider_pricing={},
        )

    def test_report_maps_real_tickers_and_keeps_blockers_visible(self) -> None:
        class FakeClient:
            def get_instruments(self, _context):
                return [
                    {
                        "ticker": "VOD_US_EQ",
                        "name": "Vodafone",
                        "currencyCode": "USD",
                        "exchange": "NASDAQ",
                    },
                    {
                        "ticker": "VODl_EQ",
                        "name": "Vodafone Group PLC",
                        "currencyCode": "GBX",
                        "exchange": "LSE",
                    },
                    {
                        "ticker": "SHELl_EQ",
                        "name": "Shell PLC",
                        "currencyCode": "GBX",
                        "exchange": "LSE",
                    },
                ]

        report = Trading212InstrumentReport(
            config=self._config(),
            client_factory=lambda _config: FakeClient(),
        ).build_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(
            [item["symbol"] for item in report["mapped_symbols"]],
            ["VOD", "SHEL"],
        )
        self.assertEqual(report["unmapped_symbols"], ["UK_GOLD"])
        self.assertEqual(report["price_source"]["status"], "disabled")
        self.assertIn("trading212_market_data_provider_disabled", report["blockers"])
        self.assertIn("trading212_latest_bars_source_missing", report["blockers"])
        self.assertIn("trading212_proposal_lane_missing", report["blockers"])

    def test_report_marks_unknown_price_source_as_not_implemented(self) -> None:
        class FakeClient:
            def get_instruments(self, _context):
                return [{"ticker": "VODl_EQ", "name": "Vodafone", "currencyCode": "GBX"}]

        config = self._config()
        config.trading212_paper_market_data_provider = "some_vendor"

        report = Trading212InstrumentReport(
            config=config,
            client_factory=lambda _config: FakeClient(),
        ).build_report()

        self.assertEqual(report["price_source"]["status"], "not_implemented")
        self.assertIn(
            "trading212_market_data_provider_not_implemented:some_vendor",
            report["blockers"],
        )

    def test_report_marks_positions_api_as_held_positions_only(self) -> None:
        class FakeClient:
            def get_instruments(self, _context):
                return [{"ticker": "VODl_EQ", "name": "Vodafone", "currencyCode": "GBX"}]

        config = self._config()
        config.trading212_paper_market_data_provider = "positions_api"
        config.trading212_paper_equity_symbols = ("VOD",)

        report = Trading212InstrumentReport(
            config=config,
            client_factory=lambda _config: FakeClient(),
        ).build_report()

        self.assertEqual(report["price_source"]["status"], "held_positions_only")
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            report["price_source"]["warning"],
            "requires_seed_positions_for_each_symbol",
        )

    def test_report_handles_missing_credentials(self) -> None:
        config = self._config()
        config.trading212_paper_api_configured = False

        report = Trading212InstrumentReport(config=config).build_report()

        self.assertEqual(report["status"], "not_configured")
        self.assertIn("trading212_paper_credentials_missing", report["blockers"])


if __name__ == "__main__":
    unittest.main()
