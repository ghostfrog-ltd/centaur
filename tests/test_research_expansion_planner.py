from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.framework.reporting.research_expansion_planner import ResearchExpansionPlannerReport


class _StubPortfolioPlanner:
    def __init__(self, report, refreshed_report=None):
        self.reports = [dict(report)]
        if refreshed_report is not None:
            self.reports.append(dict(refreshed_report))
        self.calls = 0

    def build_report(self):
        index = min(self.calls, len(self.reports) - 1)
        self.calls += 1
        return dict(self.reports[index])


class _StubWriteLedger:
    def __init__(self) -> None:
        self.rows = []

    def ensure_strategy_variant_definition(self, **kwargs):
        row = dict(kwargs)
        self.rows.append(row)
        return {"variant_id": kwargs["variant_id"]}


class _StubVariantService:
    def _resolve_profile(self, **_kwargs):
        return SimpleNamespace(
            parameters={
                "min_movement_pct": 0.12,
                "min_discovery_score": 3.0,
                "min_volume_ratio": 1.25,
                "min_atr_pct": 0.25,
            },
            holding_window_minutes=60,
            stop_loss_pct=0.01,
            target_multiple=2.0,
        )


class ResearchExpansionPlannerTests(unittest.TestCase):
    def test_exhausted_universe_returns_research_only_expansion_plan(self) -> None:
        report = ResearchExpansionPlannerReport.__new__(ResearchExpansionPlannerReport)
        report.portfolio_planner = _StubPortfolioPlanner(
            {
                "ranked_strategies": [],
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "research_expansion": {
                    "next_required_operator_action": "generate_new_research_candidates",
                    "next_research_expansion_action": "generate_new_strategy_family_research_only",
                    "next_recommended_command": ".venv-mac/bin/python main.py --research-expansion-planner",
                },
                "next_required_operator_action": "generate_new_research_candidates",
                "next_data_runtime_action": {},
                "next_actionable_research_candidate": {},
            }
        )
        built = report.build_report()
        self.assertEqual(built["research_universe_status"], "exhausted_current_strategy_set")
        self.assertEqual(built["next_research_expansion_action"], "generate_new_strategy_family_research_only")
        self.assertEqual(built["next_required_operator_action"], "generate_new_research_candidates")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["live_state"], "unchanged")
        self.assertEqual(built["threshold_state"], "unchanged")
        self.assertEqual(built["promotion_policy_state"], "unchanged")

    def test_generates_distinct_range_breakout_candidate_specs(self) -> None:
        report = ResearchExpansionPlannerReport.__new__(ResearchExpansionPlannerReport)
        report.config = SimpleNamespace()
        report.usage_ledger = SimpleNamespace()
        report.research_usage_ledger = _StubWriteLedger()
        report.variant_service = _StubVariantService()
        report.portfolio_planner = _StubPortfolioPlanner(
            {
                "ranked_strategies": [
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout_wide_signal",
                        "timeframe": "15Min",
                        "research_status": "insufficient_history_after_variant_research",
                        "generated_candidate_metadata": {
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                            "source_profile_id": "range_breakout",
                        },
                    }
                ],
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "research_expansion": {
                    "next_required_operator_action": "expand_signal_generation_research_only",
                    "next_research_expansion_action": "widen_range_breakout_signal_search_research_only",
                    "next_recommended_command": ".venv-mac/bin/python main.py --research-expansion-planner",
                },
                "next_required_operator_action": "expand_signal_generation_research_only",
                "next_data_runtime_action": {},
                "next_actionable_research_candidate": {},
            }
        )

        built = report.build_report()

        self.assertTrue(built["generated_candidate_specs"])
        spec = built["generated_candidate_specs"][0]
        self.assertEqual(spec["base_strategy_id"], "crypto_research.range_breakout")
        self.assertEqual(spec["profile_id"], "range_breakout_compression_release")
        self.assertEqual(spec["timeframe"], "1Hour")
        self.assertEqual(spec["paper_trading_allowed"], "no")
        self.assertEqual(spec["command_execution_mode"], "allowlisted_research_only")
        self.assertIn("--run-strategy-variant-research", spec["next_recommended_command"])
        self.assertIn("excludes the failed generated candidate", spec["why_this_is_different_from_failed_candidates"])
        self.assertEqual(report.research_usage_ledger.rows[0]["profile_id"], "range_breakout_compression_release")
        metadata = report.research_usage_ledger.rows[0]["params"]["__research_candidate_metadata__"]
        self.assertTrue(metadata["actionable_generated_candidate"])
        self.assertTrue(metadata["generated_at"])

    def test_failed_generated_candidate_is_excluded_until_newer_evidence_exists(self) -> None:
        report = ResearchExpansionPlannerReport.__new__(ResearchExpansionPlannerReport)
        report.config = SimpleNamespace()
        report.usage_ledger = SimpleNamespace()
        report.research_usage_ledger = _StubWriteLedger()
        report.variant_service = _StubVariantService()
        report.portfolio_planner = _StubPortfolioPlanner(
            {
                "ranked_strategies": [
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout_wide_signal",
                        "timeframe": "15Min",
                        "research_status": "insufficient_history_after_variant_research",
                        "generated_candidate_metadata": {"candidate_id": "wide-v1"},
                    },
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout_compression_release",
                        "timeframe": "1Hour",
                        "research_status": "insufficient_history_after_variant_research",
                        "generated_candidate_metadata": {"candidate_id": "compression-v1"},
                        "generated_candidate_zero_sample_outcome": {
                            "reason": "variant_research_completed_but_zero_samples",
                        },
                    },
                ],
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "research_expansion": {
                    "next_required_operator_action": "expand_signal_generation_research_only",
                    "next_research_expansion_action": "widen_range_breakout_signal_search_research_only",
                    "next_recommended_command": ".venv-mac/bin/python main.py --research-expansion-planner",
                },
                "next_required_operator_action": "expand_signal_generation_research_only",
                "next_data_runtime_action": {},
                "next_actionable_research_candidate": {},
            }
        )

        built = report.build_report()

        spec = built["generated_candidate_specs"][0]
        self.assertEqual(spec["generation_decision"], "generate_distinct_candidate")
        self.assertEqual(spec["profile_id"], "range_breakout_trend_reclaim")
        self.assertEqual(spec["timeframe"], "4Hour")
        self.assertEqual(built["previous_generated_candidate_excluded"], "yes")
        self.assertEqual(built["excluded_candidate"], "crypto_research.range_breakout/range_breakout_compression_release/1Hour")
        self.assertEqual(built["exclusion_reason"], "variant_research_completed_but_zero_samples")
        self.assertEqual(spec["paper_trading_allowed"], "no")
        self.assertEqual(report.research_usage_ledger.rows[0]["profile_id"], "range_breakout_trend_reclaim")

    def test_exhausted_universe_generates_new_liquidation_wick_family_candidate(self) -> None:
        report = ResearchExpansionPlannerReport.__new__(ResearchExpansionPlannerReport)
        report.config = SimpleNamespace()
        report.usage_ledger = SimpleNamespace()
        report.research_usage_ledger = _StubWriteLedger()
        report.variant_service = _StubVariantService()
        report.portfolio_planner = _StubPortfolioPlanner(
            {
                "ranked_strategies": [
                    {
                        "base_strategy_id": "mean_reversion.snapback",
                        "profile_id": "snapback",
                        "timeframe": "1Hour",
                        "research_status": "promising_but_failed_audit",
                    },
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout",
                        "timeframe": "15Min",
                        "research_status": "insufficient_history_after_variant_research",
                    },
                ],
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "research_expansion": {
                    "next_required_operator_action": "generate_new_research_candidates",
                    "next_research_expansion_action": "generate_new_strategy_family_research_only",
                    "next_recommended_command": ".venv-mac/bin/python main.py --research-expansion-planner",
                },
                "next_required_operator_action": "generate_new_research_candidates",
                "next_data_runtime_action": {},
                "next_actionable_research_candidate": {},
            }
        )

        built = report.build_report()

        self.assertTrue(built["generated_candidate_specs"])
        spec = built["generated_candidate_specs"][0]
        self.assertEqual(spec["base_strategy_id"], "crypto_research.liquidation_wick_reclaim")
        self.assertEqual(spec["profile_id"], "liquidation_wick_reclaim_confirmed")
        self.assertEqual(spec["timeframe"], "15Min")
        self.assertEqual(spec["asset_class"], "crypto")
        self.assertEqual(spec["paper_trading_allowed"], "no")
        self.assertEqual(spec["allowlist_status"], "allowlisted_research_only")
        self.assertIn("not a retry", spec["why_this_is_different_from_failed_candidates"])
        self.assertIn("--run-strategy-variant-research", spec["next_recommended_command"])
        self.assertEqual(report.research_usage_ledger.rows[0]["base_strategy_id"], "crypto_research.liquidation_wick_reclaim")
        metadata = report.research_usage_ledger.rows[0]["params"]["__research_candidate_metadata__"]
        self.assertEqual(metadata["source_profile_id"], "liquidation_wick_reclaim")
        self.assertTrue(metadata["research_only"])


if __name__ == "__main__":
    unittest.main()
