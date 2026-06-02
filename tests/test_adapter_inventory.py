from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.framework.reporting.adapter_inventory import AdapterInventoryReport


class AdapterInventoryReportTests(unittest.TestCase):
    def test_inventory_lists_active_and_unimplemented_adapters(self) -> None:
        report = AdapterInventoryReport(
            config=SimpleNamespace(centaur_mode="live", centaur_environment="live")
        ).build_report()

        records = {
            (item["adapter_type"], item["provider_id"]): item
            for item in report["records"]
        }

        self.assertEqual(report["active_market_data_provider"], "alpaca")
        self.assertEqual(
            records[("market_data", "alpaca")]["implementation"],
            "AlpacaMarketDataAdapter",
        )
        self.assertEqual(
            records[("execution", "alpaca_live")]["status"],
            "active_bridge",
        )
        self.assertEqual(
            records[("market_data", "binance")]["status"],
            "not_implemented",
        )
        self.assertEqual(
            records[("broker_account", "trading212_paper")]["status"],
            "active_paper",
        )
        self.assertEqual(
            records[("execution", "trading212_paper")]["status"],
            "active_bridge",
        )
        self.assertEqual(
            records[("broker_account", "trading212_live")]["status"],
            "disabled_live",
        )
        self.assertEqual(
            records[("execution", "trading212_live")]["status"],
            "disabled_live",
        )
        self.assertEqual(
            records[("market_data", "trading212_live")]["status"],
            "disabled_live",
        )
        self.assertEqual(
            records[("market_data", "trading212_paper")]["status"],
            "metadata_only",
        )
        self.assertIn(
            "configured_price_provider=disabled",
            records[("market_data", "trading212_paper")]["behavior"],
        )
        self.assertFalse(report["non_alpaca_active"])

    def test_render_includes_activation_rule_warning(self) -> None:
        rendered = AdapterInventoryReport(
            config=SimpleNamespace(centaur_mode="paper", centaur_environment="paper")
        ).render()

        self.assertIn("Centaur Adapter Inventory", rendered)
        self.assertIn("market_data/alpaca", rendered)
        self.assertIn("execution/binance", rendered)
        self.assertIn("must not be used for trading", rendered)


if __name__ == "__main__":
    unittest.main()
