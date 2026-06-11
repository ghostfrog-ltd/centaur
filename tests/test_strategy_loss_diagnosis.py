from __future__ import annotations

from datetime import datetime
from io import StringIO
import contextlib
import sys
import unittest

import main as main_module
from app.framework.reporting.strategy_loss_diagnosis import (
    ALLOWED_EXIT_VERDICTS,
    ALLOWED_SUBSET_EDGE_VERDICTS,
    ALLOWED_VERDICTS,
    ALLOWED_PROFITABILITY_VERDICTS,
    StrategyLossDiagnosisReport,
)


class _FakeLossLedger:
    backend = "sqlite"

    def __init__(self) -> None:
        self.definitions = [
            {
                "variant_id": "baseline",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {
                    "max_movement_pct": -0.18,
                    "min_discovery_score": 4.0,
                    "min_trade_count": 40,
                    "stop_loss_pct": 0.01,
                    "target_multiple": 1.75,
                },
                "generation_reason": "baseline_profile",
            },
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
            },
        ]

    def list_strategy_variant_definitions(self, **_kwargs):
        return list(self.definitions)


class _FakeLossService:
    def __init__(self, outcomes=None) -> None:
        self.outcomes = list(outcomes or [])
        self.last_variant_id = None

    def _resolve_profile(self, **_kwargs):
        return object()

    def _profile_from_variant(self, **_kwargs):
        return object()

    def collect_variant_outcomes(self, **_kwargs):
        self.last_variant_id = str(((_kwargs.get("variant") or {}).get("variant_id", "")) or "")
        return {
            "outcomes": list(self.outcomes),
            "proposal_rows": [],
            "candidates_evaluated": len(self.outcomes),
            "proposals_count": len(self.outcomes),
            "symbols_tested": sorted(
                {
                    str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "")
                    for item in self.outcomes
                    if str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "")
                }
            ),
            "diagnostics": {},
        }


class StrategyLossDiagnosisTests(unittest.TestCase):
    def test_report_runs_read_only_and_calculates_cost_drag(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertEqual(built["data_source"], "regenerated_read_only_baseline")
        self.assertIn("gross_positive_net_negative_count", built["cost_drag"])
        self.assertEqual(
            built["safety_statement"],
            "Research-only loss diagnosis. No paper or live approval has been changed.",
        )
        self.assertIn("profitability_requirement_diagnosis", built)
        self.assertIn("time_exit_and_target_achievement_diagnosis", built)

    def test_report_supports_1hour_timeframe(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            timeframe="1Hour",
        )
        self.assertEqual(built["timeframe"], "1Hour")
        self.assertEqual(
            built["safety_statement"],
            "Research-only loss diagnosis. No paper or live approval has been changed.",
        )

    def test_non_snapback_strategy_uses_generic_verdict_names(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.usage_ledger.definitions = [
            {
                "variant_id": "baseline",
                "base_strategy_id": "crypto_momentum.trend",
                "profile_id": "trend",
                "timeframe": "15Min",
                "params_json": {
                    "min_movement_pct": 0.15,
                    "max_movement_pct": 2.5,
                    "min_discovery_score": 2.5,
                    "min_trade_count": 2,
                    "stop_loss_pct": 0.01,
                    "target_multiple": 2.0,
                },
                "generation_reason": "baseline_profile",
            }
        ]
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="crypto_momentum.trend", profile_id="trend")
        self.assertIn(
            built["verdict"],
            {"cost_problem", "symbol_filter_problem", "entry_quality_problem", "exit_logic_problem", "no_edge_detected", "insufficient_diagnostics"},
        )
        self.assertNotIn("snapback", built["verdict"])

    def test_symbol_best_worst_ranking_works(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertEqual(built["symbol_breakdown"]["best_10"][0]["symbol"], "AAPL")
        self.assertEqual(built["symbol_breakdown"]["worst_10"][0]["symbol"], "TSLA")

    def test_empty_diagnostics_handled_safely(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=[])
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertEqual(built["verdict"], "insufficient_diagnostics")
        self.assertIn("data_adequacy", built)

    def test_empty_diagnostics_include_data_adequacy(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()

        class _AdequacyService(_FakeLossService):
            def collect_variant_outcomes(self, **_kwargs):
                return {
                    "outcomes": [],
                    "proposal_rows": [],
                    "candidates_evaluated": 0,
                    "proposals_count": 0,
                    "symbols_tested": [],
                    "diagnostics": {
                        "data_adequacy": {
                            "dataset_id": "historical_crypto_bars:1Day:5d",
                            "timeframe": "1Day",
                            "days_covered": 2.0,
                            "symbols_covered": ["BTC/USD"],
                            "total_bars": 4,
                            "eligible_signal_count": 0,
                            "generated_proposal_count": 0,
                            "usable_decision_count": 0,
                            "zero_decision_reason": "insufficient_crypto_history",
                        }
                    },
                }

        report.service = _AdequacyService(outcomes=[])
        built = report.build_report(base_strategy_id="crypto_pullback", profile_id="downside_reversal_watch", timeframe="1Day")
        self.assertEqual(built["data_adequacy"]["dataset_id"], "historical_crypto_bars:1Day:5d")
        self.assertEqual(built["data_adequacy"]["zero_decision_reason"], "insufficient_crypto_history")

    def test_specific_variant_can_be_diagnosed(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        service = _FakeLossService(outcomes=_sample_outcomes())
        report.service = service
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            variant_id="variant-240",
        )
        self.assertEqual(built["data_source"], "regenerated_read_only_variant")
        self.assertEqual(built["diagnosed_variant_id"], "variant-240")
        self.assertEqual(service.last_variant_id, "variant-240")
        self.assertEqual(built["diagnosed_params_json"]["holding_window_minutes"], 240)

    def test_verdict_is_allowed_value(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertIn(built["verdict"], ALLOWED_VERDICTS)
        self.assertIn(
            built["profitability_requirement_diagnosis"]["profitability_verdict"],
            ALLOWED_PROFITABILITY_VERDICTS,
        )
        self.assertIn(
            built["time_exit_and_target_achievement_diagnosis"]["exit_verdict"],
            ALLOWED_EXIT_VERDICTS,
        )
        self.assertIn(
            built["subset_edge_diagnosis"]["verdict"],
            ALLOWED_SUBSET_EDGE_VERDICTS,
        )

    def test_profitability_requirement_calculations_match_expected_values(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        profitability = built["profitability_requirement_diagnosis"]
        self.assertAlmostEqual(profitability["required_average_winner_pct"], 0.64, places=6)
        self.assertAlmostEqual(profitability["required_win_rate"], 0.686327, places=6)

    def test_profitability_requirement_handles_divide_by_zero_safely(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(
            outcomes=[
                {
                    "evaluated_at": datetime.now().astimezone().isoformat(),
                    "checkpoint_minutes": 60,
                    "outcome_status": "stop_hit",
                    "gross_realized_return_pct": -0.5,
                    "realized_return_pct": -0.5,
                    "max_adverse_excursion_pct": -0.5,
                    "proposal_context": {"symbol": "AAPL"},
                }
            ]
        )
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        profitability = built["profitability_requirement_diagnosis"]
        self.assertEqual(profitability["required_average_winner_pct"], 0.0)
        self.assertEqual(profitability["required_win_rate"], 1.0)
        self.assertEqual(profitability["profitability_verdict"], "insufficient_data")

    def test_profitability_section_is_rendered(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        rendered = report.render(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertIn("Profitability Requirement Diagnosis", rendered)
        self.assertIn("profitability_verdict=", rendered)

    def test_exit_reason_breakdown_and_exit_sections_are_rendered(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        breakdown = built["time_exit_and_target_achievement_diagnosis"]["exit_reason_breakdown"]
        reasons = {item["exit_reason"] for item in breakdown}
        self.assertIn("time_exit", reasons)
        self.assertIn("target_hit", reasons)
        self.assertIn("stop_hit", reasons)
        rendered = report.render(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertIn("Time Exit and Target Achievement Diagnosis", rendered)
        self.assertIn("exit_verdict=", rendered)

    def test_time_exit_target_and_stop_metrics_are_calculated(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        exit_diag = built["time_exit_and_target_achievement_diagnosis"]
        self.assertEqual(exit_diag["time_exit_quality"]["count"], 2)
        self.assertEqual(exit_diag["target_achievement"]["count"], 2)
        self.assertEqual(exit_diag["stop_damage"]["count"], 1)

    def test_missing_mfe_mae_fields_are_handled_safely(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        outcomes = _sample_outcomes()
        for item in outcomes:
            if item.get("outcome_status") == "time_exit":
                item.pop("max_adverse_excursion_pct", None)
        report.service = _FakeLossService(outcomes=outcomes)
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        time_exit_quality = built["time_exit_and_target_achievement_diagnosis"]["time_exit_quality"]
        self.assertIsNone(time_exit_quality["average_max_adverse_excursion_pct"])

    def test_symbol_breakdown_includes_extended_metrics(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        best = built["symbol_breakdown"]["best_10"][0]
        self.assertIn("average_winner", best)
        self.assertIn("average_loser", best)
        self.assertIn("target_hit_count", best)
        self.assertIn("stop_hit_count", best)
        self.assertIn("time_exit_count", best)

    def test_bucket_breakdown_works(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            variant_id="variant-240",
        )
        buckets = built["bucket_breakdown"]
        self.assertTrue(buckets["by_month"])
        self.assertTrue(buckets["by_trade_count_bucket"])
        self.assertTrue(buckets["by_pullback_depth_bucket"])
        self.assertTrue(buckets["by_discovery_score_bucket"])
        self.assertTrue(buckets["by_rank_bucket"])

    def test_missing_bucket_fields_are_handled_safely(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        outcomes = [
            {
                "evaluated_at": datetime.now().astimezone().isoformat(),
                "checkpoint_minutes": 240,
                "outcome_status": "time_exit",
                "gross_realized_return_pct": 0.12,
                "realized_return_pct": -0.11,
                "proposal_context": {"symbol": "AAPL"},
            }
        ]
        report.service = _FakeLossService(outcomes=outcomes)
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            variant_id="variant-240",
        )
        self.assertEqual(built["bucket_breakdown"]["by_trade_count_bucket"], [])
        self.assertEqual(built["bucket_breakdown"]["by_discovery_score_bucket"], [])

    def test_report_remains_read_only_and_cannot_produce_paper_or_live_status(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            variant_id="variant-240",
        )
        serialized = str(built)
        self.assertNotIn("paper_candidate_requires_manual_approval", serialized)
        self.assertNotIn("live_approved", serialized)
        self.assertNotIn("paper_approved", serialized)
        self.assertEqual(
            built["safety_statement"],
            "Research-only loss diagnosis. No paper or live approval has been changed.",
        )

    def test_thresholds_remain_unchanged(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            variant_id="variant-240",
        )
        self.assertEqual(built["baseline_params_json"]["stop_loss_pct"], 0.01)
        self.assertEqual(built["baseline_params_json"]["target_multiple"], 1.75)

    def test_holding_window_diagnostic_is_available_when_checkpoint_windows_exist(self) -> None:
        report = StrategyLossDiagnosisReport.__new__(StrategyLossDiagnosisReport)
        report.config = object()
        report.usage_ledger = _FakeLossLedger()
        report.service = _FakeLossService(outcomes=_sample_outcomes())
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        holding = built["time_exit_and_target_achievement_diagnosis"]["holding_window_sensitivity"]
        self.assertTrue(holding["available"])
        self.assertTrue(holding["windows"])

    def test_cli_renders_loss_diagnosis_report(self) -> None:
        original_reporter = main_module.StrategyLossDiagnosisReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--strategy-loss-diagnosis",
            "--base-strategy",
            "mean_reversion.snapback",
            "--variant-id",
            "variant-240",
        ]

        class _Report:
            def render(self, **_kwargs) -> str:
                assert _kwargs.get("variant_id") == "variant-240"
                return (
                    "Strategy Loss Diagnosis\n"
                    "Research-only loss diagnosis. No paper or live approval has been changed."
                )

        main_module.StrategyLossDiagnosisReport = _Report
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.StrategyLossDiagnosisReport = original_reporter
            sys.argv = original_argv

        self.assertIn("Strategy Loss Diagnosis", stdout.getvalue())
        self.assertIn(
            "Research-only loss diagnosis. No paper or live approval has been changed.",
            stdout.getvalue(),
        )


def _sample_outcomes() -> list[dict[str, object]]:
    now = datetime(2026, 5, 1, 10, 0, 0).astimezone().isoformat()
    return [
        {
            "evaluated_at": now,
            "checkpoint_minutes": 240,
            "outcome_status": "target_hit",
            "gross_realized_return_pct": 0.45,
            "realized_return_pct": 0.10,
            "max_adverse_excursion_pct": -0.30,
            "proposal_context": {
                "symbol": "AAPL",
                "discovery_score": 5.2,
                "movement_pct": -0.31,
                "trade_count": 120,
                "signal_rank": 1,
            },
        },
        {
            "evaluated_at": datetime(2026, 5, 2, 10, 0, 0).astimezone().isoformat(),
            "checkpoint_minutes": 240,
            "outcome_status": "time_exit",
            "gross_realized_return_pct": 0.08,
            "realized_return_pct": -0.22,
            "max_adverse_excursion_pct": -0.70,
            "proposal_context": {
                "symbol": "TSLA",
                "discovery_score": 4.1,
                "movement_pct": -0.19,
                "trade_count": 42,
                "signal_rank": 2,
            },
        },
        {
            "evaluated_at": datetime(2026, 6, 3, 10, 0, 0).astimezone().isoformat(),
            "checkpoint_minutes": 240,
            "outcome_status": "stop_hit",
            "gross_realized_return_pct": -0.55,
            "realized_return_pct": -0.88,
            "max_adverse_excursion_pct": -1.20,
            "proposal_context": {
                "symbol": "TSLA",
                "discovery_score": 3.9,
                "movement_pct": -0.17,
                "trade_count": 35,
                "signal_rank": 2,
            },
        },
        {
            "evaluated_at": datetime(2026, 6, 4, 10, 0, 0).astimezone().isoformat(),
            "checkpoint_minutes": 240,
            "outcome_status": "target_hit",
            "gross_realized_return_pct": 0.62,
            "realized_return_pct": 0.29,
            "max_adverse_excursion_pct": -0.24,
            "proposal_context": {
                "symbol": "AAPL",
                "discovery_score": 5.4,
                "movement_pct": -0.33,
                "trade_count": 130,
                "signal_rank": 1,
            },
        },
        {
            "evaluated_at": datetime(2026, 6, 5, 10, 0, 0).astimezone().isoformat(),
            "checkpoint_minutes": 240,
            "outcome_status": "time_exit",
            "gross_realized_return_pct": 0.03,
            "realized_return_pct": -0.18,
            "max_adverse_excursion_pct": -0.61,
            "proposal_context": {
                "symbol": "NVDA",
                "discovery_score": 4.7,
                "movement_pct": -0.23,
                "trade_count": 75,
                "signal_rank": 2,
            },
        },
    ]


if __name__ == "__main__":
    unittest.main()
