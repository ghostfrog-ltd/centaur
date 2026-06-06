from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.framework.reporting.research_proof_vs_real import ResearchProofVsRealReport


class _Ledger:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return self.rows[:limit]


class ResearchProofVsRealReportTests(unittest.TestCase):
    def test_render_explains_why_real_has_no_candidates(self) -> None:
        report = ResearchProofVsRealReport(
            config=SimpleNamespace(
                research_min_windows=4,
                research_min_proposals=50,
                research_min_net_return_pct=0.10,
                research_min_net_win_rate=0.55,
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
            ),
            usage_ledger=_Ledger(
                [
                    {
                        "tick_id": "researchcycle-real",
                        "state_snapshot_json": {
                            "run": {
                                "pipeline": "research_cycle",
                                "source": "real_heartbeat",
                                "timeframe": "15Min",
                                "days": 5,
                                "max_replay_timestamps": 500,
                            },
                            "research_cycle": {
                                "strategy_profiles_evaluated": 9,
                                "replay_windows_tested": [{}, {}, {}, {}],
                                "paper_candidates_created": 0,
                                "paper_removal_candidates_created": 0,
                                "decisions": [
                                    {
                                        "strategy_id": "s1",
                                        "profile_id": "p1",
                                        "recommendation": "research_only",
                                        "proposals_created": 12,
                                        "outcomes_recorded": 0,
                                        "blocker_reasons": [
                                            "insufficient_sample_size",
                                            "paper_allocation_excludes_backtest_evidence",
                                        ],
                                    }
                                ],
                            },
                        },
                    }
                ]
            ),
        )
        report._proof_summary = lambda **_kwargs: {
            "inputs_summary": "proof",
            "strategies_evaluated": 1,
            "historical_windows_selected": 4,
            "replay_evidence_counts": "profiles_with_replay=1",
            "paper_sim_evidence_counts": "profiles_with_paper_sim=1",
            "usable_decision_count": 1,
            "candidate_count": 1,
            "removal_candidate_count": 0,
            "fitness_gates_applied": "proof",
            "thresholds_applied": "proof",
        }
        report._latest_real_cycle_row = lambda: report.usage_ledger.rows[0]

        rendered = report.render()

        self.assertIn("proof_candidate_count=1", rendered)
        self.assertIn("real_candidate_count=0", rendered)
        self.assertIn("proof_uses_synthetic_evidence=yes", rendered)
        self.assertIn("real_uses_stored_historical_bars=no", rendered)
        self.assertIn("real_raw_decisions_count=1", rendered)
        self.assertIn("real_rejected_decisions_count=1", rendered)
        self.assertIn(
            "why_proof_produces_candidates_but_real_does_not=proof_runner_uses_synthetic_replay_and_paper_sim_evidence,real_runtime_blocks_allocation_from_backtest_evidence,real_runtime_failed_sample_size_threshold",
            rendered,
        )


class RealLearningProofReportTests(unittest.TestCase):
    def test_real_learning_proof_does_not_fail_when_valid_replay_windows_exist(self) -> None:
        from app.framework.reporting.real_learning_proof import RealLearningProofReport

        report = RealLearningProofReport(
            config=SimpleNamespace(),
            usage_ledger=type(
                "_Ledger",
                (),
                {
                    "backend": "postgres",
                    "list_recent_tick_runs": lambda self, limit=400: [
                        {
                            "tick_id": "researchcycle-real",
                            "state_snapshot_json": {
                                "run": {
                                    "pipeline": "research_cycle",
                                    "source": "real_heartbeat",
                                },
                                "research_cycle": {
                                    "historical_windows_selected": 4,
                                    "latest_valid_replay_window_end": "2026-05-29T09:45:00+00:00",
                                    "strategy_profiles_evaluated": 1,
                                    "research_decisions_written": 1,
                                    "usable_decisions_count": 0,
                                    "paper_candidates_created": 0,
                                    "paper_removal_candidates_created": 0,
                                    "decisions": [
                                        {
                                            "strategy_id": "s1",
                                            "profile_id": "p1",
                                            "recommendation": "research_only",
                                            "proposals_created": 3,
                                            "blocker_reasons": ["insufficient_sample_size"],
                                        }
                                    ],
                                },
                            },
                        }
                    ],
                },
            )(),
        )

        built = report.build_report()

        self.assertTrue(built["real_learning_proven"])
        self.assertNotIn("no_valid_replay_windows", built["failure_reasons"])
        self.assertEqual(built["historical_windows_selected"], 4)
        self.assertEqual(built["profiles_with_replay"], 1)


if __name__ == "__main__":
    unittest.main()
