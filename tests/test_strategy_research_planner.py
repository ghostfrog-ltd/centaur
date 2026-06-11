from __future__ import annotations

from io import StringIO
import contextlib
import sys
import unittest

import main as main_module
from app.framework.reporting.strategy_research_planner import (
    ALLOWED_EXPERIMENT_TYPES,
    SAFETY_STATEMENT,
    StrategyResearchPlannerReport,
)


class _StubVariantReporter:
    def __init__(self, report):
        self.report = report
        self.service = _StubResearchService()

    def build_report(self, **_kwargs):
        return dict(self.report)


class _StubDiagnosticsReporter:
    def __init__(self, report):
        self.report = report

    def build_report(self, **_kwargs):
        return dict(self.report)


class _StubLossReporter:
    def __init__(self, baseline_report, variant_reports=None):
        self.baseline_report = baseline_report
        self.variant_reports = dict(variant_reports or {})
        self.render_calls = []

    def build_report(self, **kwargs):
        variant_id = kwargs.get("variant_id")
        if variant_id:
            return dict(self.variant_reports.get(variant_id, self.baseline_report))
        return dict(self.baseline_report)

    def render(self, **kwargs):
        self.render_calls.append(dict(kwargs))
        report = self.build_report(**kwargs)
        return f"rendered_variant={report.get('diagnosed_variant_id', '-')}"


class _StubResearchService:
    def __init__(self):
        self.calls = []

    def run_research(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "variants_generated": 3,
            "evaluations": [{"variant_id": "baseline"}, {"variant_id": "variant-240"}],
        }


class _StubSymbolStabilityReporter:
    def __init__(self):
        self.calls = []

    def render(self, **kwargs):
        self.calls.append(dict(kwargs))
        return "symbol-stability-rendered"


class StrategyResearchPlannerTests(unittest.TestCase):
    def test_selects_holding_window_variants_when_exit_verdict_says_too_short_and_none_exist(self) -> None:
        planner = _planner(
            variant_report=_variant_report([]),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=20),
        )
        built = planner.build_report()
        self.assertEqual(built["selected_experiment_type"], "test_holding_window_variants")

    def test_selects_symbol_regime_subset_when_holding_window_variant_beats_baseline_but_remains_negative(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [
                    _variant(
                        "variant-240",
                        generation_reason="holding_window_240",
                        params_json={"holding_window_minutes": 240},
                        beats_baseline=True,
                        beats_thresholds=False,
                        net_return_after_costs=-0.18,
                        win_rate=0.54,
                    )
                ]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(sample_size=40, subset_verdict="insufficient_subset_data", diagnosed_variant_id="variant-240")},
        )
        built = planner.build_report()
        self.assertEqual(built["selected_experiment_type"], "diagnose_symbol_regime_subset")
        self.assertEqual(built["selected_variant_id"], "variant-240")
        self.assertIn("--strategy-loss-diagnosis", built["proposed_next_command"])

    def test_selects_validate_symbol_subset_stability_when_symbol_filter_promising_exists(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [
                    _variant(
                        "variant-240",
                        generation_reason="holding_window_240",
                        params_json={"holding_window_minutes": 240},
                        beats_baseline=True,
                        beats_thresholds=False,
                        net_return_after_costs=-0.18,
                        win_rate=0.54,
                    )
                ]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(
                sample_size=40,
                subset_verdict="symbol_filter_promising",
                diagnosed_variant_id="variant-240",
                symbol_rows=[
                    {
                        "symbol": "WDC",
                        "sample_size": 21,
                        "net_return_after_costs": 0.194383,
                        "win_rate": 0.571429,
                        "target_hit_count": 11,
                        "stop_hit_count": 8,
                        "time_exit_count": 2,
                    }
                ],
            )},
        )
        built = planner.build_report()
        self.assertEqual(built["selected_experiment_type"], "validate_symbol_subset_stability")
        self.assertEqual(built["candidate_symbols"][0]["symbol"], "WDC")
        self.assertTrue(built["execution_available"])
        self.assertIn("--symbol-subset-stability-report", built["proposed_next_command"])

    def test_planner_includes_candidate_symbol_evidence(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-240", generation_reason="holding_window_240", params_json={"holding_window_minutes": 240}, beats_baseline=True, net_return_after_costs=-0.18)]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(
                sample_size=40,
                subset_verdict="symbol_filter_promising",
                diagnosed_variant_id="variant-240",
                symbol_rows=[
                    {
                        "symbol": "WDC",
                        "sample_size": 21,
                        "net_return_after_costs": 0.194383,
                        "win_rate": 0.571429,
                        "target_hit_count": 11,
                        "stop_hit_count": 8,
                        "time_exit_count": 2,
                    }
                ],
            )},
        )
        built = planner.build_report()
        candidate = built["candidate_symbols"][0]
        self.assertEqual(candidate["symbol"], "WDC")
        self.assertEqual(candidate["sample_size"], 21)
        self.assertAlmostEqual(candidate["net_return_after_costs"], 0.194383)
        self.assertAlmostEqual(candidate["win_rate"], 0.571429)

    def test_selects_retire_or_deprioritise_when_no_variant_improves_baseline(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [
                    _variant("variant-a", beats_baseline=False, net_return_after_costs=-0.6),
                    _variant("variant-b", beats_baseline=False, net_return_after_costs=-0.4),
                ]
            ),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(
                loss_verdict="snapback_no_edge_detected",
                subset_verdict="no_clear_subset_edge",
                sample_size=40,
            ),
        )
        built = planner.build_report()
        self.assertEqual(built["selected_experiment_type"], "retire_or_deprioritise_strategy")

    def test_never_selects_live_candidate(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-240", beats_baseline=True, beats_thresholds=True, net_return_after_costs=1.2)]
            ),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(sample_size=40),
        )
        built = planner.build_report()
        self.assertIn(built["selected_experiment_type"], ALLOWED_EXPERIMENT_TYPES)
        self.assertNotEqual(built["selected_experiment_type"], "live_candidate")

    def test_never_auto_approves_paper(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-240", beats_baseline=True, beats_thresholds=True, net_return_after_costs=1.2)]
            ),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(sample_size=40),
        )
        built = planner.build_report(execute_next_research_step=True)
        self.assertNotIn("approve-paper", built["proposed_next_command"])
        self.assertEqual(built["safety_statement"], SAFETY_STATEMENT)

    def test_does_not_lower_thresholds(self) -> None:
        planner = _planner(
            variant_report=_variant_report([]),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(loss_verdict="snapback_cost_problem", sample_size=30),
        )
        built = planner.build_report()
        self.assertNotIn("threshold", built["proposed_next_command"].lower())
        self.assertNotIn("lower", built["reason"].lower())

    def test_generic_non_snapback_verdicts_do_not_require_snapback_names(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-a", beats_baseline=False, net_return_after_costs=-0.6)]
            ),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(
                loss_verdict="no_edge_detected",
                subset_verdict="no_clear_subset_edge",
                sample_size=40,
            ),
        )
        built = planner.build_report(
            base_strategy_id="crypto_momentum.trend",
            profile_id="trend",
            timeframe="15Min",
        )
        self.assertEqual(built["selected_experiment_type"], "retire_or_deprioritise_strategy")

    def test_report_includes_safety_statement(self) -> None:
        planner = _planner(
            variant_report=_variant_report([]),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(sample_size=30),
        )
        rendered = planner.render()
        self.assertIn(SAFETY_STATEMENT, rendered)

    def test_execute_flag_only_runs_research_only_steps(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [
                    _variant(
                        "variant-240",
                        generation_reason="holding_window_240",
                        params_json={"holding_window_minutes": 240},
                        beats_baseline=True,
                        beats_thresholds=False,
                        net_return_after_costs=-0.18,
                    )
                ]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(sample_size=40, diagnosed_variant_id="variant-240")},
        )
        built = planner.build_report(execute_next_research_step=True)
        self.assertEqual(built["execution"]["status"], "executed_research_only")
        self.assertIn("--strategy-loss-diagnosis", built["execution"]["executed_command"])

    def test_marks_execution_available_when_command_exists(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-240", generation_reason="holding_window_240", params_json={"holding_window_minutes": 240}, beats_baseline=True, net_return_after_costs=-0.18)]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(
                sample_size=40,
                subset_verdict="symbol_filter_promising",
                diagnosed_variant_id="variant-240",
                symbol_rows=[{"symbol": "WDC", "sample_size": 21, "net_return_after_costs": 0.194383, "win_rate": 0.571429}],
            )},
        )
        built = planner.build_report()
        self.assertTrue(built["execution_available"])

    def test_execute_flag_safely_runs_symbol_stability_report(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-240", generation_reason="holding_window_240", params_json={"holding_window_minutes": 240}, beats_baseline=True, net_return_after_costs=-0.18)]
            ),
            diagnostics_rows=[
                {"variant_id": "variant-240", "generation_reason": "holding_window_240", "params_json": {"holding_window_minutes": 240}}
            ],
            baseline_loss_report=_loss_report(exit_verdict="holding_window_too_short", sample_size=40),
            variant_loss_reports={"variant-240": _loss_report(
                sample_size=40,
                subset_verdict="symbol_filter_promising",
                diagnosed_variant_id="variant-240",
                symbol_rows=[{"symbol": "WDC", "sample_size": 21, "net_return_after_costs": 0.194383, "win_rate": 0.571429}],
            )},
        )
        built = planner.build_report(execute_next_research_step=True)
        self.assertEqual(built["execution"]["status"], "executed_research_only")
        self.assertIn("--symbol-subset-stability-report", built["execution"]["executed_command"])
        self.assertEqual(built["execution"]["output_preview"], "symbol-stability-rendered")

    def test_target_exit_recommendation_executes_bounded_research_only_variants(self) -> None:
        planner = _planner(
            variant_report=_variant_report(
                [_variant("variant-target", beats_baseline=False, net_return_after_costs=-0.3)]
            ),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(
                loss_verdict="symbol_filter_problem",
                profitability_verdict="target_exit_logic_problem",
                exit_verdict="target_too_far",
                sample_size=3,
            ),
        )
        built = planner.build_report(
            base_strategy_id="crypto_research.dip_rebound",
            profile_id="dip_rebound",
            timeframe="15Min",
            execute_next_research_step=True,
        )
        self.assertEqual(built["selected_experiment_type"], "test_target_multiple_variants")
        self.assertTrue(built["execution_available"])
        self.assertIn("--run-strategy-variant-research", built["proposed_next_command"])
        self.assertEqual(built["execution"]["status"], "executed_research_only")
        self.assertEqual(
            planner.variant_reporter.service.calls,
            [
                {
                    "base_strategy_id": "crypto_research.dip_rebound",
                    "profile_id": "dip_rebound",
                    "timeframe": "15Min",
                    "created_by": "strategy_research_planner",
                    "bounded_diagnosis": True,
                }
            ],
        )

    def test_no_paper_or_live_status_is_produced(self) -> None:
        planner = _planner(
            variant_report=_variant_report([]),
            diagnostics_rows=[],
            baseline_loss_report=_loss_report(sample_size=30),
        )
        built = planner.build_report()
        joined = " ".join(
            [
                built["selected_experiment_type"],
                built["reason"],
                built["proposed_next_command"],
                str(built["execution"]),
            ]
        ).lower()
        self.assertNotIn("paper_approved", joined)
        self.assertNotIn("live_candidate", joined)

    def test_cli_command_invokes_planner(self) -> None:
        original_reporter = main_module.StrategyResearchPlannerReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--strategy-research-planner",
            "--base-strategy",
            "mean_reversion.snapback",
        ]
        captured = []

        class _Reporter:
            def render(self, **kwargs):
                captured.append(dict(kwargs))
                return "planner-output"

        main_module.StrategyResearchPlannerReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.StrategyResearchPlannerReport = original_reporter
            sys.argv = original_argv
        self.assertEqual(
            captured,
            [{"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min", "execute_next_research_step": False}],
        )
        self.assertIn("planner-output", stdout.getvalue())


def _planner(*, variant_report, diagnostics_rows, baseline_loss_report, variant_loss_reports=None):
    planner = StrategyResearchPlannerReport.__new__(StrategyResearchPlannerReport)
    planner.config = object()
    planner.usage_ledger = object()
    planner.variant_reporter = _StubVariantReporter(variant_report)
    planner.variant_diagnostics_reporter = _StubDiagnosticsReporter(
        {
            "title": "Strategy Variant Diagnostics",
            "rows": list(diagnostics_rows),
        }
    )
    planner.loss_reporter = _StubLossReporter(baseline_loss_report, variant_loss_reports)
    planner.symbol_stability_reporter = _StubSymbolStabilityReporter()
    return planner


def _variant_report(variants):
    return {
        "baseline": {
            "variant_id": "baseline",
            "metrics": {
                "net_return_after_costs": -0.5,
                "sample_size": 40,
            },
        },
        "variants": list(variants),
    }


def _variant(
    variant_id,
    *,
    generation_reason="grid",
    params_json=None,
    beats_baseline=False,
    beats_thresholds=False,
    net_return_after_costs=-0.5,
    win_rate=0.5,
):
    return {
        "variant_id": variant_id,
        "generation_reason": generation_reason,
        "params_json": dict(params_json or {}),
        "beats_baseline": beats_baseline,
        "beats_thresholds": beats_thresholds,
        "net_return_after_costs": net_return_after_costs,
        "win_rate": win_rate,
        "drawdown": 1.0,
    }


def _loss_report(
    *,
    loss_verdict="snapback_exit_logic_problem",
    profitability_verdict="break_even_requirements_met",
    exit_verdict="exit_logic_no_clear_fix",
    subset_verdict="no_clear_subset_edge",
    sample_size=40,
    diagnosed_variant_id="baseline",
    symbol_rows=None,
):
    return {
        "verdict": loss_verdict,
        "diagnosed_variant_id": diagnosed_variant_id,
        "return_distribution": {"total_decisions": sample_size},
        "profitability_requirement_diagnosis": {
            "profitability_verdict": profitability_verdict,
        },
        "time_exit_and_target_achievement_diagnosis": {
            "exit_verdict": exit_verdict,
        },
        "subset_edge_diagnosis": {
            "verdict": subset_verdict,
        },
        "symbol_breakdown": {
            "symbols_with_enough_sample": list(symbol_rows or []),
        },
    }


if __name__ == "__main__":
    unittest.main()
