import unittest

from app.adapters.execution.alpaca_live import AlpacaLiveExecutionAdapter
from app.adapters.execution.alpaca_paper import AlpacaPaperExecutionAdapter
from app.adapters.market_data.alpaca_data import AlpacaMarketDataAdapter
from app.core.instruments import default_instrument_registry
from app.engine.execution_planner import ExecutionRouter
from app.runtime.mode_context import ModeContext
from app.storage.layout import storage_layout_from_config


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


if __name__ == "__main__":
    unittest.main()
