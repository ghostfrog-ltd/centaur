from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.framework.strategies.crypto_momentum import CryptoMomentumStrategy
from app.framework.strategies.crypto_pullback import CryptoPullbackStrategy
from app.framework.strategies.crypto_research import CryptoResearchStrategy
from app.framework.strategies.mean_reversion import MeanReversionStrategy
from app.framework.strategies.momentum_breakout import MomentumVolatilityBreakoutStrategy
from app.framework.strategies.registry import evaluate_strategies


class StrategyRegistryTests(unittest.TestCase):
    def test_mean_reversion_snapback_accepts_only_deep_equity_pullbacks(self) -> None:
        config = self._config()
        strategy = MeanReversionStrategy()
        profile = strategy.build_profiles(config)[0]

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate={
                "source": "alpaca_equity_data",
                "symbol": "AAPL",
                "asset_class": "equity",
                "canonical_instrument_id": "AAPL-US-EQUITY",
                "close_price": 100.0,
                "close_price_gbp": 79.0,
                "movement_pct": -0.25,
                "discovery_score": 5.0,
                "trade_count": 100,
                "volume": 10_000,
            },
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "mean_reversion.snapback")
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.stop_loss_price, 98.2)
        self.assertEqual(signal.target_price, 103.15)
        self.assertEqual(signal.risk_pct, 1.8)
        self.assertEqual(signal.target_return_pct, 3.15)

        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={
                    "source": "alpaca_equity_data",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "canonical_instrument_id": "AAPL-US-EQUITY",
                    "close_price": 100.0,
                    "movement_pct": 0.25,
                    "discovery_score": 5.0,
                    "trade_count": 100,
                    "volume": 10_000,
                },
                market_context={},
            )
        )
        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={
                    "source": "alpaca_crypto_data",
                    "symbol": "BTC/USD",
                    "asset_class": "crypto",
                    "canonical_instrument_id": "BTC-USD-SPOT",
                    "close_price": 100.0,
                    "movement_pct": -0.25,
                    "discovery_score": 5.0,
                    "trade_count": 100,
                    "volume": 10_000,
                },
                market_context={},
            )
        )

    def test_crypto_momentum_uses_lane_specific_one_percent_stop(self) -> None:
        config = self._config()
        strategy = CryptoMomentumStrategy()
        profile = strategy.build_profiles(config)[0]

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate={
                "source": "alpaca_crypto_data",
                "symbol": "BTC/USD",
                "asset_class": "crypto",
                "canonical_instrument_id": "BTC-USD-SPOT",
                "close_price": 100.0,
                "close_price_gbp": 79.0,
                "movement_pct": 0.2,
                "discovery_score": 5.0,
                "trade_count": 10,
                "volume": 1_000,
            },
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "crypto_momentum.trend")
        self.assertEqual(signal.stop_loss_price, 99.0)
        self.assertEqual(signal.target_price, 102.0)
        self.assertEqual(signal.risk_pct, 1.0)
        self.assertEqual(signal.target_return_pct, 2.0)

        weak_signal = strategy.evaluate_candidate(
            profile=profile,
            candidate={
                "source": "alpaca_crypto_data",
                "symbol": "BTC/USD",
                "asset_class": "crypto",
                "canonical_instrument_id": "BTC-USD-SPOT",
                "close_price": 100.0,
                "close_price_gbp": 79.0,
                "movement_pct": 0.149,
                "discovery_score": 5.0,
                "trade_count": 10,
                "volume": 1_000,
            },
            market_context={},
        )
        self.assertIsNone(weak_signal)

    def test_crypto_momentum_rejects_spikes_low_volume_and_wide_spreads(self) -> None:
        config = self._config()
        strategy = CryptoMomentumStrategy()
        profile = strategy.build_profiles(config)[0]
        base_candidate = {
            "source": "alpaca_crypto_data",
            "symbol": "BTC/USD",
            "asset_class": "crypto",
            "canonical_instrument_id": "BTC-USD-SPOT",
            "close_price": 100.0,
            "close_price_gbp": 79.0,
            "movement_pct": 0.2,
            "discovery_score": 5.0,
            "trade_count": 10,
            "volume": 1_000,
        }

        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**base_candidate, "movement_pct": 3.0},
                market_context={},
            )
        )
        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**base_candidate, "volume": 10},
                market_context={},
            )
        )
        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**base_candidate, "spread_pct": 0.5},
                market_context={},
            )
        )

    def test_crypto_research_dip_rebound_is_crypto_only_shadow_signal(self) -> None:
        config = self._config()
        strategy = CryptoResearchStrategy()
        profile = strategy.build_profiles(config)[0]
        candidate = {
            "source": "alpaca_crypto_data",
            "symbol": "ETH/USD",
            "asset_class": "crypto",
            "canonical_instrument_id": "ETH-USD-SPOT",
            "close_price": 100.0,
            "close_price_gbp": 79.0,
            "movement_pct": -0.4,
            "discovery_score": 4.0,
            "trade_count": 10,
            "volume": 1_000,
        }

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate=candidate,
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "crypto_research.dip_rebound")
        self.assertEqual(signal.asset_class, "crypto")
        self.assertEqual(signal.note, "shadow_only_crypto_dip_rebound")
        self.assertEqual(signal.stop_loss_price, 99.0)
        self.assertEqual(signal.target_price, 102.0)

        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**candidate, "asset_class": "equity", "symbol": "AAPL"},
                market_context={},
            )
        )
        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**candidate, "movement_pct": -3.0},
                market_context={},
            )
        )
        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**candidate, "spread_pct": 0.5},
                market_context={},
            )
        )

    def test_crypto_pullback_downside_watch_emits_paper_research_signal_only_on_negative_moves(self) -> None:
        config = self._config()
        strategy = CryptoPullbackStrategy()
        profile = strategy.build_profiles(config)[0]
        candidate = {
            "source": "alpaca_crypto_data",
            "symbol": "AVAX/USD",
            "asset_class": "crypto",
            "canonical_instrument_id": "AVAX-USD-SPOT",
            "close_price": 100.0,
            "close_price_gbp": 79.0,
            "movement_pct": -0.417,
            "discovery_score": 2.8,
            "trade_count": 3,
            "volume": 1_000,
            "volume_gbp": 79_000.0,
            "spread_pct": 0.12,
        }

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate=candidate,
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "crypto_pullback.downside_reversal_watch")
        self.assertEqual(signal.direction, "pullback_watch")
        self.assertEqual(signal.note, "paper_research_only_crypto_pullback_watch")

        self.assertIsNone(
            strategy.evaluate_candidate(
                profile=profile,
                candidate={**candidate, "movement_pct": 0.417},
                market_context={},
            )
        )

    def test_crypto_research_range_breakout_requires_crypto_technical_confirmation(self) -> None:
        config = self._config()
        strategy = CryptoResearchStrategy()
        profile = strategy.build_profiles(config)[1]
        candidate = {
            "source": "alpaca_crypto_data",
            "symbol": "SOL/USD",
            "asset_class": "crypto",
            "canonical_instrument_id": "SOL-USD-SPOT",
            "close_price": 100.0,
            "close_price_gbp": 79.0,
            "movement_pct": 0.35,
            "discovery_score": 4.0,
            "trade_count": 10,
            "volume": 1_000,
            "technical_context_ready": True,
            "price_trigger_20": True,
            "volume_ratio_20": 1.8,
            "atr_pct_20": 0.8,
        }

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate=candidate,
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "crypto_research.range_breakout")
        self.assertEqual(signal.asset_class, "crypto")
        self.assertEqual(signal.note, "shadow_only_crypto_range_breakout")

        for override in (
            {"technical_context_ready": False},
            {"price_trigger_20": False},
            {"volume_ratio_20": 1.25},
            {"atr_pct_20": 0.1},
            {"atr_pct_20": 4.0},
            {"movement_pct": 3.0},
        ):
            self.assertIsNone(
                strategy.evaluate_candidate(
                    profile=profile,
                    candidate={**candidate, **override},
                    market_context={},
                )
            )

    def test_crypto_research_profiles_are_not_execution_allowlisted(self) -> None:
        paper_allowed = {
            "mean_reversion.snapback",
            "crypto_momentum.trend",
            "momentum.volatility_breakout",
        }
        live_allowed = set(paper_allowed)
        research_ids = {
            profile.strategy_id
            for profile in CryptoResearchStrategy().build_profiles(self._config())
        }

        self.assertTrue(research_ids)
        self.assertTrue(research_ids.isdisjoint(paper_allowed))
        self.assertTrue(research_ids.isdisjoint(live_allowed))

    def test_crypto_pullback_profile_is_not_live_execution_allowlisted(self) -> None:
        strategy_id = CryptoPullbackStrategy().build_profiles(self._config())[0].strategy_id
        paper_allowed = {
            "mean_reversion.snapback",
            "crypto_momentum.trend",
            "momentum.volatility_breakout",
        }
        live_allowed = set(paper_allowed)

        self.assertNotIn(strategy_id, live_allowed)

    def test_volatility_breakout_requires_ready_trigger_volume_and_atr_floor(self) -> None:
        config = self._config()
        strategy = MomentumVolatilityBreakoutStrategy()
        profile = strategy.build_profiles(config)[0]

        signal = strategy.evaluate_candidate(
            profile=profile,
            candidate={
                **self._breakout_candidate(),
                "volume_ratio_20": 2.5,
                "atr_pct_20": 1.5,
            },
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.strategy_id, "momentum.volatility_breakout")
        self.assertEqual(signal.stop_loss_price, 102.0)
        self.assertEqual(signal.target_price, 111.0)
        self.assertEqual(signal.break_even_trigger_price, 108.0)
        self.assertEqual(signal.trailing_stop_mode, "break_even_next_bar")
        self.assertEqual(signal.risk_pct, 2.857143)
        self.assertEqual(signal.target_return_pct, 5.714286)

        for override in (
            {"technical_context_ready": False},
            {"price_trigger_20": False},
            {"volume_ratio_20": 2.0},
            {"atr_pct_20": 1.0},
        ):
            self.assertIsNone(
                strategy.evaluate_candidate(
                    profile=profile,
                    candidate={**self._breakout_candidate(), **override},
                    market_context={},
                )
            )

    def test_evaluate_strategies_ranks_strategy_signals_deterministically(self) -> None:
        batch = evaluate_strategies(
            tick_id="tick-test",
            config=self._config(),
            market_context={},
            candidates=[
                {
                    "source": "alpaca_equity_data",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "canonical_instrument_id": "AAPL-US-EQUITY",
                    "close_price": 100.0,
                    "movement_pct": -0.25,
                    "discovery_score": 5.0,
                    "trade_count": 100,
                    "volume": 10_000,
                },
                {
                    "source": "alpaca_crypto_data",
                    "symbol": "BTC/USD",
                    "asset_class": "crypto",
                    "canonical_instrument_id": "BTC-USD-SPOT",
                    "close_price": 100.0,
                    "close_price_gbp": 79.0,
                    "movement_pct": 0.2,
                    "discovery_score": 5.0,
                    "trade_count": 10,
                    "volume": 1_000,
                },
                {
                    **self._breakout_candidate(),
                    "volume_ratio_20": 2.5,
                    "atr_pct_20": 1.5,
                },
                {
                    "source": "alpaca_crypto_data",
                    "symbol": "SOL/USD",
                    "asset_class": "crypto",
                    "canonical_instrument_id": "SOL-USD-SPOT",
                    "close_price": 100.0,
                    "close_price_gbp": 79.0,
                    "movement_pct": 0.35,
                    "discovery_score": 4.0,
                    "trade_count": 10,
                    "volume": 1_000,
                    "technical_context_ready": True,
                    "price_trigger_20": True,
                    "volume_ratio_20": 1.8,
                    "atr_pct_20": 0.8,
                },
            ],
        )

        signal_ids = {signal.strategy_id for signal in batch.signals}
        self.assertIn("mean_reversion.snapback", signal_ids)
        self.assertIn("crypto_momentum.trend", signal_ids)
        self.assertIn("crypto_research.range_breakout", signal_ids)
        self.assertIn("momentum.volatility_breakout", signal_ids)
        self.assertEqual(
            [signal.signal_rank for signal in batch.signals],
            list(range(1, len(batch.signals) + 1)),
        )
        self.assertGreaterEqual(batch.family_count, 3)
        self.assertGreaterEqual(batch.profile_count, 3)
        self.assertGreater(batch.rejection_summary["total_rejections"], 0)

    def test_rejection_summary_records_missing_identity(self) -> None:
        batch = evaluate_strategies(
            tick_id="tick-test",
            config=self._config(),
            market_context={},
            candidates=[
                {
                    "source": "alpaca_equity_data",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "close_price": 100.0,
                    "movement_pct": -0.25,
                    "discovery_score": 5.0,
                    "trade_count": 100,
                    "volume": 10_000,
                }
            ],
        )

        self.assertEqual(batch.signals, [])
        reasons = {
            row["reason"]
            for row in batch.rejection_summary.get("by_strategy_reason", [])
        }
        self.assertIn("missing_instrument_identity", reasons)

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            shadow_min_opportunity_score=55.0,
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=60.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=2.5,
            crypto_momentum_min_trade_count=2,
            crypto_momentum_min_volume_gbp=50_000.0,
            crypto_momentum_max_spread_pct=0.25,
        )

    def _breakout_candidate(self) -> dict[str, object]:
        return {
            "source": "alpaca_equity_data",
            "symbol": "MSFT",
            "asset_class": "equity",
            "canonical_instrument_id": "MSFT-US-EQUITY",
            "close_price": 105.0,
            "close_price_gbp": 82.95,
            "movement_pct": 1.2,
            "discovery_score": 5.0,
            "technical_context_ready": True,
            "breakout_high_20": 104.0,
            "avg_volume_20": 10_000.0,
            "atr_20": 1.5,
            "atr_pct_20": 1.5,
            "volume_ratio_20": 2.5,
            "breakout_margin_pct_20": 0.961538,
            "price_trigger_20": True,
        }


if __name__ == "__main__":
    unittest.main()
