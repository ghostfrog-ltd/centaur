from __future__ import annotations

import contextlib
from io import StringIO
import sys
import unittest

import main as main_module
from app.framework.reporting.bounded_dip_rebound_precompute import (
    BoundedDipReboundPrecomputeReport,
    PRECOMPUTE_COMMAND,
    SAFETY_STATEMENT,
)


class _StubLedger:
    def __init__(self) -> None:
        self.recorded: list[dict[str, object]] = []

    def record_strategy_variant_evaluation(self, **kwargs):
        self.recorded.append(dict(kwargs))
        return dict(kwargs)


class _StubVariantService:
    def __init__(self, *, sample_size: int = 7, runtime_blocker: str = "") -> None:
        self.calls: list[dict[str, object]] = []
        self.sample_size = sample_size
        self.runtime_blocker = runtime_blocker

    def run_research(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "baseline_metrics": {
                "sample_size": self.sample_size,
                "net_return_after_costs": 0.123,
                "win_rate": 0.571429,
                "drawdown": 0.22,
                "symbols_tested": ["BTCUSD", "ETHUSD"],
                "raw": {
                    "diagnostics": {
                        "data_adequacy": {
                            "total_bars": 240,
                            "zero_decision_reason": self.runtime_blocker,
                        }
                    }
                },
            }
        }


class BoundedDipReboundPrecomputeTests(unittest.TestCase):
    def test_report_is_research_only_and_persists_freshness_evidence(self) -> None:
        ledger = _StubLedger()
        service = _StubVariantService()
        report = BoundedDipReboundPrecomputeReport(
            config=object(),
            usage_ledger=ledger,
            variant_service=service,
        ).build_report()

        self.assertEqual(report["runtime_status"], "precomputed")
        self.assertEqual(report["cache_status"], "fresh")
        self.assertEqual(report["paper_trades_created"], "no")
        self.assertEqual(report["live_changed"], "no")
        self.assertEqual(report["thresholds_changed"], "no")
        self.assertEqual(report["promotion_policy_changed"], "no")
        self.assertEqual(report["next_recommended_command"], ".venv-mac/bin/python main.py --strategy-portfolio-research-planner")
        self.assertEqual(len(ledger.recorded), 1)
        self.assertEqual(ledger.recorded[0]["raw"]["report_type"], "replay_dataset_preparation")
        self.assertEqual(ledger.recorded[0]["raw"]["prep_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(ledger.recorded[0]["notes"], SAFETY_STATEMENT)
        self.assertTrue(service.calls[0]["bounded_diagnosis"])

    def test_failed_precompute_emits_runtime_blocker_clearly(self) -> None:
        report = BoundedDipReboundPrecomputeReport(
            config=object(),
            usage_ledger=_StubLedger(),
            variant_service=_StubVariantService(sample_size=0, runtime_blocker="historical_bar_read_timeout"),
        ).build_report()

        self.assertEqual(report["runtime_status"], "runtime_blocked")
        self.assertEqual(report["runtime_blocker"], "historical_bar_read_timeout")
        self.assertEqual(report["next_recommended_command"], PRECOMPUTE_COMMAND)

    def test_cli_command_outputs_json(self) -> None:
        original_reporter = main_module.BoundedDipReboundPrecomputeReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--precompute-bounded-dip-rebound-15min-outcomes", "--json"]

        class _Reporter:
            def build_report(self):
                return {"runtime_status": "precomputed", "paper_trades_created": "no"}

        main_module.BoundedDipReboundPrecomputeReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.BoundedDipReboundPrecomputeReport = original_reporter
            sys.argv = original_argv

        text = stdout.getvalue()
        self.assertIn('"runtime_status": "precomputed"', text)
        self.assertIn('"paper_trades_created": "no"', text)
