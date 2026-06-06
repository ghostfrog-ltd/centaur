from __future__ import annotations

import importlib
import unittest
from datetime import datetime
from types import SimpleNamespace


class StrategySignalScoreToTradeThresholdTests(unittest.TestCase):
    def _context(self, *, environment: str) -> SimpleNamespace:
        return SimpleNamespace(
            tick_id="threshold-test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                centaur_environment=environment,
                strategy_allocation_min_checkpoints=2,
                strategy_allocation_favor_threshold=3.0,
                strategy_allocation_suppress_threshold=-8.9,
                paper_execution_enabled=True,
                paper_execution_kill_switch=False,
                live_execution_enabled=True,
                live_execution_kill_switch=False,
                paper_min_signal_score_to_trade=91.0,
                live_min_signal_score_to_trade=97.0,
                paper_execution_high_score_override_fitness_margin=0.25,
                live_execution_high_score_override_fitness_margin=0.75,
                paper_execution_allowed_strategies=("paper.strategy",),
                live_execution_allowed_strategies=("live.strategy",),
            ),
            state={
                "context_enrichment": {"candidates": [{"symbol": "AAPL"}]},
                "market_gate": {},
                "alpaca_account": {"summary": {"equity": 100000.0}},
                "strategy_fitness": {"summaries": []},
            },
            usage_ledger=SimpleNamespace(
                record_strategy_candidate_signals=lambda **_: None,
            ),
        )

    def test_paper_and_live_disable_score_override_even_when_knobs_exist(self) -> None:
        module = importlib.import_module(
            "app.heartbeat.steps.26_strategy_signals.implementation.main"
        )
        original_evaluate = module.evaluate_strategies
        original_allocate = module.allocate_strategy_signals
        original_advisor = module.ThresholdAdvisor
        original_thresholds = module._paper_allocation_suppress_thresholds
        score_to_trade_calls: list[dict[str, object]] = []

        class Signal:
            def as_dict(self, *, tick_id: str) -> dict[str, object]:
                return {
                    "tick_id": tick_id,
                    "strategy_id": "mean_reversion.snapback",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "holding_window_code": "1h",
                    "signal_score": 92.0,
                }

        class Advisor:
            def __init__(self, **_: object) -> None:
                pass

            def effective_threshold(self, **_: object) -> dict[str, float]:
                return {"effective_threshold": -8.9}

        def evaluate_strategies(**_: object) -> SimpleNamespace:
            return SimpleNamespace(
                family_count=1,
                profile_count=1,
                signals=[Signal()],
                rejection_summary={},
            )

        def allocate_strategy_signals(**kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
            if "high_score_override_min_score" in kwargs:
                score_to_trade_calls.append(
                    {
                        "enabled": kwargs.get("high_score_override_enabled"),
                        "min_score": kwargs.get("high_score_override_min_score"),
                        "fitness_margin": kwargs.get(
                            "high_score_override_fitness_margin"
                        ),
                        "allowed_strategies": kwargs.get(
                            "high_score_override_allowed_strategies"
                        ),
                    }
                )
            return (
                list(kwargs["signals"]),
                {
                    "suppressed": 0,
                    "high_score_overrides": 0,
                    "favored": 0,
                    "raw_signals": [],
                    "suppressed_signals": [],
                },
            )

        try:
            module.evaluate_strategies = evaluate_strategies
            module.allocate_strategy_signals = allocate_strategy_signals
            module.ThresholdAdvisor = Advisor
            module._paper_allocation_suppress_thresholds = lambda *_, **__: {}

            module.run_implementation(self._context(environment="paper"))
            module.run_implementation(self._context(environment="live"))
        finally:
            module.evaluate_strategies = original_evaluate
            module.allocate_strategy_signals = original_allocate
            module.ThresholdAdvisor = original_advisor
            module._paper_allocation_suppress_thresholds = original_thresholds

        self.assertEqual(
            score_to_trade_calls,
            [
                {
                    "enabled": False,
                    "min_score": 91.0,
                    "fitness_margin": 0.25,
                    "allowed_strategies": set(),
                },
                {
                    "enabled": False,
                    "min_score": 97.0,
                    "fitness_margin": 0.75,
                    "allowed_strategies": set(),
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
