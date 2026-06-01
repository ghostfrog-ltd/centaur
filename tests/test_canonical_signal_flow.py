from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.engine.candidate_engine import rank_candidates
from app.strategies.crypto_momentum import CryptoMomentumStrategy


class CanonicalSignalFlowTests(unittest.TestCase):
    def test_discovery_preserves_canonical_instrument_metadata(self) -> None:
        ranked = rank_candidates(
            current_rows=[
                {
                    "source": "alpaca_crypto_data",
                    "symbol": "BTC/USD",
                    "asset_class": "crypto",
                    "canonical_instrument_id": "BTC-USD-SPOT",
                    "venue": "alpaca",
                    "venue_symbol": "BTC/USD",
                    "close_price": 100.0,
                    "volume": 1000,
                    "trade_count": 20,
                }
            ],
            previous_by_symbol={},
            target_count=1,
        )

        candidate = ranked[0].as_dict()

        self.assertEqual(candidate["canonical_instrument_id"], "BTC-USD-SPOT")
        self.assertEqual(candidate["venue"], "alpaca")
        self.assertEqual(candidate["venue_symbol"], "BTC/USD")
        self.assertEqual(
            candidate["instrument_ref"],
            {
                "canonical_instrument_id": "BTC-USD-SPOT",
                "venue": "alpaca",
                "venue_symbol": "BTC/USD",
                "asset_class": "crypto",
            },
        )

    def test_strategy_signal_preserves_canonical_instrument_metadata(self) -> None:
        config = SimpleNamespace(
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=60.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=2.5,
            crypto_momentum_min_trade_count=2,
            crypto_momentum_min_volume_gbp=50_000.0,
            crypto_momentum_max_spread_pct=0.25,
            shadow_min_opportunity_score=50.0,
        )
        profile = CryptoMomentumStrategy().build_profiles(config)[0]
        signal = CryptoMomentumStrategy().evaluate_candidate(
            profile=profile,
            candidate={
                "source": "alpaca_crypto_data",
                "symbol": "BTC/USD",
                "asset_class": "crypto",
                "canonical_instrument_id": "BTC-USD-SPOT",
                "venue": "alpaca",
                "venue_symbol": "BTC/USD",
                "close_price": 100.0,
                "close_price_gbp": 79.0,
                "movement_pct": 0.4,
                "discovery_score": 5.0,
                "trade_count": 10,
                "volume": 1000,
            },
            market_context={},
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        row = signal.as_dict(tick_id="test")
        self.assertEqual(row["canonical_instrument_id"], "BTC-USD-SPOT")
        self.assertEqual(row["venue"], "alpaca")
        self.assertEqual(row["venue_symbol"], "BTC/USD")
        self.assertEqual(row["instrument_ref"]["canonical_instrument_id"], "BTC-USD-SPOT")
        self.assertEqual(row["instrument_ref"]["venue_symbol"], "BTC/USD")
        self.assertEqual(row["stop_loss_price"], 99.0)
        self.assertEqual(row["target_price"], 102.0)


if __name__ == "__main__":
    unittest.main()
