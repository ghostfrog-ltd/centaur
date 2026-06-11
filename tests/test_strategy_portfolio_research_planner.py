from __future__ import annotations

import contextlib
from io import StringIO
import json
import os
import sys
from types import SimpleNamespace
import unittest

import main as main_module
from app.framework.reporting.strategy_portfolio_research_planner import (
    SAFETY_STATEMENT,
    StrategyPortfolioResearchPlannerReport,
)


class _StubLedger:
    def __init__(self, *, definitions=None, decisions=None, promotions=None, evaluations=None):
        self._definitions = list(definitions or [])
        self._decisions = list(decisions or [])
        self._promotions = dict(promotions or {})
        self._evaluations = list(evaluations or [])

    def list_strategy_variant_definitions(self, **_kwargs):
        return list(self._definitions)

    def list_latest_research_cycle_decisions(self):
        return list(self._decisions)

    def get_strategy_promotion(self, *, strategy_id, profile_id):
        return dict(self._promotions.get((strategy_id, profile_id), {}))

    def list_strategy_variant_evaluations(self, **_kwargs):
        return list(self._evaluations)


class _StubVariantReporter:
    def __init__(self, reports):
        self.reports = dict(reports)

    def build_report(self, **kwargs):
        key = (kwargs["base_strategy_id"], kwargs["profile_id"], kwargs["timeframe"])
        report = self.reports.get(key)
        if isinstance(report, Exception):
            raise report
        return dict(report or {})


class _StubLossReporter:
    def __init__(self, reports):
        self.reports = dict(reports)

    def build_report(self, **kwargs):
        key = (kwargs["base_strategy_id"], kwargs["profile_id"], kwargs["timeframe"])
        report = self.reports.get(key)
        if isinstance(report, Exception):
            raise report
        return dict(report or {})


class _StubStrategyPlanner:
    def __init__(self, reports):
        self.reports = dict(reports)

    def build_report(self, **kwargs):
        key = (kwargs["base_strategy_id"], kwargs["profile_id"], kwargs["timeframe"])
        report = self.reports.get(key)
        if isinstance(report, Exception):
            raise report
        return dict(report or {})


class _StubAuditReporter:
    def __init__(self, reports):
        self.reports = dict(reports)

    def build_report(self, **kwargs):
        key = (kwargs["base_strategy_id"], kwargs["profile_id"], kwargs["timeframe"])
        report = self.reports.get(key)
        if isinstance(report, Exception):
            raise report
        return dict(report or {})


class _StubVariantService:
    def __init__(self, result=None):
        self.result = dict(result or {})
        self.calls: list[dict[str, object]] = []

    def run_research(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "variants_generated": 15,
            "variants_total_including_baseline": 16,
            "evaluations": [{"variant_id": "baseline"}],
            **self.result,
        }


class StrategyPortfolioResearchPlannerTests(unittest.TestCase):
    def test_default_report_uses_read_only_skip_bootstrap_ledger(self) -> None:
        calls: list[dict[str, object]] = []
        original_usage_ledger = (
            StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"]
        )

        class _InitStubLedger:
            def __init__(self, **kwargs: object) -> None:
                calls.append(dict(kwargs))

            def list_strategy_variant_definitions(self, **_kwargs):
                return []

            def list_latest_research_cycle_decisions(self, **_kwargs):
                return []

            def get_strategy_promotion(self, **_kwargs):
                return {}

            def list_strategy_variant_evaluations(self, **_kwargs):
                return []

        StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"] = _InitStubLedger
        try:
            report = StrategyPortfolioResearchPlannerReport(config=SimpleNamespace())
        finally:
            StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"] = (
                original_usage_ledger
            )

        self.assertIsInstance(report.usage_ledger, _InitStubLedger)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]["read_only"])
        self.assertTrue(calls[0]["skip_schema_bootstrap"])
        self.assertEqual(calls[0]["query_timeout_ms"], 15000)
        self.assertIsNone(calls[0]["lock_timeout_ms"])
        self.assertFalse(calls[1]["read_only"])

    def test_diagnostics_use_write_enabled_research_ledger_while_reports_stay_read_only(self) -> None:
        calls: list[dict[str, object]] = []
        original_usage_ledger = (
            StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"]
        )

        class _InitStubLedger:
            def __init__(self, **kwargs: object) -> None:
                calls.append(dict(kwargs))

            def list_strategy_variant_definitions(self, **_kwargs):
                return []

            def list_latest_research_cycle_decisions(self, **_kwargs):
                return []

            def get_strategy_promotion(self, **_kwargs):
                return {}

            def list_strategy_variant_evaluations(self, **_kwargs):
                return []

        StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"] = _InitStubLedger
        try:
            report = StrategyPortfolioResearchPlannerReport(config=SimpleNamespace())
        finally:
            StrategyPortfolioResearchPlannerReport.__init__.__globals__["UsageLedger"] = (
                original_usage_ledger
            )

        self.assertIsInstance(report.research_usage_ledger, _InitStubLedger)
        self.assertTrue(report.usage_ledger.read_only if hasattr(report.usage_ledger, "read_only") else calls[0]["read_only"])
        self.assertFalse(calls[1]["read_only"])
        self.assertIs(report.variant_service.usage_ledger, report.research_usage_ledger)

    def test_ranks_positive_improving_strategy_above_deeply_negative_ones(self) -> None:
        planner = _planner()
        built = planner.build_report()
        ranked = built["ranked_strategies"]
        self.assertEqual(ranked[0]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(ranked[0]["research_status"], "insufficient_data")
        self.assertEqual(built["selected_next_strategy"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_portfolio_action"], "collect_more_data_for_snapback_WDC")
        self.assertEqual(
            built["next_actionable_research_candidate"]["base_strategy_id"],
            "mean_reversion.snapback",
        )

    def test_deprioritises_strongly_negative_strategies_with_sufficient_sample(self) -> None:
        planner = _planner()
        built = planner.build_report()
        rows = {item["base_strategy_id"]: item for item in built["ranked_strategies"]}
        self.assertEqual(rows["momentum.balanced"]["research_status"], "deprioritise")
        self.assertEqual(rows["momentum.strong"]["research_status"], "deprioritise")
        self.assertEqual(rows["crypto_pullback"]["research_status"], "deprioritise")

    def test_exhausted_universe_emits_explicit_operator_action(self) -> None:
        planner = _planner(
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=60, net_avg=-0.9, win_rate=0.4),
                _decision("crypto_momentum.trend", "trend", "15Min", outcomes_recorded=44, net_avg=-0.8, win_rate=0.38),
                _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=64, net_avg=-1.24, win_rate=0.41),
                _decision("momentum.strong", "strong", "1Day", outcomes_recorded=58, net_avg=-0.91, win_rate=0.39),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(sample_size=60, net_return_after_costs=-0.9, win_rate=0.4, variants=[]),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(sample_size=44, net_return_after_costs=-0.8, win_rate=0.38, variants=[]),
                ("momentum.balanced", "balanced", "1Hour"): _variant_report(sample_size=64, net_return_after_costs=-1.24, win_rate=0.41, variants=[]),
                ("momentum.strong", "strong", "1Day"): _variant_report(sample_size=58, net_return_after_costs=-0.91, win_rate=0.39, variants=[]),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): {"selected_experiment_type": "retire_or_deprioritise_strategy", "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy mean_reversion.snapback --profile-id snapback", "reason": "No edge is visible."},
                ("crypto_momentum.trend", "trend", "15Min"): {"selected_experiment_type": "retire_or_deprioritise_strategy", "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy crypto_momentum.trend --profile-id trend", "reason": "No edge is visible."},
                ("momentum.balanced", "balanced", "1Hour"): {"selected_experiment_type": "retire_or_deprioritise_strategy", "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.balanced --profile-id balanced", "reason": "No edge is visible."},
                ("momentum.strong", "strong", "1Day"): {"selected_experiment_type": "retire_or_deprioritise_strategy", "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.strong --profile-id strong", "reason": "No edge is visible."},
            },
        )
        built = planner.build_report()
        self.assertEqual(built["portfolio_research_status"], "no_actionable_candidate")
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["next_required_operator_action"], "generate_new_research_candidates")
        self.assertEqual(built["proposed_next_command"], ".venv-mac/bin/python main.py --research-expansion-planner")
        self.assertEqual(built["terminal_research_state"], "generate_new_strategy_family")
        self.assertEqual(built["next_safe_operator_action"], "generate_new_research_candidates")
        self.assertEqual(built["next_check_command"], ".venv-mac/bin/python main.py --research-expansion-planner")

    def test_generated_research_candidate_definition_becomes_next_actionable_candidate(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"),
            definitions=[
                {
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "params_json": {
                        "__research_candidate_metadata__": {"source_profile_id": "range_breakout"},
                        "min_movement_pct": 0.08,
                        "min_volume_ratio": 1.1,
                    },
                },
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "1Hour"},
                {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "1Day"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=60, net_avg=-0.9, win_rate=0.4),
                _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=64, net_avg=-1.24, win_rate=0.41),
                _decision("momentum.strong", "strong", "1Day", outcomes_recorded=58, net_avg=-0.91, win_rate=0.39),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                ),
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(sample_size=60, net_return_after_costs=-0.9, win_rate=0.4, variants=[]),
                ("momentum.balanced", "balanced", "1Hour"): _variant_report(sample_size=64, net_return_after_costs=-1.24, win_rate=0.41, variants=[]),
                ("momentum.strong", "strong", "1Day"): _variant_report(sample_size=58, net_return_after_costs=-0.91, win_rate=0.39, variants=[]),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy mean_reversion.snapback --profile-id snapback",
                    "reason": "No edge is visible.",
                },
                ("momentum.balanced", "balanced", "1Hour"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.balanced --profile-id balanced",
                    "reason": "No edge is visible.",
                },
                ("momentum.strong", "strong", "1Day"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.strong --profile-id strong",
                    "reason": "No edge is visible.",
                },
            },
        )

        built = planner.build_report()

        self.assertEqual(built["research_universe_status"], "active_current_strategy_set")
        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_wide_signal")
        self.assertEqual(built["next_actionable_research_candidate"]["lifecycle_status"], "generated_not_evaluated")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_wide_signal --timeframe 15Min",
        )

    def test_generated_new_family_candidate_becomes_active_current_strategy_set(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"),
            definitions=[
                {
                    "variant_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                    "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                    "profile_id": "liquidation_wick_reclaim_confirmed",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "evaluation_status": "pending",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "liquidation_wick_reclaim",
                            "candidate_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                            "generated_at": "2026-06-10T10:00:00+00:00",
                        },
                        "min_flush_pct": 1.15,
                        "holding_window_minutes": 180,
                    },
                    "notes": "{}",
                },
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=60, net_avg=-0.9, win_rate=0.4),
            ],
            variant_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                    runtime_summary={"runtime_status": "not_run"},
                ),
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(sample_size=60, net_return_after_costs=-0.9, win_rate=0.4, variants=[]),
            },
            planner_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {},
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": "",
                    "reason": "No edge is visible.",
                },
            },
        )

        built = planner.build_report()

        self.assertEqual(built["research_universe_status"], "active_current_strategy_set")
        self.assertEqual(built["selected_next_strategy"]["base_strategy_id"], "crypto_research.liquidation_wick_reclaim")
        self.assertEqual(built["selected_next_strategy"]["profile_id"], "liquidation_wick_reclaim_confirmed")
        self.assertEqual(built["next_portfolio_action"], "run_generated_variant_research")
        self.assertIn("liquidation_wick_reclaim_confirmed", built["next_actionable_research_command"])

    def test_generated_candidate_with_zero_sample_completed_variant_research_is_not_diagnosed(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                        },
                        "min_movement_pct": 0.08,
                        "min_volume_ratio": 1.1,
                    },
                },
                {"base_strategy_id": "crypto_research.range_breakout", "profile_id": "range_breakout", "timeframe": "15Min"},
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=60, net_avg=-0.9, win_rate=0.4),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "insufficient_crypto_history",
                        "coverage_symbols_seen": 8,
                        "eligible_symbols_after_filters": 3,
                        "symbols_processed_for_strategy": 0,
                        "zero_sample_reason": "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay",
                        "history_coverage_reason": "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient",
                        "bars_read": 4400,
                    },
                ),
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=3,
                    variants_evaluated=3,
                ),
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(
                    sample_size=60,
                    net_return_after_costs=-0.9,
                    win_rate=0.4,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
                ("crypto_research.range_breakout", "range_breakout", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    "reason": "Base breakout still has no usable persisted decisions.",
                },
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy mean_reversion.snapback --profile-id snapback",
                    "reason": "No edge is visible.",
                },
            },
        )

        built = planner.build_report()

        candidate = next(
            item for item in built["ranked_strategies"]
            if item["profile_id"] == "range_breakout_wide_signal"
        )
        self.assertEqual(candidate["profile_id"], "range_breakout_wide_signal")
        self.assertEqual(candidate["generated_candidate_lifecycle_status"], "insufficient_history_after_variant_research")
        self.assertEqual(candidate["research_status"], "insufficient_history_after_variant_research")
        self.assertEqual(
            candidate["generated_candidate_zero_sample_outcome"]["reason"],
            "variant_research_completed_but_zero_samples",
        )
        self.assertFalse(built["next_actionable_research_candidate"])
        self.assertNotEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertNotIn("range_breakout_wide_signal", built["next_actionable_research_command"])
        self.assertEqual(
            built["terminal_research_state"],
            "generate_new_strategy_family_or_wait_for_new_market_data",
        )
        self.assertEqual(
            built["no_actionable_reason"],
            "All current and generated candidates are exhausted, blocked, or zero-sample.",
        )
        self.assertEqual(built["waiting_for"], "new_market_data_or_new_strategy_family")
        self.assertEqual(
            built["minimum_new_data_required"],
            "additional crypto bars covering enough replay windows for zero-sample candidates",
        )
        self.assertEqual(
            built["next_safe_operator_action"],
            "wait_for_new_market_data_or_generate_new_strategy_family",
        )
        self.assertEqual(
            built["next_check_command"],
            ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        )

    def test_generated_candidate_missing_features_requests_data_action_not_bad_evidence(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                    "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                    "profile_id": "liquidation_wick_reclaim_confirmed",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "liquidation_wick_reclaim",
                            "candidate_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                        },
                    },
                    "notes": "{}",
                },
            ],
            decisions=[],
            variant_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=16,
                    variants_evaluated=17,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                        "no_progress_classification": "missing_required_features",
                        "no_progress_reason": "required replay features missing: vwap, volume_ratio_20, atr_pct_20",
                        "next_required_action": "compute_crypto_15Min_vwap_features",
                        "missing_required_fields": ["vwap", "volume_ratio_20", "atr_pct_20"],
                    },
                ),
            },
            planner_reports={},
        )

        built = planner.build_report()

        candidate = next(
            item for item in built["ranked_strategies"]
            if item["profile_id"] == "liquidation_wick_reclaim_confirmed"
        )
        self.assertEqual(
            candidate["generated_candidate_zero_sample_outcome"]["no_progress_classification"],
            "missing_required_features",
        )
        self.assertEqual(
            candidate["generated_candidate_zero_sample_outcome"]["next_required_action"],
            "compute_crypto_15Min_vwap_features",
        )
        self.assertNotEqual(
            candidate["generated_candidate_zero_sample_outcome"]["no_progress_reason"],
            "no_progress_after_research_step_with_negative_replay_edge",
        )

    def test_generated_candidate_with_nonzero_variant_result_can_move_to_diagnosis(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"),
            definitions=[
                {
                    "variant_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                    "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                    "profile_id": "liquidation_wick_reclaim_confirmed",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "liquidation_wick_reclaim",
                            "candidate_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                        },
                    },
                    "notes": "{}",
                },
            ],
            decisions=[
                _decision(
                    "crypto_research.liquidation_wick_reclaim",
                    "liquidation_wick_reclaim_confirmed",
                    "15Min",
                    outcomes_recorded=4,
                    net_avg=0.18,
                    win_rate=0.5,
                ),
            ],
            variant_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): _variant_report(
                    sample_size=4,
                    net_return_after_costs=0.18,
                    win_rate=0.5,
                    variants=[],
                    variants_generated=16,
                    variants_evaluated=17,
                    runtime_summary={
                        "baseline_sample_size": 4,
                        "best_variant_sample_size": 7,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                        "no_progress_classification": "variant_research_not_consumed",
                        "next_required_action": "send_to_diagnosis",
                    },
                ),
            },
            planner_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {},
            },
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertIn("--diagnose-next-best-strategy", built["next_actionable_research_command"])

    def test_generated_compression_release_zero_sample_variant_research_is_classified_generically(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                        },
                        "min_movement_pct": 0.16,
                        "min_volume_ratio": 1.35,
                    },
                },
                {"base_strategy_id": "crypto_research.range_breakout", "profile_id": "range_breakout", "timeframe": "15Min"},
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=60, net_avg=-0.9, win_rate=0.4),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "insufficient_market_history",
                        "coverage_symbols_seen": 8,
                        "eligible_symbols_after_filters": 3,
                        "symbols_processed_for_strategy": 0,
                        "zero_sample_reason": "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay",
                        "history_coverage_reason": "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient",
                        "bars_read": 4400,
                    },
                ),
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=3,
                    variants_evaluated=3,
                ),
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(
                    sample_size=60,
                    net_return_after_costs=-0.9,
                    win_rate=0.4,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): {},
                ("crypto_research.range_breakout", "range_breakout", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    "reason": "Base breakout still has no usable persisted decisions.",
                },
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy mean_reversion.snapback --profile-id snapback",
                    "reason": "No edge is visible.",
                },
            },
        )

        built = planner.build_report()

        candidate = next(
            item for item in built["ranked_strategies"]
            if item["profile_id"] == "range_breakout_compression_release"
        )
        self.assertEqual(candidate["generated_candidate_lifecycle_status"], "insufficient_history_after_variant_research")
        self.assertEqual(candidate["research_status"], "insufficient_history_after_variant_research")
        self.assertEqual(
            candidate["generated_candidate_zero_sample_outcome"]["reason"],
            "variant_research_completed_but_zero_samples",
        )
        self.assertEqual(
            candidate["generated_candidate_zero_sample_outcome"]["next_required_action"],
            "generate_next_research_candidate",
        )
        self.assertFalse(built["next_actionable_research_candidate"])
        self.assertNotEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")

    def test_generated_candidate_with_nonzero_variant_samples_can_still_move_to_diagnosis(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"),
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour", outcomes_recorded=12, net_avg=-0.04, win_rate=0.5),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): _variant_report(
                    sample_size=12,
                    net_return_after_costs=-0.04,
                    win_rate=0.5,
                    variants=[
                        {
                            "variant_id": "compression-v1",
                            "net_return_after_costs": 0.02,
                            "win_rate": 0.55,
                            "beats_baseline": True,
                            "beats_thresholds": False,
                        }
                    ],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 12,
                        "best_variant_sample_size": 9,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                    },
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): {},
            },
        )

        built = planner.build_report()

        candidate = built["next_actionable_research_candidate"]
        self.assertEqual(candidate["profile_id"], "range_breakout_compression_release")
        self.assertEqual(candidate["lifecycle_status"], "variant_research_completed")
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertIn("--diagnose-next-best-strategy", built["next_actionable_research_command"])

    def test_pending_generated_candidate_with_newer_variant_evidence_advances_to_diagnosis(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                    "generation_reason": "research_expansion_candidate",
                    "evaluation_status": "pending",
                    "created_at": "2026-06-10T09:07:59+01:00",
                    "notes": "{\"lifecycle_status\":\"variant_research_completed\",\"generated_candidate_evidence_at\":\"2026-06-10T09:56:20+01:00\",\"baseline_sample_size\":12,\"best_variant_sample_size\":17,\"runtime_status\":\"completed\"}",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                            "generated_at": "2026-06-10T09:07:59+01:00",
                            "evaluation_status": "pending",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour", outcomes_recorded=12, net_avg=0.14, win_rate=0.61),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): _variant_report(
                    sample_size=12,
                    net_return_after_costs=0.14,
                    win_rate=0.61,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 12,
                        "best_variant_sample_size": 17,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                    },
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): {
                    "selected_experiment_type": "",
                    "proposed_next_command": "",
                    "reason": "",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.range_breakout",
                    "range_breakout_compression_release",
                    "1Hour",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-10T09:51:20+01:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "before_candidate": "crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                        "after_candidate": "crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                        "before_action_identity": {
                            "base_strategy_id": "crypto_research.range_breakout",
                            "profile_id": "range_breakout_compression_release",
                            "timeframe": "1Hour",
                            "variant_id": "",
                            "action_type": "diagnose_next_best_strategy",
                            "command_type": "diagnose-next-best-strategy",
                        },
                        "after_action_identity": {
                            "base_strategy_id": "crypto_research.range_breakout",
                            "profile_id": "range_breakout_compression_release",
                            "timeframe": "1Hour",
                            "variant_id": "",
                            "action_type": "diagnose_next_best_strategy",
                            "command_type": "diagnose-next-best-strategy",
                        },
                        "recorded_at": "2026-06-10T09:51:20+01:00",
                        "autopilot_classification_timestamp": "2026-06-10T09:51:20+01:00",
                    },
                )
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["portfolio_research_status"], "research_in_progress")
        self.assertEqual(built["research_universe_status"], "active_current_strategy_set")
        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_compression_release")
        self.assertEqual(built["next_actionable_research_candidate"]["lifecycle_status"], "variant_research_completed")
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertIn("--diagnose-next-best-strategy", built["next_actionable_research_command"])

    def test_zero_sample_generated_candidate_is_not_diagnosis_eligible_without_newer_nonzero_evidence(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "evaluation_status": "evaluated_no_samples",
                    "created_at": "2026-06-10T09:07:59+01:00",
                    "notes": "{\"lifecycle_status\":\"variant_research_completed\",\"generated_candidate_evidence_at\":\"2026-06-10T11:54:43+01:00\",\"baseline_sample_size\":0,\"best_variant_sample_size\":0,\"runtime_status\":\"completed\"}",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                            "generated_at": "2026-06-10T09:07:59+01:00",
                            "evaluation_status": "evaluated_no_samples",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "insufficient_crypto_history",
                    },
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
            },
        )

        built = planner.build_report()

        self.assertIsNone(built["next_actionable_research_candidate"])
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")

    def test_generated_candidate_can_reenter_diagnosis_after_newer_nonzero_variant_evidence(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "evaluation_status": "evaluated_no_samples",
                    "created_at": "2026-06-10T09:07:59+01:00",
                    "notes": "{\"lifecycle_status\":\"variant_research_completed\",\"generated_candidate_evidence_at\":\"2026-06-10T09:54:43+01:00\",\"baseline_sample_size\":0,\"best_variant_sample_size\":0,\"runtime_status\":\"completed\"}",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                            "generated_at": "2026-06-10T09:07:59+01:00",
                            "evaluation_status": "evaluated_no_samples",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min", outcomes_recorded=12, net_avg=0.11, win_rate=0.58),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=12,
                    net_return_after_costs=0.11,
                    win_rate=0.58,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 12,
                        "best_variant_sample_size": 14,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                    },
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
            },
            evaluations=[
                _evaluation(
                    "crypto_research.range_breakout",
                    "range_breakout_wide_signal",
                    "15Min",
                    variant_id="range-breakout-refresh",
                    evaluated_at="2026-06-10T10:15:00+01:00",
                    raw_json={"report_type": "strategy_variant_research"},
                )
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_wide_signal")
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertIn("--diagnose-next-best-strategy", built["next_actionable_research_command"])

    def test_distinct_generated_candidate_is_consumed_after_failed_wide_signal_is_excluded(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"),
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                        },
                    },
                },
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                        },
                        "min_movement_pct": 0.16,
                        "min_volume_ratio": 1.35,
                    },
                },
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "insufficient_crypto_history",
                    },
                ),
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): {},
            },
            loss_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): {},
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): {},
            },
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_compression_release")
        self.assertEqual(built["next_actionable_research_candidate"]["timeframe"], "1Hour")
        self.assertEqual(built["next_actionable_research_candidate"]["lifecycle_status"], "generated_not_evaluated")
        self.assertIn("range_breakout_compression_release", built["next_actionable_research_command"])
        self.assertNotIn("range_breakout_wide_signal --timeframe 15Min", built["next_actionable_research_command"])

    def test_fresh_generated_candidate_outranks_stale_exhausted_base_follow_up(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                ),
                ("crypto_research.range_breakout", "range_breakout_compression_release", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    "reason": "The base profile has already been retried and is exhausted.",
                }
            },
            evaluations=[
                _evaluation(
                    "crypto_research.range_breakout",
                    "range_breakout",
                    "15Min",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T11:45:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "before_candidate": "crypto_research.range_breakout/range_breakout/15Min",
                        "after_candidate": "crypto_research.range_breakout/range_breakout/15Min",
                        "before_action": "continue_research_for_crypto_research.range_breakout",
                        "after_action": "continue_research_for_crypto_research.range_breakout",
                        "before_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                        "after_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                        "recorded_at": "2026-06-09T11:45:00+00:00",
                        "step_advanced": "no",
                        "evidence_changed": "no",
                        "candidate_status_changed": "no",
                    },
                )
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["portfolio_research_status"], "research_in_progress")
        self.assertEqual(built["research_universe_status"], "active_current_strategy_set")
        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_compression_release")
        self.assertEqual(built["next_actionable_research_candidate"]["lifecycle_status"], "generated_not_evaluated")
        self.assertEqual(
            built["next_actionable_research_candidate"]["reason"],
            "no_progress_after_research_step_with_negative_replay_edge",
        )
        self.assertIn("range_breakout_compression_release", built["next_actionable_research_command"])
        self.assertNotIn("--profile-id range_breakout --timeframe 15Min", built["next_actionable_research_command"])

    def test_generated_candidate_zero_sample_classification_is_operator_readable(self) -> None:
        planner = _planner(
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                        },
                    },
                }
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 0,
                        "best_variant_sample_size": 0,
                        "runtime_status": "completed",
                        "runtime_blocker": "insufficient_crypto_history",
                        "coverage_symbols_seen": 8,
                        "eligible_symbols_after_filters": 3,
                        "symbols_processed_for_strategy": 0,
                        "zero_sample_reason": "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay",
                        "history_coverage_reason": "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient",
                        "bars_read": 4400,
                    },
                ),
            },
        )

        built = planner.build_report()

        summary = next(
            item["generated_candidate_zero_sample_outcome"]
            for item in built["ranked_strategies"]
            if item["profile_id"] == "range_breakout_wide_signal"
        )
        self.assertEqual(summary["research_status"], "insufficient_history_after_variant_research")
        self.assertEqual(summary["next_required_action"], "generate_next_research_candidate")
        self.assertEqual(summary["coverage_symbols_seen"], 8)
        self.assertEqual(summary["eligible_symbols_after_filters"], 3)
        self.assertEqual(summary["symbols_processed_for_strategy"], 0)
        self.assertEqual(
            summary["history_coverage_reason"],
            "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient",
        )

    def test_generated_candidate_with_nonzero_variant_research_can_move_to_diagnosis(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"),
            definitions=[
                {
                    "variant_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_wide_signal",
                    "timeframe": "15Min",
                    "generation_reason": "research_expansion_candidate",
                    "params_json": {
                        "__research_candidate_metadata__": {
                            "source_profile_id": "range_breakout",
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                        },
                    },
                }
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min", outcomes_recorded=12, net_avg=0.11, win_rate=0.58),
            ],
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout_wide_signal", "15Min"): _variant_report(
                    sample_size=12,
                    net_return_after_costs=0.11,
                    win_rate=0.58,
                    variants=[],
                    variants_generated=15,
                    variants_evaluated=16,
                    runtime_summary={
                        "baseline_sample_size": 12,
                        "best_variant_sample_size": 14,
                        "runtime_status": "completed",
                        "runtime_blocker": "",
                    },
                ),
            },
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["profile_id"], "range_breakout_wide_signal")
        self.assertEqual(
            built["next_actionable_research_candidate"]["lifecycle_status"],
            "variant_research_completed",
        )
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertIn("--diagnose-next-best-strategy", built["next_actionable_research_command"])

    def test_does_not_promote_paper_or_live(self) -> None:
        planner = _planner(
            planner_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --variant-id v-snap --symbol WDC",
                    "reason": "Validate the subset only.",
                }
            }
        )
        built = planner.build_report()
        text = " ".join(
            [
                built["selected_next_experiment_type"],
                built["reason"],
                built["proposed_next_command"],
                built["safety_statement"],
            ]
        ).lower()
        self.assertNotIn("approve-paper", text)
        self.assertNotIn("live", built["selected_next_experiment_type"])

    def test_autopilot_applied_deprioritise_until_new_data_excludes_candidate_from_immediate_reselection(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "1Hour", outcomes_recorded=41, net_avg=-0.62, win_rate=0.39),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=11, net_avg=0.08, win_rate=0.56),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.62,
                    win_rate=0.39,
                    variants=[],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=42,
                    net_return_after_costs=0.18,
                    win_rate=0.56,
                    variants=[
                        {
                            "variant_id": "steady-v1",
                            "net_return_after_costs": 0.22,
                            "win_rate": 0.58,
                            "beats_baseline": True,
                            "beats_thresholds": False,
                        }
                    ],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "Needs another bounded diagnosis.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Alternative candidate remains actionable.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "liquidity_probe.steady_flow")
        dip = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_research.dip_rebound")
        self.assertEqual(dip["autopilot_classification_timestamp"], "2026-06-09T10:00:00+00:00")
        self.assertEqual(dip["latest_relevant_evidence_timestamp"], "")

    def test_no_progress_reason_excludes_candidate_until_newer_evidence_exists(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "1Hour", outcomes_recorded=41, net_avg=-0.62, win_rate=0.39),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.62,
                    win_rate=0.39,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "Needs another bounded diagnosis.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                        "step_advanced": "no",
                        "evidence_changed": "no",
                        "candidate_status_changed": "no",
                        "before_action": "diagnose_next_best_strategy",
                        "after_action": "diagnose_next_best_strategy",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertIsNone(built["next_actionable_research_candidate"])
        dip = built["ranked_strategies"][0]
        self.assertEqual(
            dip["latest_autopilot_no_progress"]["classification_reason"],
            "no_progress_after_research_step_with_negative_replay_edge",
        )

    def test_candidate_becomes_eligible_again_once_newer_evidence_exists(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    outcomes_recorded=41,
                    net_avg=-0.12,
                    win_rate=0.46,
                    evaluated_at="2026-06-09T11:00:00+00:00",
                ),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.12,
                    win_rate=0.46,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "New replay evidence arrived after the autopilot pause.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="baseline",
                    evaluated_at="2026-06-09T11:00:00+00:00",
                    raw_json={"report_type": "strategy_variant_research"},
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "crypto_research.dip_rebound")
        dip = built["ranked_strategies"][0]
        self.assertEqual(dip["latest_variant_evaluation_timestamp"], "2026-06-09T11:00:00+00:00")
        self.assertEqual(dip["latest_relevant_evidence_timestamp"], "2026-06-09T11:00:00+00:00")

    def test_post_precompute_negative_dip_rebound_is_deprioritised_until_new_data(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=3, net_avg=-0.305701, win_rate=0.333333),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=42, net_avg=0.18, win_rate=0.56),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=3,
                    net_return_after_costs=-0.305701,
                    win_rate=0.333333,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Fresh precompute unlocked a bounded diagnosis but the edge is still weak.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:05:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/15Min",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/15Min",
                        "after_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "precompute_completed_but_only_3_negative_samples",
                        "recorded_at": "2026-06-09T10:05:00+00:00",
                    },
                ),
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "runtime_status": "precomputed",
                        "cache_status": "fresh",
                    },
                ),
            ],
        )

        built = planner.build_report()

        dip = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_research.dip_rebound")
        self.assertEqual(dip["research_status"], "deprioritise_until_new_data")
        self.assertEqual(
            dip["latest_autopilot_no_progress"]["classification_reason"],
            "precompute_completed_but_only_3_negative_samples",
        )
        self.assertIsNone(built["next_actionable_research_candidate"])
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")
        self.assertEqual(built["next_required_operator_action"], "generate_new_research_candidates")

    def test_post_precompute_negative_dip_rebound_unlocks_only_after_newer_evidence(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
            ],
            decisions=[
                _decision(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    outcomes_recorded=7,
                    net_avg=0.04,
                    win_rate=0.57,
                    evaluated_at="2026-06-09T11:00:00+00:00",
                ),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=7,
                    net_return_after_costs=0.04,
                    win_rate=0.57,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "New evidence arrived after the post-precompute pause.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:05:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/15Min",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/15Min",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "precompute_completed_but_only_3_negative_samples",
                        "recorded_at": "2026-06-09T10:05:00+00:00",
                    },
                ),
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="baseline",
                    evaluated_at="2026-06-09T11:00:00+00:00",
                    raw_json={"report_type": "strategy_variant_research"},
                ),
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "runtime_status": "precomputed",
                        "cache_status": "fresh",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "crypto_research.dip_rebound")
        dip = built["ranked_strategies"][0]
        self.assertEqual(dip["latest_relevant_evidence_timestamp"], "2026-06-09T11:00:00+00:00")

    def test_replay_dataset_preparation_counts_as_newer_evidence_for_autopilot_exclusion(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "1Hour", outcomes_recorded=41, net_avg=-0.12, win_rate=0.46),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.12,
                    win_rate=0.46,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "Replay preparation recorded fresh bounded evidence.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "before_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "after_candidate": "crypto_research.dip_rebound/dip_rebound/1Hour",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "1Hour",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:15:00+00:00",
                    raw_json={"report_type": "replay_dataset_preparation"},
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "crypto_research.dip_rebound")
        dip = built["ranked_strategies"][0]
        self.assertEqual(dip["latest_replay_preparation_timestamp"], "2026-06-09T11:15:00+00:00")
        self.assertEqual(dip["latest_relevant_evidence_timestamp"], "2026-06-09T11:15:00+00:00")

    def test_snapback_no_progress_is_excluded_like_dip_rebound(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=41, net_avg=-0.62, win_rate=0.39),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=11, net_avg=0.08, win_rate=0.56),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.62,
                    win_rate=0.39,
                    variants=[],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=11,
                    net_return_after_costs=0.08,
                    win_rate=0.56,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min",
                    "reason": "Would otherwise retry the same stale diagnosis.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Alternative candidate remains actionable.",
                },
            },
            evaluations=[
                _evaluation(
                    "mean_reversion.snapback",
                    "snapback",
                    "15Min",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "after_candidate": "mean_reversion.snapback/snapback/15Min",
                        "after_action_identity": {
                            "base_strategy_id": "mean_reversion.snapback",
                            "profile_id": "snapback",
                            "timeframe": "15Min",
                            "variant_id": "",
                            "action_type": "diagnose_next_best_strategy",
                            "command_type": "diagnose-next-best-strategy",
                        },
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "liquidity_probe.steady_flow")

    def test_run_scoped_parked_candidate_selects_next_safe_alternative(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "1Hour", outcomes_recorded=4, net_avg=-0.21377, win_rate=0.0),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=19, net_avg=0.09, win_rate=0.58),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=4,
                    net_return_after_costs=-0.21377,
                    win_rate=0.0,
                    variants=[],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=19,
                    net_return_after_costs=0.09,
                    win_rate=0.58,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "Would have retried the parked dip rebound candidate.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Safe fallback candidate remains actionable.",
                },
            },
        )

        built = planner.build_report(
            parked_candidate_keys_this_run=["crypto_research.dip_rebound/dip_rebound/1Hour"]
        )

        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "liquidity_probe.steady_flow")
        self.assertEqual(
            built["run_scoped_parked_candidates_received"],
            ["crypto_research.dip_rebound/dip_rebound/1Hour"],
        )
        considered = built["next_actionable_research_candidate_diagnostics"]["ranked_alternatives_considered"]
        parked = next(item for item in considered if item["candidate_key"] == "crypto_research.dip_rebound/dip_rebound/1Hour")
        self.assertEqual(parked["rejection_reason"], "parked_for_current_autopilot_run")

    def test_run_scoped_parked_candidates_can_exhaust_safe_alternatives(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "1Hour", outcomes_recorded=4, net_avg=-0.21377, win_rate=0.0),
            ],
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): _variant_report(
                    sample_size=4,
                    net_return_after_costs=-0.21377,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    "reason": "Only parked candidate remains.",
                },
            },
        )

        built = planner.build_report(
            parked_candidate_keys_this_run=["crypto_research.dip_rebound/dip_rebound/1Hour"]
        )

        self.assertIsNone(built["next_actionable_research_candidate"])
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        diagnostics = built["next_actionable_research_candidate_diagnostics"]
        self.assertEqual(diagnostics["parked_candidates_received"], ["crypto_research.dip_rebound/dip_rebound/1Hour"])
        self.assertEqual(
            diagnostics["ranked_alternatives_considered"][0]["rejection_reason"],
            "parked_for_current_autopilot_run",
        )

    def test_autopilot_exclusion_uses_stable_action_identity_not_raw_command_string(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "15Min", outcomes_recorded=41, net_avg=-0.62, win_rate=0.39),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(
                    sample_size=41,
                    net_return_after_costs=-0.62,
                    win_rate=0.39,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": "./.venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min",
                    "reason": "Equivalent command text should still be blocked.",
                },
            },
            evaluations=[
                _evaluation(
                    "mean_reversion.snapback",
                    "snapback",
                    "15Min",
                    variant_id="research-autopilot",
                    evaluated_at="2026-06-09T10:00:00+00:00",
                    raw_json={
                        "report_type": "research_autopilot_step_summary",
                        "after_candidate": "mean_reversion.snapback/snapback/15Min",
                        "after_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min",
                        "after_action": "diagnose_next_best_strategy",
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertIsNone(built["next_actionable_research_candidate"])

    def test_planner_points_to_symbol_replay_evidence_command(self) -> None:
        planner = _planner()
        built = planner.build_report()
        self.assertIn("--collect-symbol-replay-evidence", built["proposed_next_command"])
        self.assertTrue(built["execution_available"])

    def test_does_not_lower_thresholds(self) -> None:
        planner = _planner()
        built = planner.build_report()
        joined = f"{built['reason']} {built['proposed_next_command']}".lower()
        self.assertNotIn("lower threshold", joined)
        self.assertNotIn("widen risk", joined)

    def test_includes_all_strategies_with_persisted_evidence(self) -> None:
        planner = _planner()
        built = planner.build_report()
        strategy_ids = {item["base_strategy_id"] for item in built["ranked_strategies"]}
        self.assertEqual(
            strategy_ids,
            {
                "mean_reversion.snapback",
                "crypto_momentum.trend",
                "momentum.balanced",
                "momentum.strong",
                "crypto_pullback",
            },
        )

    def test_handles_missing_diagnosis_gracefully(self) -> None:
        planner = _planner(
            loss_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): {
                    "verdict": "snapback_exit_logic_problem",
                },
                ("momentum.balanced", "balanced", "1Hour"): RuntimeError("unsupported"),
                ("momentum.strong", "strong", "1Day"): RuntimeError("unsupported"),
                ("crypto_pullback", "downside_reversal_watch", "1Hour"): RuntimeError("unsupported"),
            }
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "momentum.balanced")
        self.assertEqual(row["latest_diagnosis_verdict"], "")
        self.assertEqual(row["research_status"], "deprioritise")

    def test_emits_exact_safety_statement(self) -> None:
        planner = _planner()
        rendered = planner.render()
        self.assertIn(SAFETY_STATEMENT, rendered)
        self.assertEqual(planner.build_report()["safety_statement"], SAFETY_STATEMENT)

    def test_json_shape_if_added(self) -> None:
        planner = _planner()
        built = planner.build_report()
        self.assertIn("ranked_strategies", built)
        self.assertIn("selected_next_strategy", built)
        self.assertEqual(built["execution_available"], True)

    def test_failed_audit_changes_status_and_blocks_paper_approval_path(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
            },
            loss_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "verdict": "snapback_cost_problem",
                }
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "test_cost_expected_move_variants",
                    "proposed_next_command": "app.framework.reporting.strategy_variant_research.StrategyVariantResearchService.run_research",
                    "reason": "Retest expected move filters.",
                }
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                    "fragility_flags": ["too_few_samples", "one_month_dominates_profit"],
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "mean_reversion.snapback" and item["timeframe"] == "1Hour")
        self.assertEqual(row["research_status"], "promising_but_failed_audit")
        self.assertEqual(planner._next_portfolio_action(row, built["ranked_strategies"]), "collect_more_out_of_sample_data")
        self.assertNotIn("--paper-candidate-audit", planner._proposed_next_command(row, built["ranked_strategies"]))
        self.assertEqual(
            built["why_not_selected_for_paper"],
            "Parked by paper-candidate audit until fresh evidence arrives; remain research-only.",
        )

    def test_unresolved_failed_audit_candidate_is_excluded_from_next_paper_candidate(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=87,
                    net_return_after_costs=0.18,
                    win_rate=0.58,
                    variants=[
                        {
                            "variant_id": "trend-v2",
                            "net_return_after_costs": 0.24,
                            "win_rate": 0.61,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "audit_verdict": "paper_candidate_needs_more_replay",
                    "audit_status": "blocked_pending_more_data",
                },
            },
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "no_usable_subset_data",
                        "selected_symbol_summary": {"sample_size": 0, "net_return_after_costs": 0.0},
                    }
                }
            ],
        )
        built = planner.build_report()
        self.assertEqual(built["current_known_best_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_paper_candidate"]["base_strategy_id"], "crypto_momentum.trend")

    def test_parked_candidate_is_not_recommended_for_same_audit_without_new_evidence(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=188,
                    net_return_after_costs=0.405455,
                    win_rate=0.648936,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=87,
                    net_return_after_costs=0.18,
                    win_rate=0.58,
                    variants=[
                        {
                            "variant_id": "trend-v2",
                            "net_return_after_costs": 0.24,
                            "win_rate": 0.61,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "audit_verdict": "paper_candidate_needs_more_replay",
                    "audit_status": "blocked_pending_more_data",
                },
            },
        )
        built = planner.build_report()
        self.assertEqual(built["blocked_or_parked_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertNotIn("--paper-candidate-audit --base-strategy mean_reversion.snapback", built["next_actionable_research_command"])
        self.assertEqual(
            built["next_actionable_research_reason"],
            "Selected a symbol-subset stability follow-up for the blocked best candidate before considering paper.",
        )
        self.assertNotIn("Selected a new untested strategy", built["next_actionable_research_reason"])
        self.assertIn(
            built["next_portfolio_action"],
            {"collect_more_out_of_sample_data", "audit_paper_candidate", "diagnose_next_best_strategy"},
        )

    def test_next_paper_candidate_excludes_data_gap_insufficient_and_deprioritised(self) -> None:
        planner = _planner(
            variant_reports={
                ("mean_reversion.snapback", "snapback", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "no_bars_for_timeframe"},
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                ),
                ("momentum.balanced", "balanced", "1Hour"): _variant_report(
                    sample_size=64,
                    net_return_after_costs=-1.24,
                    win_rate=0.41,
                    variants=[],
                ),
                ("momentum.strong", "strong", "1Day"): _variant_report(
                    sample_size=58,
                    net_return_after_costs=-0.91,
                    win_rate=0.39,
                    variants=[],
                ),
            },
        )
        built = planner.build_report()
        self.assertIsNone(built["next_paper_candidate"])

    def test_strategy_with_evidence_is_not_marked_untested(self) -> None:
        planner = _planner(
            selected_identity=("crypto_momentum.trend", "trend", "15Min"),
            variant_reports={
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=37,
                    net_return_after_costs=-0.11,
                    win_rate=0.51,
                    variants=[
                        {
                            "variant_id": "crypto-v1",
                            "net_return_after_costs": -0.05,
                            "win_rate": 0.53,
                            "beats_baseline": True,
                            "beats_thresholds": False,
                        }
                    ],
                ),
            },
            loss_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "verdict": "exit_logic_problem",
                }
            },
            planner_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "test_holding_window_variants",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Replay evidence exists and exits need retesting.",
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_momentum.trend")
        self.assertNotEqual(row["research_status"], "untested_strategy")

    def test_zero_decision_with_inadequate_crypto_data_stays_insufficient_data(self) -> None:
        planner = _planner(
            selected_identity=("crypto_pullback", "downside_reversal_watch", "1Hour"),
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "insufficient_crypto_history"},
                ),
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_pullback --profile-id downside_reversal_watch --timeframe 1Hour",
                    "reason": "Collect more crypto history first.",
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_pullback" and item["timeframe"] == "1Hour")
        self.assertEqual(row["research_status"], "insufficient_data")

    def test_no_bars_for_timeframe_produces_data_gap_action(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.dip_rebound", "dip_rebound", "15Min"),
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={
                        "zero_decision_reason": "no_bars_for_timeframe",
                        "dataset_id": "historical_crypto_bars:1Day:30d",
                        "days_covered": 0.0,
                        "symbols_covered": [],
                        "total_bars": 0,
                    },
                ),
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                    "reason": "No 1Day crypto bars are available yet.",
                },
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Proceed with the next crypto research candidate.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", "1Day", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_pullback" and item["timeframe"] == "1Day")
        self.assertEqual(row["research_status"], "data_gap")
        self.assertEqual(row["data_gap_action"]["research_status"], "insufficient_data")
        self.assertEqual(row["data_gap_action"]["data_gap_action"], "backfill_or_resample_crypto_1Day_bars")
        self.assertEqual(row["data_gap_action"]["reason"], "no 1Day crypto bars available")
        self.assertIn(
            "resample_15Min_bars_into_1Day_bars_research_only_if_provenance_is_auditable",
            row["data_gap_action"]["action_candidates"],
        )

    def test_data_gap_strategy_is_not_marked_deprioritise(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "no_bars_for_timeframe", "total_bars": 0},
                ),
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                    "reason": "No bars exist for the requested timeframe.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", "1Day", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_pullback")
        self.assertEqual(row["research_status"], "data_gap")
        self.assertNotIn(row["base_strategy_id"], {item["base_strategy_id"] for item in built["bad_strategies"]})
        self.assertIn(row["base_strategy_id"], {item["base_strategy_id"] for item in built["data_gap_strategies"]})

    def test_zero_decision_with_enough_data_but_no_setups_is_insufficient_data(self) -> None:
        planner = _planner(
            selected_identity=("crypto_pullback", "downside_reversal_watch", "1Hour"),
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "no_qualifying_setups_in_window"},
                ),
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_pullback --profile-id downside_reversal_watch --timeframe 1Hour",
                    "reason": "No setups were found in the replay window.",
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_pullback" and item["timeframe"] == "1Hour")
        self.assertEqual(row["research_status"], "insufficient_data")
        self.assertNotIn(row["base_strategy_id"], {item["base_strategy_id"] for item in built["bad_strategies"]})

    def test_zero_sample_strategy_is_not_bad_by_default(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout", "15Min"),
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "unknown_zero_decision_reason"},
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    "reason": "No replay outcomes were recorded yet for this shadow-only profile.",
                }
            },
            definitions=[
                {"base_strategy_id": "crypto_research.range_breakout", "profile_id": "range_breakout", "timeframe": "15Min"},
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=64, net_avg=-1.24, win_rate=0.41),
            ],
        )
        built = planner.build_report()
        row = next(
            item
            for item in built["ranked_strategies"]
            if item["base_strategy_id"] == "crypto_research.range_breakout" and item["profile_id"] == "range_breakout"
        )
        self.assertEqual(row["research_status"], "insufficient_data")
        self.assertNotIn(
            "crypto_research.range_breakout",
            {item["base_strategy_id"] for item in built["bad_strategies"]},
        )
        self.assertNotIn(
            "crypto_research.range_breakout",
            {item["base_strategy_id"] for item in built["deprioritised_strategies"]},
        )

    def test_zero_sample_unsupported_profile_is_not_deprioritised(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.range_breakout", "range_breakout", "15Min"),
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "unsupported_strategy_profile"},
                ),
            },
            planner_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                    "reason": "Profile support is incomplete, so the result is not a failed strategy verdict.",
                }
            },
            definitions=[
                {"base_strategy_id": "crypto_research.range_breakout", "profile_id": "range_breakout", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
        )
        built = planner.build_report()
        row = built["ranked_strategies"][0]
        self.assertEqual(row["research_status"], "insufficient_data")
        self.assertFalse(built["bad_strategies"])

    def test_zero_sample_after_variant_research_is_insufficient_data_not_untested(self) -> None:
        planner = _planner(
            selected_identity=("crypto_momentum.trend", "trend", "15Min"),
            variant_reports={
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=9,
                    variants_evaluated=10,
                ),
            },
            loss_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "verdict": "insufficient_diagnostics",
                }
            },
            planner_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-variant-research-report --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Evidence exists but no usable replay decisions were produced.",
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_momentum.trend")
        self.assertEqual(row["research_status"], "insufficient_data")

    def test_cli_command_invokes_portfolio_planner(self) -> None:
        original_reporter = main_module.StrategyPortfolioResearchPlannerReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--strategy-portfolio-research-planner"]

        class _Reporter:
            def __init__(self):
                print("db_connection_diagnostic noisy=true", file=sys.stderr)

            def render(self):
                print("runtime_db_diagnostic noisy=true", file=sys.stderr)
                return (
                    "Strategy Portfolio Research Planner\n"
                    "Final Summary\n"
                    "current_known_best_candidate=mean_reversion.snapback/snapback/15Min\n"
                    "current_paper_candidate=\n"
                    "paper_candidate_status=\n"
                    "paper_trading_allowed=\n"
                    "blocked_or_parked_candidate=\n"
                    "next_actionable_research_candidate=mean_reversion.snapback/snapback/15Min\n"
                    "next_actionable_research_reason=keep_collecting\n"
                    "next_actionable_research_command=.venv-mac/bin/python main.py --collect-symbol-replay-evidence\n"
                    "selected_next_strategy=mean_reversion.snapback/snapback/15Min\n"
                    "next_portfolio_action=collect_more_data_for_snapback_WDC\n"
                    "data_gap_strategies_count=0\n"
                    "bad_strategies_count=0\n"
                    "untested_strategies_count=0\n"
                    "promising_but_failed_audit_count=0"
                )

        main_module.StrategyPortfolioResearchPlannerReport = _Reporter
        stdout = StringIO()
        stderr = StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main_module.main()
        finally:
            main_module.StrategyPortfolioResearchPlannerReport = original_reporter
            sys.argv = original_argv
        text = stdout.getvalue()
        self.assertIn("Final Summary", text)
        self.assertIn("selected_next_strategy=mean_reversion.snapback/snapback/15Min", text)
        self.assertIn("diagnostics_suppressed=2", text)
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_verbose_mode_keeps_diagnostics_visible(self) -> None:
        original_reporter = main_module.StrategyPortfolioResearchPlannerReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--strategy-portfolio-research-planner", "--verbose"]

        class _Reporter:
            def __init__(self):
                print("db_connection_diagnostic noisy=true", file=sys.stderr)

            def render(self):
                return "Strategy Portfolio Research Planner\nFinal Summary\nselected_next_strategy=mean_reversion.snapback/snapback/15Min"

        main_module.StrategyPortfolioResearchPlannerReport = _Reporter
        stdout = StringIO()
        stderr = StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main_module.main()
        finally:
            main_module.StrategyPortfolioResearchPlannerReport = original_reporter
            sys.argv = original_argv
        self.assertIn("selected_next_strategy=mean_reversion.snapback/snapback/15Min", stdout.getvalue())
        self.assertIn("db_connection_diagnostic noisy=true", stderr.getvalue())

    def test_planner_advances_when_wide_stability_exists(self) -> None:
        planner = _planner(
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "symbol_promising_and_stable",
                        "selected_symbol_summary": {"sample_size": 617, "net_return_after_costs": 0.12},
                    }
                }
            ]
        )
        built = planner.build_report()
        self.assertEqual(built["next_portfolio_action"], "research_symbol_filter_variant")
        self.assertIn("--strategy-research-planner", built["proposed_next_command"])

    def test_failed_wide_stability_stops_wdc_branch_and_moves_on(self) -> None:
        planner = _planner(
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {"sample_size": 617, "net_return_after_costs": -0.243092},
                    }
                }
            ]
        )
        built = planner.build_report()
        self.assertEqual(built["stopped_branch"], "snapback_WDC")
        self.assertEqual(built["stopped_reason"], "symbol_not_promising")
        self.assertEqual(built["wide_sample_size"], 617)
        self.assertAlmostEqual(built["wide_net_return_after_costs"], -0.243092)
        self.assertEqual(
            built["blocked_or_parked_candidate"]["base_strategy_id"],
            "mean_reversion.snapback",
        )
        self.assertIsNone(built["next_actionable_research_candidate"])
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["proposed_next_command"], ".venv-mac/bin/python main.py --research-status")

    def test_parked_branch_is_not_immediately_reselected_as_next_actionable(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=87,
                    net_return_after_costs=0.18,
                    win_rate=0.58,
                    variants=[
                        {
                            "variant_id": "trend-v2",
                            "net_return_after_costs": 0.24,
                            "win_rate": 0.61,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                },
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "audit_verdict": "paper_candidate_needs_more_replay",
                },
            },
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {"sample_size": 617, "net_return_after_costs": -0.243092},
                    }
                }
            ],
        )
        built = planner.build_report()
        self.assertEqual(built["current_known_best_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["blocked_or_parked_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "crypto_momentum.trend")
        self.assertIn("--paper-candidate-audit", built["next_actionable_research_command"])

    def test_insufficient_data_candidate_can_remain_research_only_not_paper(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=12,
                    net_return_after_costs=0.03,
                    win_rate=0.55,
                    variants=[],
                ),
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                },
            },
        )
        built = planner.build_report()
        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["current_known_best_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_paper_candidate"]["base_strategy_id"], "mean_reversion.snapback")

    def test_run_selected_strategy_diagnostics_executes_planner_selected_timeframe(self) -> None:
        planner = _planner(
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                )
            },
            loss_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "verdict": "insufficient_diagnostics",
                    "profitability_requirement_diagnosis": {"profitability_verdict": "insufficient_data"},
                    "time_exit_and_target_achievement_diagnosis": {"exit_verdict": "insufficient_exit_diagnostics"},
                }
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour",
                    "reason": "Collect more 1Hour evidence from stored bars.",
                },
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Already attempted but still empty.",
                },
            },
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
        )
        planner.variant_service = _StubVariantService()
        result = planner.run_selected_strategy_diagnostics()
        self.assertEqual(result["status"], "no_selected_strategy")
        self.assertEqual(planner.variant_service.calls, [])

    def test_insufficient_data_advances_after_evidence_is_collected(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            planner_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Already attempted but still empty.",
                }
            },
        )

        class _DynamicVariantReporter:
            def __init__(self, service):
                self.service = service

            def build_report(self, **kwargs):
                if kwargs["timeframe"] != "1Hour":
                    return {}
                if not self.service.calls:
                    return {
                        "baseline": {"variant_id": "baseline", "metrics": {"sample_size": 0, "net_return_after_costs": 0.0, "win_rate": 0.0}},
                        "variants_generated": 0,
                        "variants_evaluated": 0,
                        "variants": [],
                    }
                return {
                    "baseline": {"variant_id": "baseline", "metrics": {"sample_size": 64, "net_return_after_costs": 0.22, "win_rate": 0.57}},
                    "variants_generated": 15,
                    "variants_evaluated": 16,
                    "variants": [{"variant_id": "v-snap", "beats_baseline": True, "beats_thresholds": False, "net_return_after_costs": 0.3, "win_rate": 0.58}],
                }

        class _DynamicLossReporter:
            def build_report(self, **kwargs):
                if kwargs["timeframe"] != "1Hour":
                    return {}
                if kwargs.get("variant_id"):
                    return {"subset_edge_diagnosis": {"verdict": "no_clear_subset_edge"}, "symbol_breakdown": {"symbols_with_enough_sample": []}}
                return {
                    "verdict": "snapback_exit_logic_problem",
                    "profitability_requirement_diagnosis": {"profitability_verdict": "break_even_requirements_met"},
                    "time_exit_and_target_achievement_diagnosis": {"exit_verdict": "holding_window_too_short"},
                }

        class _DynamicStrategyPlanner:
            def __init__(self, service):
                self.service = service

            def build_report(self, **kwargs):
                if kwargs["timeframe"] != "1Hour":
                    return {
                        "selected_experiment_type": "insufficient_data_collect_more",
                        "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    }
                if not self.service.calls:
                    return {
                        "selected_experiment_type": "insufficient_data_collect_more",
                        "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour",
                    }
                return {
                    "selected_experiment_type": "test_holding_window_variants",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour",
                }

        planner.variant_service = _StubVariantService()
        planner.variant_reporter = _DynamicVariantReporter(planner.variant_service)
        planner.loss_reporter = _DynamicLossReporter()
        planner.strategy_planner = _DynamicStrategyPlanner(planner.variant_service)

        result = planner.run_selected_strategy_diagnostics()

        self.assertEqual(result["before"]["strategy_planner_recommendation"], "insufficient_data_collect_more")
        self.assertEqual(result["after"]["strategy_planner_recommendation"], "test_holding_window_variants")
        self.assertNotEqual(result["after"]["sample_size"], result["before"]["sample_size"])

    def test_cli_diagnose_next_best_strategy_outputs_research_only_summary(self) -> None:
        original_reporter = main_module.StrategyPortfolioResearchPlannerReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--diagnose-next-best-strategy",
            "--base-strategy",
            "liquidity_probe.steady_flow",
            "--profile-id",
            "steady_flow",
            "--timeframe",
            "15Min",
        ]

        class _Reporter:
            def run_selected_strategy_diagnostics(self, **kwargs):
                assert kwargs == {
                    "base_strategy_id": "liquidity_probe.steady_flow",
                    "profile_id": "steady_flow",
                    "timeframe": "15Min",
                }
                return {
                    "selected_next_strategy": {
                        "base_strategy_id": "liquidity_probe.steady_flow",
                        "profile_id": "steady_flow",
                        "timeframe": "15Min",
                    },
                    "before": {"sample_size": 0, "net_return_after_costs": 0.0, "strategy_planner_recommendation": "insufficient_data_collect_more"},
                    "after": {"sample_size": 23, "net_return_after_costs": -0.097648, "win_rate": 0.478261, "drawdown": 1.402432, "strategy_planner_recommendation": "insufficient_data_collect_more"},
                    "planner_after": {"next_portfolio_action": "continue_research_for_liquidity_probe.steady_flow", "selected_next_experiment_type": "insufficient_data_collect_more"},
                    "diagnosis_summary": {
                        "sample_size": 23,
                        "net_return_after_costs": -0.097648,
                        "win_rate": 0.478261,
                        "drawdown": 1.402432,
                        "diagnosis_verdict": "insufficient_data",
                        "planner_recommendation": "insufficient_data_collect_more",
                        "next_required_action": "continue_research_for_liquidity_probe.steady_flow",
                        "next_recommended_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                        "paper_candidate_path": "research_only_profile_not_approved_for_paper",
                        "can_become_paper_candidate": "no",
                    },
                }

        main_module.StrategyPortfolioResearchPlannerReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.StrategyPortfolioResearchPlannerReport = original_reporter
            sys.argv = original_argv
        text = stdout.getvalue()
        self.assertIn("Selected Strategy Diagnostics", text)
        self.assertIn("timeframe=15Min", text)
        self.assertIn("sample_size=23", text)
        self.assertIn("diagnosis_verdict=insufficient_data", text)
        self.assertIn("Research-only. No paper or live approval has been changed.", text)

    def test_explicit_diagnosis_target_uses_requested_identity(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=23, net_avg=-0.097648, win_rate=0.478261),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=23, net_avg=-0.097648, win_rate=0.478261),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[{"variant_id": "holding-window-240", "net_return_after_costs": 0.547019, "win_rate": 0.682432, "beats_baseline": True, "beats_thresholds": True}],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=23,
                    net_return_after_costs=-0.097648,
                    win_rate=0.478261,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id v-snap --symbol WDC",
                    "reason": "Validate the subset only.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Flow profile has evidence but still needs more research.",
                },
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
            },
        )
        planner.variant_service = _StubVariantService(
            result={
                "baseline_metrics": {
                    "sample_size": 23,
                    "net_return_after_costs": -0.097648,
                    "win_rate": 0.478261,
                    "drawdown": 1.402432,
                }
            }
        )
        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )
        self.assertEqual(result["selected_next_strategy"]["base_strategy_id"], "liquidity_probe.steady_flow")
        self.assertEqual(result["research_run"]["base_strategy_id"], "liquidity_probe.steady_flow")

    def test_explicit_diagnosis_uses_bounded_research_without_full_prebuild(self) -> None:
        planner = _planner()
        calls: list[dict[str, object]] = []

        class _Service:
            def run_research(self, **kwargs):
                calls.append(dict(kwargs))
                return {
                    "base_strategy_id": kwargs["base_strategy_id"],
                    "profile_id": kwargs["profile_id"],
                    "timeframe": kwargs["timeframe"],
                }

        planner.variant_service = _Service()
        planner.build_report = lambda: (_ for _ in ()).throw(AssertionError("full planner prebuild should not run"))
        planner._evidence_snapshot = lambda **kwargs: {
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "sample_size": 0,
            "net_return_after_costs": 0.0,
            "win_rate": 0.0,
            "drawdown": None,
            "data_adequacy": {},
            "strategy_planner_recommendation": "",
            "strategy_planner_command": "",
            "loss_diagnosis_verdict": "",
        }

        planner.run_selected_strategy_diagnostics(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )

        self.assertTrue(calls)
        self.assertTrue(calls[0]["bounded_diagnosis"])

    def test_explicit_dip_rebound_diagnosis_stays_bounded_and_targeted(self) -> None:
        planner = _planner()
        calls: list[dict[str, object]] = []

        class _Service:
            def run_research(self, **kwargs):
                calls.append(dict(kwargs))
                return {
                    "base_strategy_id": kwargs["base_strategy_id"],
                    "profile_id": kwargs["profile_id"],
                    "timeframe": kwargs["timeframe"],
                }

        planner.variant_service = _Service()
        planner._evidence_snapshot = lambda **kwargs: {
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "sample_size": 3,
            "net_return_after_costs": -0.305701,
            "win_rate": 0.333333,
            "drawdown": 0.42881,
            "data_adequacy": {},
            "strategy_planner_recommendation": "test_target_multiple_variants",
            "strategy_planner_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
            "loss_diagnosis_verdict": "symbol_filter_problem",
        }

        planner.run_selected_strategy_diagnostics(
            base_strategy_id="crypto_research.dip_rebound",
            profile_id="dip_rebound",
            timeframe="15Min",
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["base_strategy_id"], "crypto_research.dip_rebound")
        self.assertEqual(calls[0]["profile_id"], "dip_rebound")
        self.assertEqual(calls[0]["timeframe"], "15Min")
        self.assertTrue(calls[0]["bounded_diagnosis"])

    def test_runtime_blocked_diagnosis_returns_safe_summary(self) -> None:
        planner = _planner()
        planner.variant_service = type(
            "_Service",
            (),
            {
                "run_research": lambda self, **_kwargs: {
                    "base_strategy_id": "liquidity_probe.steady_flow",
                    "profile_id": "steady_flow",
                    "timeframe": "15Min",
                }
            },
        )()
        planner._evidence_snapshot = lambda **kwargs: {
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "sample_size": 0,
            "net_return_after_costs": 0.0,
            "win_rate": 0.0,
            "drawdown": None,
            "data_adequacy": {"zero_decision_reason": "historical_bar_read_timeout"},
            "strategy_planner_recommendation": "",
            "strategy_planner_command": "",
            "loss_diagnosis_verdict": "",
        }

        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )

        self.assertEqual(result["diagnosis_summary"]["diagnosis_status"], "runtime_blocked")
        self.assertEqual(result["diagnosis_summary"]["runtime_blocker"], "historical_bar_read_timeout")
        self.assertEqual(result["diagnosis_summary"]["next_required_action"], "optimise_or_precompute_replay_dataset")
        self.assertEqual(result["diagnosis_summary"]["can_become_paper_candidate"], "no")
        self.assertEqual(
            result["diagnosis_summary"]["paper_candidate_path"],
            "research_only_profile_not_approved_for_paper",
        )

    def test_negative_momentum_diagnosis_becomes_deprioritised_and_returns_to_portfolio(self) -> None:
        planner = _planner()
        planner.variant_service = type(
            "_Service",
            (),
            {
                "run_research": lambda self, **_kwargs: {
                    "base_strategy_id": "momentum.strong",
                    "profile_id": "strong",
                    "timeframe": "15Min",
                }
            },
        )()
        planner._evidence_snapshot = lambda **kwargs: {
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "sample_size": 12 if kwargs["timeframe"] == "before" else 253,
            "net_return_after_costs": -0.309606 if kwargs["timeframe"] == "before" else -0.654163,
            "win_rate": 0.333333 if kwargs["timeframe"] == "before" else 0.217391,
            "drawdown": 1.508248,
            "data_adequacy": {},
            "strategy_planner_recommendation": "insufficient_data_collect_more" if kwargs["timeframe"] == "before" else "retire_or_deprioritise_strategy",
            "strategy_planner_command": (
                ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 15Min"
            ),
            "loss_diagnosis_verdict": "",
        }
        before_calls = {"count": 0}

        def _snapshot(**kwargs):
            before_calls["count"] += 1
            first = before_calls["count"] == 1
            return {
                "base_strategy_id": kwargs["base_strategy_id"],
                "profile_id": kwargs["profile_id"],
                "timeframe": kwargs["timeframe"],
                "sample_size": 12 if first else 253,
                "net_return_after_costs": -0.309606 if first else -0.654163,
                "win_rate": 0.333333 if first else 0.217391,
                "drawdown": 1.508248,
                "data_adequacy": {},
                "strategy_planner_recommendation": "insufficient_data_collect_more" if first else "retire_or_deprioritise_strategy",
                "strategy_planner_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 15Min",
                "loss_diagnosis_verdict": "",
            }

        planner._evidence_snapshot = _snapshot

        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="momentum.strong",
            profile_id="strong",
            timeframe="15Min",
        )

        self.assertEqual(result["before"]["sample_size"], 12)
        self.assertEqual(result["after"]["sample_size"], 253)
        self.assertEqual(result["after"]["strategy_planner_recommendation"], "retire_or_deprioritise_strategy")
        self.assertEqual(result["diagnosis_summary"]["diagnosis_verdict"], "deprioritise")
        self.assertEqual(result["diagnosis_summary"]["planner_recommendation"], "retire_or_deprioritise_strategy")
        self.assertEqual(result["diagnosis_summary"]["next_required_action"], "return_to_portfolio_planner")
        self.assertEqual(
            result["diagnosis_summary"]["next_recommended_command"],
            ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        )
        self.assertEqual(result["diagnosis_summary"]["can_become_paper_candidate"], "no")

    def test_deprioritised_momentum_is_not_reselected_by_planner_after_persisted_negative_evidence(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "15Min"},
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=191, net_avg=0.282029, win_rate=0.544503),
                _decision("momentum.strong", "strong", "15Min", outcomes_recorded=253, net_avg=-0.654163, win_rate=0.217391),
                _decision("momentum.balanced", "balanced", "15Min", outcomes_recorded=18, net_avg=-0.141203, win_rate=0.444444),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[{"variant_id": "v-snap", "net_return_after_costs": 0.547019, "win_rate": 0.682432, "beats_baseline": True, "beats_thresholds": True}],
                ),
                ("momentum.strong", "strong", "15Min"): _variant_report(
                    sample_size=253,
                    net_return_after_costs=-0.654163,
                    win_rate=0.217391,
                    variants=[],
                ),
                ("momentum.balanced", "balanced", "15Min"): _variant_report(
                    sample_size=18,
                    net_return_after_costs=-0.141203,
                    win_rate=0.444444,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id v-snap --symbol ADI",
                    "reason": "Validate the subset only.",
                },
                ("momentum.strong", "strong", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.strong --profile-id strong",
                    "reason": "No edge is visible in persisted replay evidence.",
                },
                ("momentum.balanced", "balanced", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.balanced --profile-id balanced --timeframe 15Min",
                    "reason": "More evidence is needed.",
                },
            },
            evaluations=[
                {
                    "base_strategy_id": "mean_reversion.snapback",
                    "profile_id": "snapback",
                    "timeframe": "1Hour",
                    "variant_id": "v-snap",
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "wider_period": True,
                        "symbol": "ADI",
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {"sample_size": 41, "net_return_after_costs": -0.08},
                    },
                }
            ],
        )

        built = planner.build_report()

        rows = {
            (item["base_strategy_id"], item["profile_id"], item["timeframe"]): item
            for item in built["ranked_strategies"]
        }
        self.assertEqual(rows[("momentum.strong", "strong", "15Min")]["research_status"], "deprioritise")
        self.assertEqual(
            built["next_actionable_research_candidate"],
            {
                "base_strategy_id": "momentum.balanced",
                "profile_id": "balanced",
                "timeframe": "15Min",
                "research_status": "insufficient_data",
                "data_gap_action": "",
                "reason": "",
            },
        )

    def test_explicit_balanced_15min_diagnosis_deprioritises_and_returns_to_portfolio_planner(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("momentum.balanced", "balanced", "15Min", outcomes_recorded=454, net_avg=-0.5906, win_rate=0.222467),
            ],
            variant_reports={
                ("momentum.balanced", "balanced", "15Min"): _variant_report(
                    sample_size=454,
                    net_return_after_costs=-0.5906,
                    win_rate=0.222467,
                    variants=[],
                ),
            },
            planner_reports={
                ("momentum.balanced", "balanced", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.balanced --profile-id balanced --timeframe 15Min",
                    "reason": "Persisted replay evidence remains weak, so this strategy should stay deprioritised until stronger evidence appears.",
                },
            },
        )
        planner.variant_service = _StubVariantService()
        snapshot_calls = {"count": 0}

        def _snapshot(**kwargs):
            snapshot_calls["count"] += 1
            first = snapshot_calls["count"] == 1
            return {
                "base_strategy_id": kwargs["base_strategy_id"],
                "profile_id": kwargs["profile_id"],
                "timeframe": kwargs["timeframe"],
                "sample_size": 0 if first else 454,
                "net_return_after_costs": 0.0 if first else -0.5906,
                "win_rate": 0.0 if first else 0.222467,
                "drawdown": None if first else 1.006512,
                "data_adequacy": {},
                "strategy_planner_recommendation": "insufficient_data_collect_more" if first else "retire_or_deprioritise_strategy",
                "strategy_planner_command": (
                    ".venv-mac/bin/python main.py --strategy-research-planner "
                    "--base-strategy momentum.balanced --profile-id balanced --timeframe 15Min"
                ),
                "loss_diagnosis_verdict": "",
            }

        planner._evidence_snapshot = _snapshot

        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="momentum.balanced",
            profile_id="balanced",
            timeframe="15Min",
        )

        self.assertEqual(planner.variant_service.calls[0]["bounded_diagnosis"], True)
        self.assertEqual(result["before"]["sample_size"], 0)
        self.assertEqual(result["after"]["sample_size"], 454)
        self.assertEqual(result["after"]["net_return_after_costs"], -0.5906)
        self.assertEqual(result["diagnosis_summary"]["win_rate"], 0.222467)
        self.assertEqual(result["diagnosis_summary"]["drawdown"], 1.006512)
        self.assertEqual(result["diagnosis_summary"]["diagnosis_verdict"], "deprioritise")
        self.assertEqual(result["diagnosis_summary"]["planner_recommendation"], "retire_or_deprioritise_strategy")
        self.assertEqual(result["diagnosis_summary"]["next_required_action"], "return_to_portfolio_planner")
        self.assertEqual(result["diagnosis_summary"]["paper_candidate_path"], "negative_replay_edge")
        self.assertEqual(result["diagnosis_summary"]["can_become_paper_candidate"], "no")
        self.assertEqual(
            result["diagnosis_summary"]["next_recommended_command"],
            ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        )

    def test_portfolio_planner_consumes_persisted_balanced_15min_deprioritisation_and_rotates_forward(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "15Min"},
                {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "1Day"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=191, net_avg=0.282029, win_rate=0.544503),
                _decision("momentum.balanced", "balanced", "15Min", outcomes_recorded=454, net_avg=-0.5906, win_rate=0.222467),
                _decision("momentum.strong", "strong", "1Day", outcomes_recorded=32, net_avg=-0.12, win_rate=0.4375),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[{"variant_id": "v-snap", "net_return_after_costs": 0.547019, "win_rate": 0.682432, "beats_baseline": True, "beats_thresholds": True}],
                ),
                ("momentum.balanced", "balanced", "15Min"): _variant_report(
                    sample_size=454,
                    net_return_after_costs=-0.5906,
                    win_rate=0.222467,
                    variants=[],
                ),
                ("momentum.strong", "strong", "1Day"): _variant_report(
                    sample_size=32,
                    net_return_after_costs=-0.12,
                    win_rate=0.4375,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id v-snap --symbol ADI",
                    "reason": "Validate the subset only.",
                },
                ("momentum.balanced", "balanced", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.balanced --profile-id balanced --timeframe 15Min",
                    "reason": "Persisted replay evidence remains weak, so this strategy should stay deprioritised until stronger evidence appears.",
                },
                ("momentum.strong", "strong", "1Day"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    "reason": "More evidence is needed.",
                },
            },
            evaluations=[
                {
                    "base_strategy_id": "mean_reversion.snapback",
                    "profile_id": "snapback",
                    "timeframe": "1Hour",
                    "variant_id": "v-snap",
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "wider_period": True,
                        "symbol": "ADI",
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {"sample_size": 41, "net_return_after_costs": -0.08},
                    },
                }
            ],
        )

        built = planner.build_report()
        balanced_row = next(
            item
            for item in built["ranked_strategies"]
            if item["base_strategy_id"] == "momentum.balanced" and item["profile_id"] == "balanced" and item["timeframe"] == "15Min"
        )

        self.assertEqual(balanced_row["research_status"], "deprioritise")
        self.assertEqual(
            built["next_actionable_research_candidate"],
            {
                "base_strategy_id": "momentum.strong",
                "profile_id": "strong",
                "timeframe": "1Day",
                "research_status": "insufficient_data",
                "data_gap_action": "",
                "reason": "",
            },
        )
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
        )
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")

    def test_portfolio_planner_does_not_reissue_same_diagnosis_for_negative_momentum_strong_1day(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "1Day"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=191, net_avg=0.282029, win_rate=0.544503),
                _decision("momentum.strong", "strong", "1Day", outcomes_recorded=14, net_avg=-1.331577, win_rate=0.0),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[{"variant_id": "v-snap", "net_return_after_costs": 0.547019, "win_rate": 0.682432, "beats_baseline": True, "beats_thresholds": True}],
                ),
                ("momentum.strong", "strong", "1Day"): _variant_report(
                    sample_size=14,
                    net_return_after_costs=-1.331577,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id v-snap --symbol ADI",
                    "reason": "Validate the subset only.",
                },
                ("momentum.strong", "strong", "1Day"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    "reason": "Persisted replay evidence is materially negative despite the thin sample, so it should not be re-diagnosed immediately.",
                },
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
            },
            evaluations=[
                {
                    "base_strategy_id": "momentum.strong",
                    "profile_id": "strong",
                    "timeframe": "1Day",
                    "variant_id": "research-autopilot",
                    "raw_json": {
                        "report_type": "research_autopilot_step_summary",
                        "step_advanced": "no",
                        "evidence_changed": "no",
                        "candidate_status_changed": "no",
                        "before_candidate": "momentum.strong/strong/1Day",
                        "after_candidate": "momentum.strong/strong/1Day",
                        "before_action": "continue_research_for_momentum.strong",
                        "after_action": "continue_research_for_momentum.strong",
                        "after_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    },
                },
                {
                    "base_strategy_id": "mean_reversion.snapback",
                    "profile_id": "snapback",
                    "timeframe": "1Hour",
                    "variant_id": "v-snap",
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "wider_period": True,
                        "symbol": "ADI",
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {"sample_size": 41, "net_return_after_costs": -0.08},
                    },
                }
            ],
        )

        built = planner.build_report()

        selected = next(
            item
            for item in built["ranked_strategies"]
            if item["base_strategy_id"] == "momentum.strong" and item["profile_id"] == "strong" and item["timeframe"] == "1Day"
        )
        self.assertEqual(selected["research_status"], "deprioritise")
        self.assertEqual(selected["latest_planner_recommendation"], "retire_or_deprioritise_strategy")
        self.assertIsNone(built["selected_next_strategy"])
        self.assertEqual(built["next_actionable_research_candidate"], None)
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")
        self.assertEqual(built["next_required_operator_action"], "generate_new_research_candidates")
        self.assertEqual(
            selected["latest_autopilot_no_progress"]["classification_reason"],
            "no_progress_after_research_step_with_negative_replay_edge",
        )

    def test_diagnosis_falls_back_to_existing_evidence_when_read_only_blocks_persistence(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=23, net_avg=-0.097648, win_rate=0.478261),
            ],
            variant_reports={
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=23,
                    net_return_after_costs=-0.097648,
                    win_rate=0.478261,
                    variants=[],
                ),
            },
            planner_reports={
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Flow profile has evidence but still needs more research.",
                },
            },
        )

        class _ReadOnlyBlockedVariantService:
            def run_research(self, **_kwargs):
                raise RuntimeError("cannot execute INSERT in a read-only transaction")

        planner.variant_service = _ReadOnlyBlockedVariantService()
        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )
        self.assertEqual(result["status"], "read_only_existing_evidence_only")
        self.assertEqual(result["diagnosis_summary"]["diagnosis_verdict"], "existing_evidence_only")
        self.assertEqual(result["diagnosis_summary"]["support_status"], "read_only_existing_evidence_only")

    def test_explicit_negative_thin_sample_diagnosis_is_insufficient_but_negative(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "1Day"},
            ],
            decisions=[
                _decision("momentum.strong", "strong", "1Day", outcomes_recorded=14, net_avg=-1.331577, win_rate=0.0),
            ],
            variant_reports={
                ("momentum.strong", "strong", "1Day"): _variant_report(
                    sample_size=14,
                    net_return_after_costs=-1.331577,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("momentum.strong", "strong", "1Day"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    "reason": "Persisted replay evidence is materially negative despite the thin sample.",
                },
            },
        )
        planner.variant_service = _StubVariantService()
        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="momentum.strong",
            profile_id="strong",
            timeframe="1Day",
        )

        self.assertEqual(result["diagnosis_summary"]["diagnosis_verdict"], "insufficient_but_negative")
        self.assertEqual(result["diagnosis_summary"]["next_required_action"], "return_to_portfolio_planner")
        self.assertEqual(result["diagnosis_summary"]["paper_candidate_path"], "negative_replay_edge")
        self.assertEqual(result["diagnosis_summary"]["can_become_paper_candidate"], "no")

    def test_diagnosis_marks_write_enabled_research_persistence_and_never_touches_paper_or_live(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            variant_reports={
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Flow profile needs more evidence.",
                },
            },
        )

        class _GuardedVariantService(_StubVariantService):
            def run_research(self, **kwargs):
                joined = " ".join(f"{key}={value}" for key, value in kwargs.items()).lower()
                assert "paper" not in joined
                assert "live" not in joined
                return super().run_research(**kwargs)

        planner.variant_service = _GuardedVariantService()
        result = planner.run_selected_strategy_diagnostics(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )
        self.assertEqual(result["status"], "executed_research_only")
        self.assertEqual(result["research_persistence_mode"], "write_enabled_research_only")
        self.assertEqual(result["diagnosis_summary"]["can_become_paper_candidate"], "no")
        self.assertEqual(
            result["diagnosis_summary"]["paper_candidate_path"],
            "research_only_profile_not_approved_for_paper",
        )

    def test_portfolio_planner_candidate_and_command_identity_match_after_stopped_snapback(self) -> None:
        planner = _planner(
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=191, net_avg=0.282029, win_rate=0.544503),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=23, net_avg=-0.097648, win_rate=0.478261),
            ],
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=191,
                    net_return_after_costs=0.282029,
                    win_rate=0.544503,
                    variants=[{"variant_id": "holding-window-240", "net_return_after_costs": 0.547019, "win_rate": 0.682432, "beats_baseline": True, "beats_thresholds": True}],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=23,
                    net_return_after_costs=-0.097648,
                    win_rate=0.478261,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id holding-window-240 --symbol WDC",
                    "reason": "Validate the subset only.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Flow profile has evidence but still needs more research.",
                },
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
            },
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {
                            "sample_size": 23,
                            "net_return_after_costs": -0.097648,
                            "drawdown": 1.402432,
                        },
                    }
                }
            ],
        )
        built = planner.build_report()
        self.assertEqual(built["selected_next_strategy"]["base_strategy_id"], "liquidity_probe.steady_flow")
        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "liquidity_probe.steady_flow")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
        )
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")
        self.assertNotEqual(built["selected_next_strategy"]["base_strategy_id"], "mean_reversion.snapback")

    def test_json_output_is_clean_parseable(self) -> None:
        original_reporter = main_module.StrategyPortfolioResearchPlannerReport
        original_argv = sys.argv
        previous_debug = os.environ.get("CENTAUR_DEBUG_DB_DIAGNOSTICS")
        sys.argv = ["main.py", "--strategy-portfolio-research-planner", "--json"]

        class _Reporter:
            def __init__(self):
                print("db_connection_diagnostic noisy=true", file=sys.stderr)

            def build_report(self):
                print("runtime_db_diagnostic noisy=true", file=sys.stderr)
                return {"title": "Strategy Portfolio Research Planner", "ok": True}

        main_module.StrategyPortfolioResearchPlannerReport = _Reporter
        stdout = StringIO()
        stderr = StringIO()
        os.environ.pop("CENTAUR_DEBUG_DB_DIAGNOSTICS", None)
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main_module.main()
        finally:
            main_module.StrategyPortfolioResearchPlannerReport = original_reporter
            sys.argv = original_argv
            if previous_debug is None:
                os.environ.pop("CENTAUR_DEBUG_DB_DIAGNOSTICS", None)
            else:
                os.environ["CENTAUR_DEBUG_DB_DIAGNOSTICS"] = previous_debug
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["ok"], True)
        self.assertEqual(stderr.getvalue(), "")

    def test_deprioritised_liquidity_probe_is_not_selected_again_after_adequate_negative_evidence(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=148,
                    net_return_after_costs=0.547019,
                    win_rate=0.682432,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=201,
                    net_return_after_costs=-0.448534,
                    win_rate=0.119403,
                    variants=[],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=17,
                    net_return_after_costs=0.021,
                    win_rate=0.52,
                    variants=[],
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "validate_symbol_subset_stability",
                    "proposed_next_command": ".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id holding-window-240 --symbol WDC",
                    "reason": "Validate the subset only.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Adequate replay evidence remains weak.",
                },
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Some usable evidence exists but the sample is still thin.",
                },
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "audit_status": "parked_until_new_data",
                },
            },
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_subset_stability",
                        "symbol": "WDC",
                        "wider_period": True,
                        "stability_verdict": "symbol_not_promising",
                        "selected_symbol_summary": {
                            "sample_size": 148,
                            "net_return_after_costs": 0.547019,
                            "drawdown": 0.82,
                        },
                    }
                }
            ],
            definitions=[
                {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
                {"base_strategy_id": "crypto_momentum.trend", "profile_id": "trend", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("mean_reversion.snapback", "snapback", "1Hour", outcomes_recorded=148, net_avg=0.547019, win_rate=0.682432),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=201, net_avg=-0.448534, win_rate=0.119403),
                _decision("crypto_momentum.trend", "trend", "15Min", outcomes_recorded=17, net_avg=0.021, win_rate=0.52),
            ],
        )
        built = planner.build_report()
        rows = {item["base_strategy_id"]: item for item in built["ranked_strategies"]}
        self.assertEqual(rows["liquidity_probe.steady_flow"]["research_status"], "deprioritise")
        self.assertEqual(built["selected_next_strategy"]["base_strategy_id"], "crypto_momentum.trend")
        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "crypto_momentum.trend")

    def test_runtime_blocked_dip_rebound_yields_data_runtime_action_not_bad_strategy(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=4,
                    variants_evaluated=4,
                    data_adequacy={"zero_decision_reason": "historical_bar_read_timeout"},
                ),
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): _variant_report(
                    sample_size=201,
                    net_return_after_costs=-0.448534,
                    win_rate=0.119403,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Replay attempts timed out before usable bars were loaded.",
                },
                ("liquidity_probe.steady_flow", "steady_flow", "15Min"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    "reason": "Adequate replay evidence remains weak.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
                {"base_strategy_id": "liquidity_probe.steady_flow", "profile_id": "steady_flow", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("liquidity_probe.steady_flow", "steady_flow", "15Min", outcomes_recorded=201, net_avg=-0.448534, win_rate=0.119403),
            ],
        )
        built = planner.build_report()
        dip = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_research.dip_rebound")
        self.assertEqual(dip["research_status"], "runtime_blocked")
        self.assertNotIn(
            "crypto_research.dip_rebound",
            {item["base_strategy_id"] for item in built["bad_strategies"]},
        )
        self.assertIsNone(built["selected_next_strategy"])
        self.assertEqual(built["next_portfolio_action"], "optimise_or_precompute_replay_dataset")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset",
        )
        self.assertEqual(
            built["next_data_runtime_action"]["data_or_runtime_action"],
            "optimise_or_precompute_crypto_replay_dataset",
        )

    def test_replay_prep_runtime_blocked_uses_specific_precompute_action_instead_of_generic_prep(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=4,
                    variants_evaluated=4,
                    data_adequacy={"zero_decision_reason": "historical_bar_read_timeout"},
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Replay attempts timed out before usable bars were loaded.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:15:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_still_slow",
                        "prep_action": "precompute_bounded_dip_rebound_15Min_outcomes",
                        "blocker_reason": "historical_bar_read_timeout / slow_reads",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertIsNone(built["selected_next_strategy"])
        self.assertEqual(built["next_portfolio_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(
            built["next_data_runtime_action"]["data_or_runtime_action"],
            "precompute_bounded_dip_rebound_15Min_outcomes",
        )
        self.assertEqual(
            built["next_safe_operator_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(built["precompute_mapping_attempted"], "yes")
        self.assertEqual(
            built["mapped_precompute_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(built["precompute_already_completed"], "no")
        self.assertEqual(built["why_next_safe_operator_command_blank"], "")

    def test_replay_prep_missing_crypto_1day_bars_produces_specific_backfill_action(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=1,
                    variants_evaluated=1,
                    data_adequacy={"zero_decision_reason": "no_bars_for_timeframe"},
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
                {"base_strategy_id": "crypto_momentum.trend", "profile_id": "trend", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", "1Day", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("crypto_momentum.trend", "trend", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_pullback",
                    "downside_reversal_watch",
                    "1Day",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:20:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "missing_timeframe_bars",
                        "prep_action": "backfill_or_resample_crypto_1Day_bars",
                        "blocker_reason": "0/11 symbols have usable 1Day crypto bars.",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "backfill_or_resample_data")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --backfill-or-resample-crypto-1day-bars",
        )
        self.assertEqual(
            built["next_data_runtime_action"]["data_or_runtime_action"],
            "backfill_or_resample_crypto_1Day_bars",
        )

    def test_runtime_blocked_dip_rebound_infers_exact_precompute_command_from_generic_cache_action(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "historical_bar_read_timeout"},
                ),
            },
            planner_reports={
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Replay attempts timed out before usable bars were loaded.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_research.dip_rebound",
                    "dip_rebound",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:15:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_still_slow",
                        "blocker_reason": "historical_bar_read_timeout / slow_reads",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_required_operator_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(
            built["next_safe_operator_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(built["precompute_mapping_attempted"], "yes")
        self.assertEqual(
            built["mapped_precompute_command"],
            ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
        )
        self.assertEqual(built["precompute_already_completed"], "no")

    def test_runtime_blocked_momentum_balanced_maps_generic_precompute_to_exact_command(self) -> None:
        planner = _planner(
            variant_reports={
                ("momentum.balanced", "balanced", "1Hour"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "historical_bar_read_timeout"},
                ),
            },
            planner_reports={
                ("momentum.balanced", "balanced", "1Hour"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                    "reason": "Replay attempts timed out before usable bars were loaded.",
                },
            },
            definitions=[
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "momentum.balanced",
                    "balanced",
                    "1Hour",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-11T09:15:00+01:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_still_slow",
                        "blocker_reason": "historical_bar_read_timeout / slow_reads",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_required_operator_action"], "precompute_specific_replay_cache")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --precompute-specific-replay-cache --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
        )
        self.assertEqual(
            built["next_safe_operator_command"],
            ".venv-mac/bin/python main.py --precompute-specific-replay-cache --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
        )
        self.assertEqual(built["precompute_mapping_attempted"], "yes")
        self.assertEqual(
            built["mapped_precompute_command"],
            ".venv-mac/bin/python main.py --precompute-specific-replay-cache --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
        )
        self.assertEqual(built["why_next_safe_operator_command_blank"], "")

    def test_replay_prep_no_usable_signals_produces_research_only_signal_action(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=3,
                    variants_evaluated=3,
                ),
            },
            definitions=[
                {"base_strategy_id": "crypto_momentum.trend", "profile_id": "trend", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_momentum.trend", "trend", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_momentum.trend",
                    "trend",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:25:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_no_signals",
                        "prep_action": "deprioritise_until_new_data",
                        "blocker_reason": "bars exist but no_usable_signals",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "adjust_signal_generation_research_only")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --signal-generation-diagnosis --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
        )
        self.assertEqual(
            built["next_data_runtime_action"]["data_or_runtime_action"],
            "deprioritise_until_new_data",
        )

    def test_signal_generation_diagnosis_output_is_consumed_as_follow_up_command(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=3,
                    variants_evaluated=3,
                ),
            },
            definitions=[
                {"base_strategy_id": "crypto_momentum.trend", "profile_id": "trend", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_momentum.trend", "trend", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_momentum.trend",
                    "trend",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:25:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_no_signals",
                        "prep_action": "deprioritise_until_new_data",
                        "blocker_reason": "bars exist but no_usable_signals",
                    },
                ),
                _evaluation(
                    "crypto_momentum.trend",
                    "trend",
                    "15Min",
                    variant_id="signal-generation-diagnosis",
                    evaluated_at="2026-06-09T11:30:00+00:00",
                    raw_json={
                        "report_type": "signal_generation_diagnosis",
                        "next_recommended_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "adjust_signal_generation_research_only")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
        )

    def test_range_breakout_stale_signal_generation_report_follow_up_is_normalized(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_research.range_breakout", "range_breakout", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=3,
                    variants_evaluated=3,
                ),
            },
            definitions=[
                {"base_strategy_id": "crypto_research.range_breakout", "profile_id": "range_breakout", "timeframe": "15Min"},
            ],
            decisions=[
                _decision("crypto_research.range_breakout", "range_breakout", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
            ],
            evaluations=[
                _evaluation(
                    "crypto_research.range_breakout",
                    "range_breakout",
                    "15Min",
                    variant_id="replay-dataset-preparation",
                    evaluated_at="2026-06-09T11:25:00+00:00",
                    raw_json={
                        "report_type": "replay_dataset_preparation",
                        "prep_status": "replay_prepared_but_no_signals",
                        "prep_action": "deprioritise_until_new_data",
                        "blocker_reason": "bars exist but no_usable_signals",
                    },
                ),
                _evaluation(
                    "crypto_research.range_breakout",
                    "range_breakout",
                    "15Min",
                    variant_id="signal-generation-diagnosis",
                    evaluated_at="2026-06-09T11:30:00+00:00",
                    raw_json={
                        "report_type": "signal_generation_diagnosis",
                        "next_recommended_command": ".venv-mac/bin/python main.py --strategy-variant-research-report --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    },
                ),
            ],
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "adjust_signal_generation_research_only")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
        )

    def test_zero_evidence_strategy_is_labelled_untested_with_clear_reason(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=148,
                    net_return_after_costs=0.547019,
                    win_rate=0.682432,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    variants_generated=0,
                    variants_evaluated=0,
                ),
            },
            planner_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "selected_experiment_type": "test_cost_expected_move_variants",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour",
                    "reason": "Retest expected move filters.",
                }
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "fragility_flags": ["too_few_samples", "one_month_dominates_profit"],
                }
            },
        )
        built = planner.build_report()
        row = next(item for item in built["ranked_strategies"] if item["base_strategy_id"] == "crypto_momentum.trend")
        self.assertEqual(row["research_status"], "untested_strategy")
        self.assertEqual(built["current_known_best_candidate"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_actionable_research_candidate"]["base_strategy_id"], "mean_reversion.snapback")

    def test_recently_attempted_zero_evidence_strategy_is_skipped(self) -> None:
        planner = _planner(
            selected_identity=("mean_reversion.snapback", "snapback", "1Hour"),
            variant_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): _variant_report(
                    sample_size=148,
                    net_return_after_costs=0.547019,
                    win_rate=0.682432,
                    variants=[
                        {
                            "variant_id": "holding-window-240",
                            "net_return_after_costs": 0.547019,
                            "win_rate": 0.682432,
                            "beats_baseline": True,
                            "beats_thresholds": True,
                        }
                    ],
                ),
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "baseline": {"variant_id": "baseline", "metrics": {"sample_size": 0, "net_return_after_costs": 0.0, "win_rate": 0.0}},
                    "variants_generated": 12,
                    "variants_evaluated": 0,
                    "variants": [],
                },
            },
            planner_reports={
                ("crypto_momentum.trend", "trend", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    "reason": "Already attempted but no evidence recorded yet.",
                }
            },
            audit_reports={
                ("mean_reversion.snapback", "snapback", "1Hour"): {
                    "audit_verdict": "paper_candidate_reject_due_to_concentration",
                    "fragility_flags": ["too_few_samples", "one_month_dominates_profit"],
                }
            },
        )
        built = planner.build_report()
        self.assertEqual(built["selected_next_strategy"]["base_strategy_id"], "mean_reversion.snapback")
        self.assertEqual(built["next_portfolio_action"], "collect_more_out_of_sample_data")

    def test_json_report_contains_new_structured_fields(self) -> None:
        planner = _planner()
        built = planner.build_report()
        for key in (
            "current_known_best_candidate",
            "why_not_selected_for_paper",
            "untested_strategies",
            "data_gap_strategies",
            "bad_strategies",
            "promising_but_failed_audit",
            "deprioritised_strategies",
            "stopped_failed_branches",
            "selected_next_strategy",
            "selected_next_experiment_type",
            "next_portfolio_action",
            "reason",
        ):
            self.assertIn(key, built)
        json.loads(json.dumps(built, default=str))

    def test_portfolio_planner_separates_data_gap_from_bad_strategies(self) -> None:
        planner = _planner(
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={"zero_decision_reason": "no_bars_for_timeframe", "total_bars": 0},
                ),
                ("momentum.balanced", "balanced", "1Hour"): _variant_report(
                    sample_size=64,
                    net_return_after_costs=-1.24,
                    win_rate=0.41,
                    variants=[],
                ),
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                ),
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                    "reason": "No bars exist for the requested timeframe.",
                },
                ("momentum.balanced", "balanced", "1Hour"): {
                    "selected_experiment_type": "retire_or_deprioritise_strategy",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.balanced --profile-id balanced",
                    "reason": "No edge is visible in persisted replay evidence.",
                },
                ("crypto_research.dip_rebound", "dip_rebound", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                    "reason": "Proceed with the next crypto research candidate.",
                },
            },
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
                {"base_strategy_id": "crypto_research.dip_rebound", "profile_id": "dip_rebound", "timeframe": "15Min"},
                {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "1Hour"},
            ],
            decisions=[
                _decision("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", "1Day", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("crypto_research.dip_rebound", "dip_rebound", "15Min", outcomes_recorded=0, net_avg=0.0, win_rate=0.0),
                _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=64, net_avg=-1.24, win_rate=0.41),
            ],
        )
        built = planner.build_report()
        self.assertIn("crypto_pullback", {item["base_strategy_id"] for item in built["data_gap_strategies"]})
        self.assertIn("momentum.balanced", {item["base_strategy_id"] for item in built["bad_strategies"]})
        self.assertNotIn("crypto_pullback", {item["base_strategy_id"] for item in built["bad_strategies"]})


class StrategyPortfolioResearchPlannerDataGapCommandTests(unittest.TestCase):
    def test_crypto_1day_data_gap_maps_to_exact_backfill_command(self) -> None:
        planner = _planner(
            selected_identity=("crypto_pullback", "downside_reversal_watch", "1Day"),
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
            ],
            decisions=[
                _decision(
                    "crypto_pullback.downside_reversal_watch",
                    "downside_reversal_watch",
                    "1Day",
                    outcomes_recorded=0,
                    net_avg=0.0,
                    win_rate=0.0,
                ),
            ],
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={
                        "dataset_id": "historical_crypto_bars:1Day:30d",
                        "zero_decision_reason": "no_bars_for_timeframe",
                    },
                ),
            },
            loss_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {},
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {},
            },
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "backfill_or_resample_data")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --backfill-or-resample-crypto-1day-bars",
        )
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --backfill-or-resample-crypto-1day-bars",
        )

    def test_crypto_15min_data_gap_maps_to_exact_backfill_command(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"),
            definitions=[
                {"base_strategy_id": "crypto_research.liquidation_wick_reclaim", "profile_id": "liquidation_wick_reclaim_confirmed", "timeframe": "15Min"},
            ],
            decisions=[
                _decision(
                    "crypto_research.liquidation_wick_reclaim",
                    "liquidation_wick_reclaim_confirmed",
                    "15Min",
                    outcomes_recorded=0,
                    net_avg=0.0,
                    win_rate=0.0,
                ),
            ],
            variant_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={
                        "dataset_id": "historical_crypto_bars:15Min:30d",
                        "zero_decision_reason": "no_bars_for_timeframe",
                    },
                ),
            },
            loss_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {},
            },
            planner_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {},
            },
        )

        built = planner.build_report()

        self.assertEqual(built["next_portfolio_action"], "backfill_or_resample_data")
        self.assertEqual(
            built["proposed_next_command"],
            ".venv-mac/bin/python main.py --backfill-or-resample-crypto-15min-bars",
        )
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --backfill-or-resample-crypto-15min-bars",
        )

    def test_newer_crypto_1day_readiness_clears_stale_missing_bar_flag(self) -> None:
        planner = _planner(
            selected_identity=("crypto_pullback", "downside_reversal_watch", "1Day"),
            definitions=[
                {"base_strategy_id": "crypto_pullback", "profile_id": "downside_reversal_watch", "timeframe": "1Day"},
            ],
            decisions=[
                _decision(
                    "crypto_pullback.downside_reversal_watch",
                    "downside_reversal_watch",
                    "1Day",
                    outcomes_recorded=0,
                    net_avg=0.0,
                    win_rate=0.0,
                ),
            ],
            variant_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={
                        "dataset_id": "historical_crypto_bars:1Day:30d",
                        "zero_decision_reason": "no_bars_for_timeframe",
                        "total_bars": 0,
                    },
                ),
            },
            loss_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {},
            },
            planner_reports={
                ("crypto_pullback", "downside_reversal_watch", "1Day"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_pullback --profile-id downside_reversal_watch --timeframe 1Day",
                    "reason": "Collect replay evidence after data preparation.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_pullback",
                    "downside_reversal_watch",
                    "1Day",
                    variant_id="historical-data-readiness",
                    evaluated_at="2026-06-09T22:58:36+01:00",
                    raw_json={
                        "report_type": "historical_crypto_1day_backfill_or_resample",
                        "dataset_id": "historical_crypto_bars:1Day",
                        "bars_generated": 4015,
                        "days_covered": 4015,
                        "data_gap_resolved": "yes",
                    },
                ),
            ],
        )

        built = planner.build_report()
        row = built["ranked_strategies"][0]

        self.assertEqual(row["research_status"], "insufficient_data")
        self.assertEqual(row["zero_decision_reason"], "")
        self.assertEqual(row["data_adequacy"]["total_bars"], 4015)

    def test_newer_crypto_15min_readiness_clears_stale_insufficient_history_flag(self) -> None:
        planner = _planner(
            selected_identity=("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"),
            definitions=[
                {"base_strategy_id": "crypto_research.liquidation_wick_reclaim", "profile_id": "liquidation_wick_reclaim_confirmed", "timeframe": "15Min"},
            ],
            decisions=[
                _decision(
                    "crypto_research.liquidation_wick_reclaim",
                    "liquidation_wick_reclaim_confirmed",
                    "15Min",
                    outcomes_recorded=0,
                    net_avg=0.0,
                    win_rate=0.0,
                ),
            ],
            variant_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): _variant_report(
                    sample_size=0,
                    net_return_after_costs=0.0,
                    win_rate=0.0,
                    variants=[],
                    data_adequacy={
                        "dataset_id": "historical_crypto_bars:15Min:30d",
                        "zero_decision_reason": "insufficient_crypto_history",
                        "total_bars": 4400,
                    },
                ),
            },
            loss_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {},
            },
            planner_reports={
                ("crypto_research.liquidation_wick_reclaim", "liquidation_wick_reclaim_confirmed", "15Min"): {
                    "selected_experiment_type": "insufficient_data_collect_more",
                    "proposed_next_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
                    "reason": "Retry variant research after data preparation.",
                },
            },
            evaluations=[
                _evaluation(
                    "crypto_research.liquidation_wick_reclaim",
                    "liquidation_wick_reclaim_confirmed",
                    "15Min",
                    variant_id="historical-data-readiness",
                    evaluated_at="2026-06-10T09:15:00+01:00",
                    raw_json={
                        "report_type": "historical_crypto_15min_backfill_or_resample",
                        "dataset_id": "historical_crypto_bars:15Min",
                        "bars_available": 95040,
                        "days_covered": 90,
                        "data_gap_resolved": "yes",
                    },
                ),
            ],
        )

        built = planner.build_report()
        row = built["ranked_strategies"][0]

        self.assertEqual(row["research_status"], "insufficient_data")
        self.assertEqual(row["zero_decision_reason"], "")
        self.assertEqual(row["data_adequacy"]["total_bars"], 95040)


def _planner(*, variant_reports=None, loss_reports=None, planner_reports=None, promotions=None, evaluations=None, selected_identity=None, audit_reports=None, definitions=None, decisions=None):
    selected_timeframe = selected_identity[2] if selected_identity else "15Min"
    planner = StrategyPortfolioResearchPlannerReport.__new__(StrategyPortfolioResearchPlannerReport)
    planner.config = object()
    planner.usage_ledger = _StubLedger(
        definitions=definitions or [
            {"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": selected_timeframe},
            {"base_strategy_id": "crypto_momentum.trend", "profile_id": "trend", "timeframe": "15Min"},
            {"base_strategy_id": "momentum.balanced", "profile_id": "balanced", "timeframe": "1Hour"},
            {"base_strategy_id": "momentum.strong", "profile_id": "strong", "timeframe": "1Day"},
        ],
        decisions=decisions or [
            _decision(
                "mean_reversion.snapback",
                "snapback",
                selected_timeframe,
                outcomes_recorded=21,
                net_avg=0.194383,
                win_rate=0.571429,
            ),
            _decision("momentum.balanced", "balanced", "1Hour", outcomes_recorded=64, net_avg=-1.24, win_rate=0.41),
            _decision("momentum.strong", "strong", "1Day", outcomes_recorded=58, net_avg=-0.91, win_rate=0.39),
            _decision("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", "1Hour", outcomes_recorded=45, net_avg=-1.43, win_rate=0.35),
        ],
        promotions=promotions,
        evaluations=evaluations,
    )
    planner.variant_reporter = _StubVariantReporter(
        variant_reports
        or {
            ("mean_reversion.snapback", "snapback", selected_timeframe): _variant_report(
                sample_size=21,
                net_return_after_costs=0.194383,
                win_rate=0.571429,
                variants=[
                    {
                        "variant_id": "v-snap",
                        "net_return_after_costs": 0.194383,
                        "win_rate": 0.571429,
                        "beats_baseline": True,
                        "beats_thresholds": False,
                    }
                ],
            ),
            ("crypto_momentum.trend", "trend", "15Min"): _variant_report(
                sample_size=0,
                net_return_after_costs=0.0,
                win_rate=0.0,
                variants=[],
            ),
            ("momentum.balanced", "balanced", "1Hour"): _variant_report(
                sample_size=64,
                net_return_after_costs=-1.24,
                win_rate=0.41,
                variants=[],
            ),
            ("momentum.strong", "strong", "1Day"): _variant_report(
                sample_size=58,
                net_return_after_costs=-0.91,
                win_rate=0.39,
                variants=[],
            ),
            ("crypto_pullback", "downside_reversal_watch", "1Hour"): {},
        }
    )
    planner.loss_reporter = _StubLossReporter(
        loss_reports
        or {
            ("mean_reversion.snapback", "snapback", selected_timeframe): {
                "verdict": "snapback_exit_logic_problem",
            },
            ("crypto_momentum.trend", "trend", "15Min"): {},
            ("momentum.balanced", "balanced", "1Hour"): {},
            ("momentum.strong", "strong", "1Day"): {},
            ("crypto_pullback", "downside_reversal_watch", "1Hour"): {},
        }
    )
    planner.strategy_planner = _StubStrategyPlanner(
        planner_reports
        or {
            ("mean_reversion.snapback", "snapback", selected_timeframe): {
                "selected_experiment_type": "validate_symbol_subset_stability",
                "proposed_next_command": f".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy mean_reversion.snapback --profile-id snapback --timeframe {selected_timeframe} --variant-id v-snap --symbol WDC",
                "reason": "Validate the only promising subset before adding any filter because the sample is still small.",
            },
            ("crypto_momentum.trend", "trend", "15Min"): {},
            ("momentum.balanced", "balanced", "1Hour"): {
                "selected_experiment_type": "retire_or_deprioritise_strategy",
                "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.balanced --profile-id balanced",
                "reason": "No edge is visible in persisted replay evidence.",
            },
            ("momentum.strong", "strong", "1Day"): {
                "selected_experiment_type": "retire_or_deprioritise_strategy",
                "proposed_next_command": ".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy momentum.strong --profile-id strong",
                "reason": "No edge is visible in persisted replay evidence.",
            },
            ("crypto_pullback", "downside_reversal_watch", "1Hour"): {
                "selected_experiment_type": "retire_or_deprioritise_strategy",
                "proposed_next_command": ".venv-mac/bin/python main.py --research-status",
                "reason": "Current crypto pullback evidence remains weak.",
            },
        }
    )
    planner.symbol_replay_evidence_reporter = object()
    planner.symbol_stability_reporter = object()
    planner.variant_service = _StubVariantService()
    planner.audit_reporter = _StubAuditReporter(audit_reports or {})
    planner._cached_strategy_evaluations = {}
    planner._cached_latest_autopilot_no_progress = {}
    return planner


def _variant_report(
    *,
    sample_size,
    net_return_after_costs,
    win_rate,
    variants,
    variants_generated=None,
    variants_evaluated=None,
    data_adequacy=None,
    runtime_summary=None,
):
    variant_rows = list(variants)
    baseline = {
        "sample_size": sample_size,
        "net_return_after_costs": net_return_after_costs,
        "win_rate": win_rate,
        "drawdown": 0.75,
    }
    return {
        "baseline": {
            "variant_id": "baseline",
            "metrics": baseline,
            "data_adequacy": dict(data_adequacy or {}),
        },
        "variants_generated": len(variant_rows) if variants_generated is None else variants_generated,
        "variants_evaluated": (1 + len(variant_rows)) if variants_evaluated is None else variants_evaluated,
        "variants": variant_rows,
        **dict(runtime_summary or {}),
    }


def _decision(strategy_id, profile_id, timeframe, *, outcomes_recorded, net_avg, win_rate, evaluated_at=None):
    return {
        "strategy_id": strategy_id,
        "profile_id": profile_id,
        "timeframe": timeframe,
        "outcomes_recorded": outcomes_recorded,
        "net_return_summary_json": {"avg_pct": net_avg},
        "win_rate_summary_json": {"avg": win_rate},
        "evaluated_at": evaluated_at,
        "raw_json": {},
    }


def _evaluation(base_strategy_id, profile_id, timeframe, *, variant_id, evaluated_at, raw_json=None):
    return {
        "base_strategy_id": base_strategy_id,
        "profile_id": profile_id,
        "timeframe": timeframe,
        "variant_id": variant_id,
        "evaluated_at": evaluated_at,
        "raw_json": dict(raw_json or {}),
    }


if __name__ == "__main__":
    unittest.main()
