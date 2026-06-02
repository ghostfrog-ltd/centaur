from __future__ import annotations

import unittest

from app.framework.engine.fitness_engine import allocate_strategy_signals


class FitnessEngineAllocationTests(unittest.TestCase):
    def _signal(self, *, score: float) -> dict[str, object]:
        return {
            "strategy_id": "mean_reversion.snapback",
            "strategy_family": "mean_reversion",
            "profile_id": "snapback",
            "symbol": "AAPL",
            "asset_class": "equity",
            "holding_window_code": "1h",
            "signal_score": score,
            "confidence": 0.75,
            "target_return_pct": 2.0,
        }

    def _fitness_summary(self) -> dict[str, object]:
        return {
            "strategy_id": "mean_reversion.snapback",
            "asset_class": "equity",
            "checkpoint_code": "1h",
            "composite_fitness_score": -28.0,
            "sample_weight": 1.0,
            "checkpoints_evaluated": 12,
        }

    def test_score_to_trade_bypasses_fitness_suppression_for_approved_strategy(self) -> None:
        signals, stats = allocate_strategy_signals(
            signals=[self._signal(score=90.0)],
            fitness_summaries=[self._fitness_summary()],
            min_checkpoints=2,
            favor_threshold=3.0,
            suppress_threshold=-8.9,
            high_score_override_enabled=True,
            high_score_override_min_score=90.0,
            high_score_override_allowed_strategies={"mean_reversion.snapback"},
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["allocation_status"], "score_to_trade")
        self.assertEqual(stats["high_score_overrides"], 1)
        self.assertEqual(stats["suppressed"], 0)

    def test_score_below_trade_dial_remains_suppressed_by_poor_fitness(self) -> None:
        signals, stats = allocate_strategy_signals(
            signals=[self._signal(score=89.9)],
            fitness_summaries=[self._fitness_summary()],
            min_checkpoints=2,
            favor_threshold=3.0,
            suppress_threshold=-8.9,
            high_score_override_enabled=True,
            high_score_override_min_score=90.0,
            high_score_override_allowed_strategies={"mean_reversion.snapback"},
        )

        self.assertEqual(signals, [])
        self.assertEqual(stats["high_score_overrides"], 0)
        self.assertEqual(stats["suppressed"], 1)


if __name__ == "__main__":
    unittest.main()
