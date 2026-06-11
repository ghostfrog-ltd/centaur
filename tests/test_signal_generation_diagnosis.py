from __future__ import annotations

import contextlib
from io import StringIO
import sys
import unittest

import main as main_module
from app.framework.reporting.signal_generation_diagnosis import (
    SAFETY_STATEMENT,
    SignalGenerationDiagnosisReport,
)


class _StubPlanner:
    def __init__(self, report):
        self.report = dict(report)

    def build_report(self):
        return dict(self.report)


class _StubLedger:
    def __init__(self):
        self.persisted = []
        self.paper_trade_orders_recorded = 0
        self.live_trade_orders_recorded = 0

    def record_strategy_variant_evaluation(self, **kwargs):
        self.persisted.append(dict(kwargs))
        return dict(kwargs)


class SignalGenerationDiagnosisTests(unittest.TestCase):
    def test_build_report_classifies_no_usable_signals_and_proposes_research_only_follow_up(self) -> None:
        ledger = _StubLedger()
        report = SignalGenerationDiagnosisReport(
            usage_ledger=ledger,
            planner=_StubPlanner(
                {
                    "next_portfolio_action": "adjust_signal_generation_research_only",
                    "proposed_next_command": ".venv-mac/bin/python main.py --signal-generation-diagnosis --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "crypto_momentum.trend",
                            "profile_id": "trend",
                            "timeframe": "15Min",
                            "research_status": "insufficient_data",
                            "latest_sample_size": 0,
                            "latest_net_return_after_costs": 0.0,
                            "zero_decision_reason": "",
                            "paper_candidate_path": "insufficient_data",
                            "latest_replay_preparation": {
                                "prep_status": "replay_prepared_but_no_signals",
                                "blocker_reason": "bars exist but no_usable_signals",
                            },
                            "audit_report": {},
                        }
                    ],
                }
            ),
        )

        built = report.build_report(
            base_strategy_id="crypto_momentum.trend",
            profile_id="trend",
            timeframe="15Min",
        )

        self.assertEqual(built["paper_trades_created"], "no")
        self.assertEqual(built["live_changed"], "no")
        self.assertEqual(built["thresholds_changed"], "no")
        self.assertEqual(built["promotion_policy_changed"], "no")
        self.assertEqual(built["strategy_classifications"][0]["blocker"], "no_usable_signals")
        self.assertIn("--run-strategy-variant-research", built["next_recommended_command"])
        self.assertEqual(ledger.paper_trade_orders_recorded, 0)
        self.assertEqual(ledger.live_trade_orders_recorded, 0)
        self.assertEqual(ledger.persisted[0]["raw"]["report_type"], "signal_generation_diagnosis")

    def test_cli_renders_signal_generation_diagnosis(self) -> None:
        original_reporter = main_module.SignalGenerationDiagnosisReport

        class _Reporter:
            def render(self, **_kwargs):
                return "Signal Generation Diagnosis\n" + SAFETY_STATEMENT

        main_module.SignalGenerationDiagnosisReport = _Reporter
        argv = sys.argv
        stdout = StringIO()
        try:
            sys.argv = ["main.py", "--signal-generation-diagnosis"]
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            sys.argv = argv
            main_module.SignalGenerationDiagnosisReport = original_reporter

        self.assertIn("Signal Generation Diagnosis", stdout.getvalue())
        self.assertIn(SAFETY_STATEMENT, stdout.getvalue())

    def test_range_breakout_follow_up_prefers_bounded_research_command(self) -> None:
        ledger = _StubLedger()
        report = SignalGenerationDiagnosisReport(
            usage_ledger=ledger,
            planner=_StubPlanner(
                {
                    "next_portfolio_action": "adjust_signal_generation_research_only",
                    "proposed_next_command": ".venv-mac/bin/python main.py --signal-generation-diagnosis --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "crypto_research.range_breakout",
                            "profile_id": "range_breakout",
                            "timeframe": "15Min",
                            "research_status": "insufficient_data",
                            "latest_sample_size": 0,
                            "latest_net_return_after_costs": 0.0,
                            "zero_decision_reason": "",
                            "paper_candidate_path": "insufficient_data",
                            "latest_replay_preparation": {
                                "prep_status": "replay_prepared_but_no_signals",
                                "blocker_reason": "bars exist but no_usable_signals",
                            },
                            "audit_report": {},
                        }
                    ],
                }
            ),
        )

        built = report.build_report(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="15Min",
        )

        self.assertEqual(built["strategy_classifications"][0]["blocker"], "no_usable_signals")
        self.assertEqual(
            built["proposed_research_adjustments"][0]["proposed_research_adjustment"],
            "run bounded strategy variant research",
        )
        self.assertEqual(
            built["next_recommended_command"],
            ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
        )


if __name__ == "__main__":
    unittest.main()
