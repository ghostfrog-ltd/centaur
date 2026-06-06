from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.framework.reporting.real_learning_proof import RealLearningProofReport


class _Ledger:
    backend = "postgres"

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return self.rows[:limit]


class RealLearningProofReportTests(unittest.TestCase):
    def test_render_reports_pass_when_real_cycle_has_replay_evidence(self) -> None:
        report = RealLearningProofReport(
            config=SimpleNamespace(),
            usage_ledger=_Ledger(
                [
                    {
                        "state_snapshot_json": {
                            "run": {"pipeline": "research_cycle", "source": "real_heartbeat"},
                            "research_cycle": {
                                "historical_windows_selected": 4,
                                "strategy_profiles_evaluated": 2,
                                "research_decisions_written": 2,
                                "usable_decisions_count": 1,
                                "paper_candidates_created": 1,
                                "paper_removal_candidates_created": 0,
                                "decisions": [
                                    {
                                        "recommendation": "paper_sim_candidate",
                                        "proposals_created": 5,
                                        "blocker_reasons": [],
                                    },
                                    {
                                        "recommendation": "research_only",
                                        "proposals_created": 1,
                                        "blocker_reasons": ["insufficient_sample_size"],
                                    },
                                ],
                            },
                        }
                    }
                ]
            ),
        )

        rendered = report.render()

        self.assertIn("real_learning_proven=true", rendered)
        self.assertIn("historical_windows_selected=4", rendered)
        self.assertIn("profiles_with_replay=2", rendered)
        self.assertIn("raw_decisions_count=2", rendered)
        self.assertIn("evidence_decisions_count=1", rendered)
        self.assertIn("rejected_for_promotion_count=1", rendered)
        self.assertIn("promotion_eligible_count=1", rendered)
        self.assertIn("paper_candidates_created=1", rendered)
        self.assertIn("final_safety_summary=PASS", rendered)


if __name__ == "__main__":
    unittest.main()
