from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import contextlib
import sys
import unittest

import main as main_module
from app.framework.reporting.symbol_subset_stability import (
    ALLOWED_STABILITY_VERDICTS,
    SAFETY_STATEMENT,
    SymbolSubsetStabilityReport,
    normalize_symbol_subset_verdict,
)


class _FakeLedger:
    backend = "sqlite"

    def __init__(self):
        self.persisted = []

    def list_strategy_variant_definitions(self, **_kwargs):
        return [
            {
                "variant_id": "variant-240",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {
                    "holding_window_minutes": 240,
                    "max_movement_pct": -0.18,
                    "min_discovery_score": 4.0,
                    "min_trade_count": 40,
                    "stop_loss_pct": 0.01,
                    "target_multiple": 1.75,
                },
                "generation_reason": "holding_window_240",
            }
        ]

    def summarize_historical_bar_coverage(self, **_kwargs):
        return [
            {
                "earliest_bar_timestamp": datetime(2025, 6, 9, 14, 30).astimezone(),
                "latest_bar_timestamp": datetime(2026, 6, 8, 20, 45).astimezone(),
            }
        ]

    def list_strategy_variant_evaluations(self, **_kwargs):
        return []

    def record_strategy_variant_evaluation(self, **kwargs):
        self.persisted.append(dict(kwargs))
        return dict(kwargs)


class _FakeService:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def _resolve_profile(self, **_kwargs):
        return object()

    def _profile_from_variant(self, **_kwargs):
        return object()

    def collect_variant_outcomes(self, **_kwargs):
        return {"outcomes": list(self.outcomes)}

    def _replay_window_days_delta(self):
        return timedelta(days=5)


class _FakeLossReporter:
    def __init__(self, verdict="symbol_filter_promising"):
        self.verdict = verdict

    def build_report(self, **_kwargs):
        return {
            "verdict": "snapback_cost_problem",
            "profitability_requirement_diagnosis": {"profitability_verdict": "target_exit_logic_problem"},
            "subset_edge_diagnosis": {"verdict": self.verdict},
        }


class SymbolSubsetStabilityTests(unittest.TestCase):
    def test_report_runs_read_only_and_has_safety_statement(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertEqual(built["safety_statement"], SAFETY_STATEMENT)
        self.assertEqual(built["next_recommended_command"], ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min --variant-id variant-240 --symbol WDC --wider-period")
        self.assertTrue(built["persistence"]["persisted_separately"])

    def test_selected_symbol_metrics_are_calculated(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        summary = built["selected_symbol_summary"]
        self.assertEqual(summary["sample_size"], 21)
        self.assertGreater(summary["net_return_after_costs"], 0.0)
        self.assertGreater(summary["gross_return_before_costs"], 0.0)
        self.assertIn("profit_factor", summary)

    def test_period_breakdown_works(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertTrue(built["period_breakdown"]["by_month"])
        self.assertTrue(built["period_breakdown"]["by_quarter"])
        self.assertTrue(built["period_breakdown"]["by_week_or_chunk"])

    def test_sparse_symbol_data_is_handled_safely(self) -> None:
        report = _report_with(_sample_outcomes()[:2])
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertIn(
            built["stability_verdict"],
            {"symbol_promising_but_insufficient", "symbol_not_promising"},
        )

    def test_missing_cohort_metadata_is_handled_safely(self) -> None:
        outcomes = []
        for item in _sample_outcomes():
            clone = dict(item)
            clone["proposal_context"] = {"symbol": "WDC"}
            outcomes.append(clone)
        report = _report_with(outcomes)
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertEqual(built["cohort_comparison"]["availability"], "unavailable")

    def test_verdict_is_allowed_value(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertIn(built["stability_verdict"], ALLOWED_STABILITY_VERDICTS)
        self.assertEqual(normalize_symbol_subset_verdict("symbol_unstable_across_periods"), "symbol_unstable")

    def test_wdc_like_sample_does_not_auto_approve_filter(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertNotEqual(built["stability_verdict"], "symbol_promising_and_stable")

    def test_wider_period_comparison_and_persistence_are_produced(self) -> None:
        report = _report_with(_sample_outcomes() + _extra_wide_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
            wider_period=True,
        )
        self.assertIn("narrow_vs_wide_comparison", built)
        self.assertEqual(built["narrow_vs_wide_comparison"]["narrow_sample_size"], 21)
        self.assertEqual(built["selected_symbol_summary"]["sample_size"], 31)
        self.assertTrue(built["persistence"]["persisted_separately"])
        self.assertEqual(report.usage_ledger.persisted[0]["symbols_tested"], ["WDC"])

    def test_no_paper_live_status_is_produced_and_thresholds_unchanged(self) -> None:
        report = _report_with(_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        joined = str(built).lower()
        self.assertNotIn("paper_approved", joined)
        self.assertNotIn("live_candidate", joined)
        self.assertNotIn("lower_threshold", joined)
        self.assertEqual(built["next_required_action"], "run_wider_symbol_replay")

    def test_cli_command_renders_report(self) -> None:
        original_reporter = main_module.SymbolSubsetStabilityReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--symbol-subset-stability-report",
            "--base-strategy",
            "mean_reversion.snapback",
            "--variant-id",
            "variant-240",
            "--symbol",
            "WDC",
        ]

        class _Reporter:
            def render(self, **kwargs):
                return f"report-for-{kwargs['symbol']}"

        main_module.SymbolSubsetStabilityReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.SymbolSubsetStabilityReport = original_reporter
            sys.argv = original_argv
        self.assertIn("report-for-WDC", stdout.getvalue())


def _report_with(outcomes):
    report = SymbolSubsetStabilityReport.__new__(SymbolSubsetStabilityReport)
    report.config = object()
    report.usage_ledger = _FakeLedger()
    report.service = _FakeService(outcomes)
    report.loss_reporter = _FakeLossReporter()
    return report


def _sample_outcomes():
    base = datetime(2026, 4, 1, 12, 0).astimezone()
    outcomes = []
    for idx in range(21):
        symbol = "WDC"
        outcome_status = "target_hit" if idx < 11 else "stop_hit" if idx < 19 else "time_exit"
        realized = 0.9 if outcome_status == "target_hit" else -0.7 if outcome_status == "stop_hit" else 0.2
        gross = realized + (0.12 if realized > 0 else 0.05)
        outcomes.append(
            {
                "evaluated_at": (base + timedelta(days=idx * 7)).isoformat(),
                "outcome_status": outcome_status,
                "realized_return_pct": realized,
                "gross_realized_return_pct": gross,
                "max_adverse_excursion_pct": -0.8 if outcome_status != "time_exit" else -0.2,
                "proposal_context": {
                    "symbol": symbol,
                    "trade_count": 80 + (idx % 5),
                    "movement_pct": -0.21 + ((idx % 3) * 0.01),
                },
            }
        )
    for idx in range(8):
        outcomes.append(
            {
                "evaluated_at": (base + timedelta(days=idx * 7)).isoformat(),
                "outcome_status": "stop_hit" if idx % 2 else "target_hit",
                "realized_return_pct": -0.2 if idx % 2 else 0.1,
                "gross_realized_return_pct": -0.1 if idx % 2 else 0.2,
                "max_adverse_excursion_pct": -0.4,
                "proposal_context": {
                    "symbol": "STX",
                    "trade_count": 82,
                    "movement_pct": -0.22,
                },
            }
        )
    return outcomes


def _extra_wide_outcomes():
    base = datetime(2025, 8, 1, 12, 0).astimezone()
    return [
        {
            "evaluated_at": (base + timedelta(days=9 * idx)).isoformat(),
            "outcome_status": "target_hit" if idx % 2 == 0 else "stop_hit",
            "realized_return_pct": 0.4 if idx % 2 == 0 else -0.2,
            "gross_realized_return_pct": 0.48 if idx % 2 == 0 else -0.15,
            "max_adverse_excursion_pct": -0.3,
            "proposal_context": {
                "symbol": "WDC",
                "trade_count": 84,
                "movement_pct": -0.2,
            },
        }
        for idx in range(10)
    ]


if __name__ == "__main__":
    unittest.main()
