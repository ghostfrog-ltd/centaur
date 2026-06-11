from __future__ import annotations

import unittest

from app.framework.reporting.generated_candidate_state_report import GeneratedCandidateStateReport


class _StubPlanner:
    def __init__(self, report):
        self.report = dict(report)

    def build_report(self):
        return dict(self.report)

    def _is_actionable_research_candidate(self, item, *, blocked_or_parked_candidate, ranked):
        return str(item.get("profile_id", "") or "") == "range_breakout_compression_release"

    def _summary_identity(self, item):
        if not item:
            return ""
        return (
            f"{item.get('base_strategy_id', '')}/"
            f"{item.get('profile_id', '')}/"
            f"{item.get('timeframe', '')}"
        )

    def _generated_candidate_ineligible_reason(self, item):
        if str(item.get("profile_id", "") or "") == "range_breakout_wide_signal":
            return "generated_candidate_latest_variant_evidence_is_zero_sample"
        return ""


class GeneratedCandidateStateReportTests(unittest.TestCase):
    def test_eligible_generated_candidate_does_not_report_exclusion_reason(self) -> None:
        reporter = GeneratedCandidateStateReport.__new__(GeneratedCandidateStateReport)
        reporter.planner = _StubPlanner(
            {
                "ranked_strategies": [
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout_compression_release",
                        "timeframe": "1Hour",
                        "research_status": "insufficient_data",
                        "generated_candidate_lifecycle_status": "generated_not_evaluated",
                        "generated_candidate_metadata": {
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
                            "generated_at": "2026-06-10T09:07:59+01:00",
                            "evaluation_status": "evaluated",
                            "generated_candidate_evidence_at": "2026-06-10T09:12:59+01:00",
                        },
                        "latest_autopilot_no_progress": {
                            "classification_reason": "variant_research_completed_but_same_generated_candidate_remains_next_action",
                        },
                    }
                ],
                "portfolio_research_status": "research_in_progress",
                "research_universe_status": "active_current_strategy_set",
                "next_actionable_research_candidate": {
                    "base_strategy_id": "crypto_research.range_breakout",
                    "profile_id": "range_breakout_compression_release",
                    "timeframe": "1Hour",
                },
                "next_actionable_research_command": ".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                "next_portfolio_action": "run_generated_variant_research",
            }
        )

        built = reporter.build_report()

        self.assertEqual(built["next_actionable_research_candidate"], "crypto_research.range_breakout/range_breakout_compression_release/1Hour")
        self.assertEqual(len(built["generated_candidates"]), 1)
        row = built["generated_candidates"][0]
        self.assertEqual(row["eligible_for_portfolio_selection"], "yes")
        self.assertEqual(row["excluded_from_planner"], "no")
        self.assertEqual(row["exclusion_reason"], "")
        self.assertEqual(row["generated_candidate_evidence_at"], "2026-06-10T09:12:59+01:00")

    def test_zero_sample_generated_candidate_reports_diagnosis_ineligibility(self) -> None:
        reporter = GeneratedCandidateStateReport.__new__(GeneratedCandidateStateReport)
        reporter.planner = _StubPlanner(
            {
                "ranked_strategies": [
                    {
                        "base_strategy_id": "crypto_research.range_breakout",
                        "profile_id": "range_breakout_wide_signal",
                        "timeframe": "15Min",
                        "research_status": "insufficient_data",
                        "generated_candidate_lifecycle_status": "variant_research_completed",
                        "generated_candidate_metadata": {
                            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
                            "generated_at": "2026-06-10T09:07:59+01:00",
                            "evaluation_status": "evaluated_no_samples",
                            "generated_candidate_evidence_at": "2026-06-10T11:54:43+01:00",
                            "baseline_sample_size": 0,
                            "best_variant_sample_size": 0,
                        },
                        "generated_candidate_zero_sample_outcome": {
                            "reason": "variant_research_completed_but_zero_samples",
                            "baseline_sample_size": 0,
                            "best_variant_sample_size": 0,
                        },
                    }
                ],
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "next_actionable_research_candidate": {},
                "next_actionable_research_command": ".venv-mac/bin/python main.py --research-expansion-planner",
                "next_portfolio_action": "expand_signal_generation_research_only",
            }
        )

        built = reporter.build_report()

        row = built["generated_candidates"][0]
        self.assertEqual(row["baseline_sample_size"], 0)
        self.assertEqual(row["best_variant_sample_size"], 0)
        self.assertEqual(row["eligible_for_diagnosis"], "no")
        self.assertEqual(row["eligible_for_portfolio_selection"], "no")
        self.assertEqual(
            row["reason_if_not_diagnosis_eligible"],
            "generated_candidate_latest_variant_evidence_is_zero_sample",
        )
        self.assertEqual(
            row["reason_if_not_eligible"],
            "generated_candidate_latest_variant_evidence_is_zero_sample",
        )


if __name__ == "__main__":
    unittest.main()
