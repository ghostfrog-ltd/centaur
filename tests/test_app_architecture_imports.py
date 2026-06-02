import unittest

from app.framework.adapters.execution.alpaca_live import AlpacaLiveExecutionAdapter
from app.framework.adapters.execution.alpaca_paper import AlpacaPaperExecutionAdapter
from app.framework.adapters.brokers.trading212 import Trading212PaperBrokerAdapter
from app.framework.adapters.market_data.alpaca_data import AlpacaMarketDataAdapter
from app.framework.core.instruments import default_instrument_registry
from app.framework.engine.execution_planner import ExecutionRouter
from app.framework.runtime.mode_context import ModeContext
from app.heartbeat import build_heartbeat_cron_pipeline
from app.framework.storage.layout import storage_layout_from_config


class _Config:
    centaur_mode = "paper"
    centaur_environment = "paper"
    postgres_schema = ""
    postgres_core_schema = "core"
    postgres_paper_schema = "paper"
    postgres_live_schema = "live"


class AppArchitectureImportTests(unittest.TestCase):
    def test_app_architecture_facades_resolve_current_implementation(self) -> None:
        self.assertEqual(ModeContext.from_config(_Config()).mode, "paper")
        self.assertIsNotNone(ExecutionRouter)
        self.assertEqual(AlpacaPaperExecutionAdapter().broker_id, "alpaca_paper")
        self.assertEqual(AlpacaLiveExecutionAdapter().broker_id, "alpaca_live")
        self.assertEqual(
            Trading212PaperBrokerAdapter.from_config(
                type(
                    "Trading212Config",
                    (),
                    {
                        "trading212_paper_api_key": "",
                        "trading212_paper_api_secret": "",
                        "trading212_paper_base_url": "https://demo.trading212.com/api/v0",
                        "trading212_paper_request_timeout_seconds": 10,
                        "trading212_paper_primary_currency": "GBP",
                        "trading212_paper_ticker_overrides": {},
                        "trading212_paper_api_configured": False,
                        "trading212_paper_execution_enabled": True,
                        "trading212_paper_default_notional_native": 10.0,
                    },
                )()
            ).broker_id,
            "trading212_paper",
        )
        self.assertEqual(AlpacaMarketDataAdapter.provider_id, "alpaca")

        registry = default_instrument_registry()
        ref = registry.reference_for(
            venue="alpaca",
            venue_symbol="BTC/USD",
            asset_class="crypto",
        )
        self.assertEqual(ref.canonical_instrument_id, "BTC-USD-SPOT")

        layout = storage_layout_from_config(_Config())
        self.assertEqual(layout.core.postgres_schema, "core")
        self.assertEqual(layout.paper.postgres_schema, "paper")
        self.assertEqual(layout.live.postgres_schema, "live")

        heartbeat_steps = build_heartbeat_cron_pipeline()
        self.assertEqual(heartbeat_steps[0].name, "control.heartbeat")
        self.assertEqual(heartbeat_steps[-1].name, "notifications.slack")


if __name__ == "__main__":
    unittest.main()
