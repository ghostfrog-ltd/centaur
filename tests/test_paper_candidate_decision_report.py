from __future__ import annotations

import contextlib
import importlib
from io import StringIO
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

import main as main_module
from app.framework.reporting.paper_candidate_decision_report import (
    PaperCandidateDecisionReport,
    SAFETY_STATEMENT,
)
from app.framework.runtime.models import TickContext

execution_paper_module = importlib.import_module(
    "app.heartbeat.steps.30_execution_paper.implementation.main"
)
run_implementation = execution_paper_module.run_implementation


class _StubPortfolioPlanner:
    def __init__(self, report):
        self.report = dict(report)

    def build_report(self):
        return dict(self.report)


class _StubLedger:
    def __init__(self, promotions=None, evaluations=None):
        self.promotions = dict(promotions or {})
        self.evaluations = list(evaluations or [])
        self.record_calls = []
        self.evaluation_calls = []

    def get_strategy_promotion(self, *, strategy_id, profile_id):
        return dict(self.promotions.get((strategy_id, profile_id), {}))

    def record_paper_trade_orders(self, **kwargs):
        self.record_calls.append(dict(kwargs))
        return len(kwargs.get("orders", []) or [])

    def list_strategy_variant_evaluations(self, **_kwargs):
        self.evaluation_calls.append(dict(_kwargs))
        return list(self.evaluations)


class PaperCandidateDecisionReportTests(unittest.TestCase):
    def test_default_report_uses_read_only_skip_bootstrap_ledger(self) -> None:
        calls: list[dict[str, object]] = []
        original_usage_ledger = (
            PaperCandidateDecisionReport.__init__.__globals__["UsageLedger"]
        )

        class _StubLedger:
            def __init__(self, **kwargs: object) -> None:
                calls.append(dict(kwargs))

            def get_strategy_promotion(self, *, strategy_id, profile_id):
                _ = (strategy_id, profile_id)
                return {}

            def list_strategy_variant_evaluations(self, **_kwargs):
                return []

        PaperCandidateDecisionReport.__init__.__globals__["UsageLedger"] = _StubLedger
        try:
            report = PaperCandidateDecisionReport(config=SimpleNamespace())
        finally:
            PaperCandidateDecisionReport.__init__.__globals__["UsageLedger"] = (
                original_usage_ledger
            )

        self.assertIsInstance(report.usage_ledger, _StubLedger)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["read_only"])
        self.assertTrue(calls[0]["skip_schema_bootstrap"])
        self.assertEqual(calls[0]["query_timeout_ms"], 15000)
        self.assertIsNone(calls[0]["lock_timeout_ms"])

    def test_blocked_failed_audit_candidate_stays_non_executable(self) -> None:
        built = self._report().build_report()
        self.assertEqual(built["current_known_best_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertEqual(built["blocked_or_parked_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertIsNone(built["current_paper_candidate"])
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["paper_block_reason"], "concentration_fragility")
        self.assertEqual(built["blocked_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertEqual(built["blocked_reason"], "concentration_fragility")
        self.assertEqual(built["failed_audit_reason"], "paper_candidate_reject_due_to_concentration")
        self.assertEqual(built["branch_outcome"], "still_blocked")
        self.assertEqual(built["next_required_action"], "collect_more_out_of_sample_data")
        self.assertEqual(built["minimum_required_sample_size"], 200)
        self.assertIn(
            built["recommended_next_command"],
            {
                ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                ".venv-mac/bin/python main.py --collect-symbol-replay-evidence --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour --variant-id v-snap --symbol WDC",
            },
        )
        self.assertIn("no single-symbol concentration fragility", built["unblock_condition"])
        self.assertIn("remains negative, unstable, or concentrated", built["permanent_stop_condition"])
        self.assertEqual(built["wider_replay_execution_status"], "not_run")
        self.assertIn(built["rotation_required"], {"no", "yes"})
        self.assertEqual(built["next_actionable_research_candidate"], "")

    def test_parked_audit_keeps_candidate_blocked_and_not_reaudited_immediately(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    audit_report={
                        "audit_verdict": "paper_candidate_reject_due_to_concentration",
                        "audit_status": "parked_until_new_data",
                    },
                ),
                self._strategy(
                    base_strategy_id="crypto_momentum.trend",
                    profile_id="trend",
                    timeframe="15Min",
                    research_status="audit_required",
                    selected_variant_id="trend-audit",
                    selected_symbol="BTCUSD",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            next_paper_candidate={
                "base_strategy_id": "crypto_momentum.trend",
                "profile_id": "trend",
                "timeframe": "15Min",
            },
            selected_next_strategy={
                "base_strategy_id": "crypto_momentum.trend",
                "profile_id": "trend",
                "timeframe": "15Min",
            },
            proposed_next_command=".venv-mac/bin/python main.py --paper-candidate-audit --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min --variant-id trend-audit",
            next_portfolio_action="audit_paper_candidate",
        ).build_report()
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["blocked_or_parked_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertEqual(built["next_actionable_research_candidate"], "crypto_momentum.trend/trend/15Min")
        self.assertIn("crypto_momentum.trend", built["next_actionable_research_command"])
        self.assertNotIn("mean_reversion.snapback", built["next_actionable_research_command"])
        self.assertEqual(built["selected_next_strategy"], "crypto_momentum.trend/trend/15Min")
        self.assertEqual(built["next_portfolio_action"], "audit_paper_candidate")

    def test_persisted_negative_wider_replay_keeps_branch_blocked(self) -> None:
        built = self._report(
            evaluations=[
                {
                    "raw_json": {
                        "report_type": "symbol_replay_evidence_plan",
                        "symbol": "WDC",
                        "execution_status": "executed_research_only",
                        "evidence_action_verdict": "enough_existing_data_to_replay_more",
                        "executed_wider_stability_verdict": "no_usable_subset_data",
                        "executed_wider_symbol_summary": {
                            "sample_size": 31,
                            "net_return_after_costs": -0.07,
                            "drawdown": 1.4,
                        },
                    }
                }
            ],
        ).build_report()
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["branch_outcome"], "still_blocked")
        self.assertEqual(built["wider_replay_execution_status"], "executed_research_only")
        self.assertEqual(built["wider_replay_sample_size"], 31)
        self.assertEqual(built["wider_replay_net_return_after_costs"], -0.07)
        self.assertEqual(built["wider_replay_sample_size_adequate"], "no")
        self.assertEqual(built["wider_replay_symbol_diversity"], "unknown")
        self.assertEqual(built["latest_followup_verdict"], "no_usable_subset_data")
        self.assertEqual(built["paper_candidate_status"], "none_approved")
        self.assertEqual(built["rotation_required"], "yes")
        self.assertEqual(built["rotation_reason"], "followup_evidence_did_not_unblock_candidate")
        self.assertEqual(built["blocked_or_parked_candidate"], "mean_reversion.snapback/snapback/1Hour")

    def test_unresolved_follow_up_rotates_to_next_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    wide_symbol_stability={"stability_verdict": "no_usable_subset_data"},
                ),
                self._strategy(
                    base_strategy_id="crypto_momentum.trend",
                    profile_id="trend",
                    timeframe="15Min",
                    research_status="audit_required",
                    selected_variant_id="trend-audit",
                    selected_symbol="BTCUSD",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            next_paper_candidate={
                "base_strategy_id": "crypto_momentum.trend",
                "profile_id": "trend",
                "timeframe": "15Min",
            },
        ).build_report()
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["rotation_required"], "yes")
        self.assertEqual(built["next_candidate_to_review"], "crypto_momentum.trend/trend/15Min")
        self.assertEqual(built["next_actionable_research_candidate"], "crypto_momentum.trend/trend/15Min")
        self.assertEqual(
            built["next_actionable_research_reason"],
            "best_available_candidate_requires_read_only_audit_before_any_manual_paper_decision",
        )
        self.assertEqual(built["next_candidate_reason"], "best_available_candidate_requires_read_only_audit_before_any_manual_paper_decision")
        self.assertEqual(built["next_research_action"], "audit_paper_candidate")
        self.assertIn("--paper-candidate-audit", built["recommended_next_command"])

    def test_exhausted_universe_mirrors_planner_final_action(self) -> None:
        built = self._report(
            ranked_strategies=[],
            current_known_best_candidate={},
            blocked_or_parked_candidate={},
            selected_next_strategy={},
            next_actionable_research_candidate={},
            proposed_next_command=".venv-mac/bin/python main.py --research-expansion-planner",
            next_portfolio_action="generate_new_research_candidates",
            portfolio_research_status="no_actionable_candidate",
            research_universe_status="exhausted_current_strategy_set",
            next_required_operator_action="generate_new_research_candidates",
        ).build_report()
        self.assertEqual(built["portfolio_research_status"], "no_actionable_candidate")
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")
        self.assertEqual(built["next_required_operator_action"], "generate_new_research_candidates")
        self.assertEqual(built["recommended_next_command"], ".venv-mac/bin/python main.py --research-expansion-planner")
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["next_actionable_research_command"], built["recommended_next_command"])
        self.assertEqual(built["selected_next_strategy"], built["next_actionable_research_candidate"])
        self.assertEqual(built["next_portfolio_action"], built["next_research_action"])

    def test_generated_new_family_candidate_remains_research_only_in_decision_report(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="crypto_research.liquidation_wick_reclaim",
                    profile_id="liquidation_wick_reclaim_confirmed",
                    timeframe="15Min",
                    research_status="untested_strategy",
                    generated_candidate_metadata={
                        "candidate_id": "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1",
                        "source_profile_id": "liquidation_wick_reclaim",
                    },
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                "profile_id": "liquidation_wick_reclaim_confirmed",
                "timeframe": "15Min",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                "profile_id": "liquidation_wick_reclaim_confirmed",
                "timeframe": "15Min",
            },
            selected_next_strategy={
                "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                "profile_id": "liquidation_wick_reclaim_confirmed",
                "timeframe": "15Min",
            },
            next_actionable_research_candidate={
                "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                "profile_id": "liquidation_wick_reclaim_confirmed",
                "timeframe": "15Min",
            },
            proposed_next_command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
            next_portfolio_action="run_generated_variant_research",
            portfolio_research_status="research_in_progress",
            research_universe_status="active_current_strategy_set",
        ).build_report()
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertIn("liquidation_wick_reclaim_confirmed", built["recommended_next_command"])

    def test_report_keeps_candidate_identity_and_command_identity_aligned_for_diagnosis(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    wide_symbol_stability={"stability_verdict": "symbol_not_promising"},
                ),
                self._strategy(
                    base_strategy_id="liquidity_probe.steady_flow",
                    profile_id="steady_flow",
                    timeframe="15Min",
                    research_status="untested_strategy",
                    selected_variant_id="",
                    selected_symbol="",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            next_paper_candidate=None,
            selected_next_strategy={
                "base_strategy_id": "liquidity_probe.steady_flow",
                "profile_id": "steady_flow",
                "timeframe": "15Min",
            },
            next_actionable_research_candidate={
                "base_strategy_id": "liquidity_probe.steady_flow",
                "profile_id": "steady_flow",
                "timeframe": "15Min",
            },
            proposed_next_command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
            next_portfolio_action="diagnose_next_best_strategy",
        ).build_report()
        self.assertEqual(built["next_actionable_research_candidate"], "liquidity_probe.steady_flow/steady_flow/15Min")
        self.assertEqual(built["selected_next_strategy"], "liquidity_probe.steady_flow/steady_flow/15Min")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
        )
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")

    def test_only_manual_passing_audit_can_set_paper_trading_allowed_yes(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    research_status="paper_candidate_requires_manual_approval",
                    audit_report={"audit_verdict": "paper_candidate_audit_pass"},
                )
            ],
            promotions={("mean_reversion.snapback", "snapback"): {"paper_approved": True}},
        ).build_report()
        self.assertEqual(built["paper_candidate_status"], "eligible")
        self.assertEqual(built["paper_trading_allowed"], "yes")

    def test_data_gap_candidate_cannot_become_paper_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[self._strategy(research_status="data_gap", audit_report={})],
        ).build_report()
        self.assertIsNone(built["current_paper_candidate"])
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_block_reason"], "data_gap")
        self.assertEqual(built["paper_trading_allowed"], "no")

    def test_dip_rebound_next_research_candidate_remains_non_paper(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe="1Hour",
                    research_status="promising_but_failed_audit",
                    selected_variant_id="v-snap",
                    audit_report={
                        "audit_verdict": "paper_candidate_reject_due_to_concentration",
                        "audit_status": "blocked",
                    },
                ),
                self._strategy(
                    base_strategy_id="crypto_research.dip_rebound",
                    profile_id="dip_rebound",
                    timeframe="15Min",
                    research_status="active_research",
                    selected_variant_id="dip-v1",
                    selected_symbol="BTCUSD",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            next_paper_candidate=None,
            selected_next_strategy={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
            },
            next_actionable_research_candidate={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
            },
            proposed_next_command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
            next_portfolio_action="diagnose_next_best_strategy",
        ).build_report()
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertIsNone(built["current_paper_candidate"])
        self.assertEqual(built["next_actionable_research_candidate"], "crypto_research.dip_rebound/dip_rebound/15Min")
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")

    def test_post_precompute_negative_dip_rebound_remains_blocked_for_paper(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="crypto_research.dip_rebound",
                    profile_id="dip_rebound",
                    timeframe="15Min",
                    research_status="deprioritise_until_new_data",
                    latest_sample_size=3,
                    latest_net_return_after_costs=-0.305701,
                    latest_autopilot_no_progress={
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "precompute_completed_but_only_3_negative_samples",
                        "recorded_at": "2026-06-09T10:05:00+00:00",
                    },
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
            },
            selected_next_strategy=None,
            next_actionable_research_candidate=None,
            proposed_next_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            next_portfolio_action="no_actionable_candidate",
        ).build_report()

        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_block_reason"], "deprioritised")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["next_actionable_research_candidate"], "")

    def test_runtime_blocked_rotation_reports_data_runtime_action_when_no_candidate_is_actionable(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    research_status="promising_but_failed_audit",
                    wide_symbol_stability={"stability_verdict": "symbol_not_promising"},
                ),
                self._strategy(
                    base_strategy_id="crypto_research.dip_rebound",
                    profile_id="dip_rebound",
                    timeframe="15Min",
                    research_status="runtime_blocked",
                    latest_sample_size=0,
                    latest_net_return_after_costs=0.0,
                    selected_variant_id="",
                    selected_symbol="",
                    audit_report={},
                ),
                self._strategy(
                    base_strategy_id="liquidity_probe.steady_flow",
                    profile_id="steady_flow",
                    timeframe="15Min",
                    research_status="deprioritise",
                    latest_sample_size=201,
                    latest_net_return_after_costs=-0.448534,
                    selected_variant_id="",
                    selected_symbol="",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            selected_next_strategy=None,
            next_actionable_research_candidate=None,
            next_data_runtime_action={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
                "action": "optimise_or_precompute_replay_dataset",
                "data_or_runtime_action": "optimise_or_precompute_crypto_replay_dataset",
                "runtime_blocker": "historical_bar_read_timeout",
                "reason": "Replay diagnosis is blocked by runtime/data access.",
            },
            proposed_next_command=".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset",
            next_portfolio_action="optimise_or_precompute_replay_dataset",
        ).build_report()
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["next_actionable_research_candidate"], "")
        self.assertEqual(built["next_actionable_research_command"], "")
        self.assertEqual(built["next_portfolio_action"], "optimise_or_precompute_replay_dataset")
        self.assertEqual(built["next_research_action"], "optimise_or_precompute_replay_dataset")
        self.assertEqual(built["next_required_operator_action"], "optimise_or_precompute_crypto_replay_dataset")
        self.assertEqual(built["recommended_next_command"], ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset")

    def test_no_actionable_candidate_keeps_paper_blocked_after_autopilot_deprioritisation(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="crypto_research.dip_rebound",
                    profile_id="dip_rebound",
                    timeframe="1Hour",
                    research_status="deprioritise",
                    latest_sample_size=41,
                    latest_net_return_after_costs=-0.62,
                    latest_autopilot_no_progress={
                        "classification_applied": "deprioritise_until_new_data",
                        "classification_reason": "no_progress_after_research_step_with_negative_replay_edge",
                        "recorded_at": "2026-06-09T10:00:00+00:00",
                    },
                    autopilot_classification_timestamp="2026-06-09T10:00:00+00:00",
                    latest_strategy_evidence_timestamp="",
                    latest_variant_evaluation_timestamp="",
                    latest_diagnosis_timestamp="",
                    latest_symbol_stability_timestamp="",
                    latest_relevant_evidence_timestamp="",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "1Hour",
            },
            selected_next_strategy=None,
            next_actionable_research_candidate=None,
            proposed_next_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            next_portfolio_action="no_actionable_candidate",
        ).build_report()
        self.assertEqual(built["current_known_best_candidate"], "crypto_research.dip_rebound/dip_rebound/1Hour")
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["next_actionable_research_candidate"], "")
        self.assertEqual(built["next_actionable_research_command"], "")
        self.assertEqual(built["next_portfolio_action"], "no_actionable_candidate")
        self.assertEqual(built["next_required_operator_action"], "no_actionable_candidate")
        self.assertEqual(built["terminal_research_state"], "")

    def test_no_actionable_candidate_does_not_resurrect_stale_next_paper_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    research_status="promising_but_failed_audit",
                    audit_report={
                        "audit_verdict": "paper_candidate_reject_due_to_concentration",
                        "audit_status": "parked_until_new_data",
                    },
                ),
                self._strategy(
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe="15Min",
                    research_status="deprioritise",
                    latest_sample_size=87,
                    latest_net_return_after_costs=-0.41,
                    selected_variant_id="snap-15",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            next_paper_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
            },
            selected_next_strategy=None,
            next_actionable_research_candidate=None,
            next_data_runtime_action={
                "base_strategy_id": "crypto_research.dip_rebound",
                "profile_id": "dip_rebound",
                "timeframe": "15Min",
                "action": "optimise_or_precompute_replay_dataset",
                "data_or_runtime_action": "precompute_bounded_dip_rebound_15Min_outcomes",
                "runtime_blocker": "historical_bar_read_timeout",
                "reason": "Replay preparation completed, but runtime reads are still too slow for a bounded replay step.",
            },
            proposed_next_command=".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset",
            next_portfolio_action="optimise_or_precompute_replay_dataset",
        ).build_report()
        self.assertEqual(built["current_known_best_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["next_candidate_to_review"], "")
        self.assertEqual(built["next_actionable_research_candidate"], "")
        self.assertEqual(built["next_actionable_research_command"], "")
        self.assertEqual(built["next_required_operator_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(built["next_portfolio_action"], "optimise_or_precompute_replay_dataset")

    def test_no_actionable_candidate_operational_plan_is_mirrored_from_planner(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="crypto_research.range_breakout",
                    profile_id="range_breakout_wide_signal",
                    timeframe="15Min",
                    research_status="insufficient_history_after_variant_research",
                    latest_sample_size=0,
                    latest_net_return_after_costs=0.0,
                    generated_candidate_zero_sample_outcome={
                        "reason": "variant_research_completed_but_zero_samples",
                    },
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "crypto_research.range_breakout",
                "profile_id": "range_breakout_wide_signal",
                "timeframe": "15Min",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "crypto_research.range_breakout",
                "profile_id": "range_breakout_wide_signal",
                "timeframe": "15Min",
            },
            selected_next_strategy={},
            next_actionable_research_candidate={},
            proposed_next_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            next_portfolio_action="no_actionable_candidate",
            portfolio_research_status="no_actionable_candidate",
            research_universe_status="waiting_for_new_data",
            next_required_operator_action="no_actionable_candidate",
            terminal_research_state="generate_new_strategy_family_or_wait_for_new_market_data",
            no_actionable_reason="All current and generated candidates are exhausted, blocked, or zero-sample.",
            next_safe_operator_action="wait_for_new_market_data_or_generate_new_strategy_family",
            next_check_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        ).build_report()
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(
            built["terminal_research_state"],
            "generate_new_strategy_family_or_wait_for_new_market_data",
        )
        self.assertEqual(
            built["no_actionable_reason"],
            "All current and generated candidates are exhausted, blocked, or zero-sample.",
        )
        self.assertEqual(
            built["next_safe_operator_action"],
            "wait_for_new_market_data_or_generate_new_strategy_family",
        )
        self.assertEqual(
            built["next_check_command"],
            ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        )

    def test_insufficient_data_candidate_cannot_become_paper_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[self._strategy(research_status="insufficient_data", audit_report={})],
        ).build_report()
        self.assertIsNone(built["current_paper_candidate"])
        self.assertEqual(built["paper_block_reason"], "insufficient_data")
        self.assertEqual(built["paper_trading_allowed"], "no")

    def test_zero_sample_generated_variant_candidate_remains_blocked_for_paper(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="crypto_research.range_breakout",
                    profile_id="range_breakout_wide_signal",
                    timeframe="15Min",
                    research_status="no_viable_signal_after_variant_research",
                    latest_sample_size=0,
                    latest_net_return_after_costs=0.0,
                    audit_report={},
                )
            ],
            current_known_best_candidate={
                "base_strategy_id": "crypto_research.range_breakout",
                "profile_id": "range_breakout_wide_signal",
                "timeframe": "15Min",
            },
        ).build_report()
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_block_reason"], "deprioritised")
        self.assertEqual(built["paper_trading_allowed"], "no")

    def test_deprioritised_candidate_cannot_become_paper_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[self._strategy(research_status="deprioritise", audit_report={})],
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
        ).build_report()
        self.assertIsNone(built["current_paper_candidate"])
        self.assertEqual(built["paper_block_reason"], "deprioritised")
        self.assertEqual(built["paper_trading_allowed"], "no")

    def test_deprioritised_balanced_15min_rotation_keeps_paper_blocked_and_advances_to_next_candidate(self) -> None:
        built = self._report(
            ranked_strategies=[
                self._strategy(
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe="1Hour",
                    research_status="promising_but_failed_audit",
                    latest_sample_size=191,
                    latest_net_return_after_costs=0.282029,
                    selected_variant_id="v-snap",
                    selected_symbol="ADI",
                    audit_report={
                        "audit_verdict": "paper_candidate_reject_due_to_concentration",
                        "audit_status": "parked_until_new_data",
                    },
                    wide_symbol_stability={"stability_verdict": "symbol_not_promising"},
                ),
                self._strategy(
                    base_strategy_id="momentum.balanced",
                    profile_id="balanced",
                    timeframe="15Min",
                    research_status="deprioritise",
                    latest_sample_size=454,
                    latest_net_return_after_costs=-0.5906,
                    selected_variant_id="",
                    selected_symbol="",
                    audit_report={},
                ),
                self._strategy(
                    base_strategy_id="momentum.strong",
                    profile_id="strong",
                    timeframe="1Day",
                    research_status="insufficient_data",
                    latest_sample_size=32,
                    latest_net_return_after_costs=-0.12,
                    selected_variant_id="",
                    selected_symbol="",
                    audit_report={},
                ),
            ],
            current_known_best_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            blocked_or_parked_candidate={
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            selected_next_strategy={
                "base_strategy_id": "momentum.strong",
                "profile_id": "strong",
                "timeframe": "1Day",
            },
            next_actionable_research_candidate={
                "base_strategy_id": "momentum.strong",
                "profile_id": "strong",
                "timeframe": "1Day",
            },
            proposed_next_command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
            next_portfolio_action="diagnose_next_best_strategy",
        ).build_report()
        self.assertEqual(built["paper_candidate_status"], "blocked")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["blocked_or_parked_candidate"], "mean_reversion.snapback/snapback/1Hour")
        self.assertEqual(built["next_actionable_research_candidate"], "momentum.strong/strong/1Day")
        self.assertEqual(
            built["next_actionable_research_command"],
            ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
        )
        self.assertEqual(built["next_portfolio_action"], "diagnose_next_best_strategy")

    def test_cli_renders_read_only_decision_report(self) -> None:
        original_reporter = main_module.PaperCandidateDecisionReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--paper-candidate-decision-report"]

        class _Reporter:
            def __init__(self):
                print("db_connection_diagnostic noisy=true", file=sys.stderr)

            def render(self):
                print("runtime_db_diagnostic noisy=true", file=sys.stderr)
                return (
                    "Paper Candidate Decision Report\n"
                    "Final Summary\n"
                    "current_known_best_candidate=mean_reversion.snapback/snapback/1Hour\n"
                    "current_paper_candidate=\n"
                    "paper_candidate_status=blocked\n"
                    "paper_trading_allowed=no\n"
                    "blocked_or_parked_candidate=mean_reversion.snapback/snapback/1Hour\n"
                    "next_actionable_research_candidate=crypto_momentum.trend/trend/15Min\n"
                    "next_actionable_research_reason=research_only_follow_up\n"
                    "next_actionable_research_command=.venv-mac/bin/python main.py --strategy-portfolio-research-planner\n"
                    f"{SAFETY_STATEMENT}"
                )

        main_module.PaperCandidateDecisionReport = _Reporter
        stdout = StringIO()
        stderr = StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main_module.main()
        finally:
            main_module.PaperCandidateDecisionReport = original_reporter
            sys.argv = original_argv
        text = stdout.getvalue()
        self.assertIn("Paper Candidate Decision Report", text)
        self.assertIn("Final Summary", text)
        self.assertIn("current_known_best_candidate=mean_reversion.snapback/snapback/1Hour", text)
        self.assertIn("paper_trading_allowed=no", text)
        self.assertIn("diagnostics_suppressed=2", text)
        self.assertIn(SAFETY_STATEMENT, text)
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_verbose_mode_keeps_diagnostics_visible(self) -> None:
        original_reporter = main_module.PaperCandidateDecisionReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--paper-candidate-decision-report", "--verbose"]

        class _Reporter:
            def __init__(self):
                print("db_connection_diagnostic noisy=true", file=sys.stderr)

            def render(self):
                return "Paper Candidate Decision Report\nFinal Summary\npaper_trading_allowed=no"

        main_module.PaperCandidateDecisionReport = _Reporter
        stdout = StringIO()
        stderr = StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main_module.main()
        finally:
            main_module.PaperCandidateDecisionReport = original_reporter
            sys.argv = original_argv
        self.assertIn("paper_trading_allowed=no", stdout.getvalue())
        self.assertIn("db_connection_diagnostic noisy=true", stderr.getvalue())

    def test_execution_guard_blocks_paper_orders_when_report_says_no(self) -> None:
        original_reporter = run_implementation.__globals__["PaperCandidateDecisionReport"]

        class _Reporter:
            def __init__(self, **_kwargs):
                pass

            def build_report(self):
                return {
                    "paper_trading_allowed": "no",
                    "paper_candidate_status": "blocked",
                    "paper_block_reason": "concentration_fragility",
                    "failed_audit_reason": "paper_candidate_reject_due_to_concentration",
                    "current_known_best_candidate": "mean_reversion.snapback/snapback/1Hour",
                    "current_paper_candidate": None,
                }

        run_implementation.__globals__["PaperCandidateDecisionReport"] = _Reporter
        ledger = _StubLedger()
        context = TickContext(
            tick_id="tick-1",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
            ),
            usage_ledger=ledger,
            state={
                "risk_cfo": {
                    "approved_order_requests": [
                        {
                            "proposal_id": "proposal-1",
                            "broker_id": "alpaca_paper",
                            "strategy_id": "mean_reversion.snapback",
                            "strategy_family": "mean_reversion",
                            "profile_id": "snapback",
                            "source": "shadow",
                            "asset_class": "equity",
                            "symbol": "WDC",
                        }
                    ]
                }
            },
        )
        try:
            result = run_implementation(context)
        finally:
            run_implementation.__globals__["PaperCandidateDecisionReport"] = original_reporter
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["orders_saved"], 0)
        self.assertEqual(result["execution_status"], "blocked")
        self.assertEqual(result["reason"], "paper_trading_not_allowed")
        self.assertEqual(ledger.record_calls, [])

    def _report(self, **overrides):
        report = PaperCandidateDecisionReport.__new__(PaperCandidateDecisionReport)
        report.config = object()
        ledger = _StubLedger(
            promotions=overrides.pop("promotions", None),
            evaluations=overrides.pop("evaluations", None),
        )
        report.usage_ledger = ledger
        planner_report = {
            "ranked_strategies": [self._strategy()],
            "current_known_best_candidate": {
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            "blocked_or_parked_candidate": {
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
            },
            "next_paper_candidate": None,
            "stopped_branch": "",
            "stopped_reason": "",
            "wide_sample_size": 0,
            "wide_net_return_after_costs": 0.0,
            "proposed_next_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            "next_portfolio_action": "collect_more_out_of_sample_data",
            "terminal_research_state": "",
            "no_actionable_reason": "",
            "next_safe_operator_action": "",
            "next_check_command": "",
        }
        planner_report.update(overrides)
        report.portfolio_planner = _StubPortfolioPlanner(planner_report)
        return report

    def _strategy(self, **overrides):
        row = {
            "base_strategy_id": "mean_reversion.snapback",
            "profile_id": "snapback",
            "timeframe": "1Hour",
            "research_status": "promising_but_failed_audit",
            "latest_sample_size": 191,
            "latest_net_return_after_costs": 0.282029,
            "selected_variant_id": "holding-window-240",
            "selected_symbol": "WDC",
            "stopped_branch_name": "snapback_WDC",
            "audit_report": {"audit_verdict": "paper_candidate_reject_due_to_concentration"},
        }
        row.update(overrides)
        return row


if __name__ == "__main__":
    unittest.main()
