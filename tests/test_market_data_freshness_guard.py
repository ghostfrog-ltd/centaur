from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.strategies.registry import evaluate_strategies


class MarketDataFreshnessGuardTests(unittest.TestCase):
    def test_stale_trading212_positions_source_is_excluded_from_strategy_evaluation(self) -> None:
        module = importlib.import_module(
            "app.heartbeat.steps.23_market_scan.implementation.main"
        )
        started_at = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("UTC"))
        current_rows = [
            {
                "source": "trading212_market_data",
                "symbol": "VOD",
                "asset_class": "equity",
                "bar_timestamp": (started_at - timedelta(hours=63)).isoformat(),
                "close_price": 72.5,
            }
        ]
        context = SimpleNamespace(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                discovery_equity_symbols=("VOD",),
                discovery_crypto_symbols=(),
                discovery_target_count=6,
                max_bar_age_crypto_seconds=600,
                max_bar_age_equity_seconds=1800,
                allow_stale_market_data_for_research=False,
            ),
            usage_ledger=SimpleNamespace(
                get_latest_bars_for_tick=lambda **_kwargs: current_rows,
                get_previous_bars=lambda **_kwargs: {},
                record_discovery_candidates=lambda **_kwargs: None,
            ),
            state={
                "market_gate": {"can_scan": True, "reason": "market_open"},
                "trading212_data_latest_bars": {"provider": "positions_api"},
            },
        )

        result = module.run_implementation(context)

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(result["skip_reason"], "no_fresh_market_data")
        self.assertEqual(result["candidates_excluded_due_to_stale_source"], 1)
        self.assertEqual(result["candidates_excluded_due_to_account_only_source"], 1)
        self.assertIn("trading212_market_data", result["stale_sources_excluded"])
        self.assertEqual(
            result["source_freshness_status"]["trading212_market_data"]["status"],
            "account_only",
        )
        self.assertEqual(len(context.state["market_scan"]["discovered_candidates"]), 1)
        self.assertEqual(len(context.state["market_scan"]["selected_candidates"]), 0)
        self.assertEqual(
            context.state["market_scan"]["excluded_candidates"][0]["market_data_rejection_reason"],
            "market_data_source_account_only_positions_api",
        )
        self.assertIsNone(context.state["market_scan"]["excluded_candidates"][0]["movement_pct"])

    def test_fresh_alpaca_candidates_remain_eligible(self) -> None:
        module = importlib.import_module(
            "app.heartbeat.steps.23_market_scan.implementation.main"
        )
        started_at = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("UTC"))
        current_rows = [
            {
                "source": "alpaca_market_data",
                "symbol": "AAPL",
                "asset_class": "equity",
                "bar_timestamp": (started_at - timedelta(minutes=2)).isoformat(),
                "close_price": 100.0,
                "volume": 1000,
                "trade_count": 20,
            }
        ]
        previous_rows = {
            ("alpaca_market_data", "AAPL"): {
                "close_price": 99.0,
                "bar_timestamp": (started_at - timedelta(minutes=3)).isoformat(),
            }
        }
        recorded: dict[str, object] = {}
        context = SimpleNamespace(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                discovery_equity_symbols=("AAPL",),
                discovery_crypto_symbols=(),
                discovery_target_count=6,
                max_bar_age_crypto_seconds=600,
                max_bar_age_equity_seconds=1800,
                allow_stale_market_data_for_research=False,
            ),
            usage_ledger=SimpleNamespace(
                get_latest_bars_for_tick=lambda **_kwargs: current_rows,
                get_previous_bars=lambda **_kwargs: previous_rows,
                record_discovery_candidates=lambda **kwargs: recorded.update(kwargs),
            ),
            state={
                "market_gate": {"can_scan": True, "reason": "market_open"},
                "trading212_data_latest_bars": {"provider": "disabled"},
            },
        )

        result = module.run_implementation(context)

        self.assertEqual(result["mode"], "dynamic_discovery")
        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["selected_candidates"], 1)
        self.assertEqual(
            result["market_data_source_used_for_strategy"]["equity"],
            "alpaca_market_data",
        )
        candidate = context.state["market_scan"]["selected_candidates"][0]
        self.assertTrue(candidate["market_data_eligible"])
        self.assertAlmostEqual(candidate["movement_pct"], 1.010101, places=6)
        self.assertEqual(recorded["tick_id"], "test")

    def test_strategy_reports_skipped_no_fresh_market_data_for_equities(self) -> None:
        config = SimpleNamespace(
            shadow_min_opportunity_score=55.0,
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=60.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=2.5,
            crypto_momentum_min_trade_count=2,
            crypto_momentum_min_volume_gbp=50000.0,
            crypto_momentum_max_spread_pct=0.25,
        )

        batch = evaluate_strategies(
            tick_id="test",
            candidates=[],
            config=config,
            market_context={
                "market_data_source_used_for_strategy": {},
                "candidates_excluded_due_to_stale_source_by_asset_class": {"equity": 1},
            },
        )

        reasons = {
            item["reason"]
            for item in batch.rejection_summary.get("by_strategy_reason", [])
        }
        self.assertIn("strategy.skipped_no_fresh_market_data", reasons)

    def test_strategy_step_surfaces_skipped_no_fresh_market_data_when_scan_excluded_equities(self) -> None:
        module = importlib.import_module(
            "app.heartbeat.steps.26_strategy_signals.implementation.main"
        )
        context = SimpleNamespace(
            tick_id="test",
            started_at=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("UTC")),
            config=SimpleNamespace(),
            state={
                "context_enrichment": {"candidates": []},
                "market_scan": {
                    "excluded_candidates": [{"symbol": "VOD", "asset_class": "equity"}]
                },
            },
        )

        result = module.run_implementation(context)

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(
            result["rejection_summary"]["by_strategy_reason"][0]["reason"],
            "strategy.skipped_no_fresh_market_data",
        )

    def test_trading212_positions_data_remains_account_state(self) -> None:
        module = importlib.import_module(
            "app.heartbeat.steps.23_market_scan.implementation.main"
        )
        started_at = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("UTC"))
        context = SimpleNamespace(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                discovery_equity_symbols=("VOD",),
                discovery_crypto_symbols=(),
                discovery_target_count=6,
                max_bar_age_crypto_seconds=600,
                max_bar_age_equity_seconds=1800,
                allow_stale_market_data_for_research=False,
            ),
            usage_ledger=SimpleNamespace(
                get_latest_bars_for_tick=lambda **_kwargs: [],
            ),
            state={
                "market_gate": {"can_scan": True, "reason": "market_open"},
                "trading212_data_latest_bars": {"provider": "positions_api"},
                "trading212_paper_positions": {"raw": [{"symbol": "VOD", "quantity": 1}]},
            },
        )

        result = module.run_implementation(context)

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(
            context.state["trading212_paper_positions"]["raw"][0]["symbol"],
            "VOD",
        )


if __name__ == "__main__":
    unittest.main()
