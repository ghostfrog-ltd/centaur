from __future__ import annotations

from datetime import datetime
import unittest

from app.framework.reporting.research_cycle_status import ResearchCycleStatusReport


class _StatusLedger:
    def __init__(self, *, tick_runs: list[dict[str, object]], latest_real_cycle: dict[str, object] | None = None) -> None:
        self._tick_runs = tick_runs
        self._latest_real_cycle = dict(latest_real_cycle or {})

    def latest_real_heartbeat_research_cycle_summary(self) -> dict[str, object]:
        return dict(self._latest_real_cycle)

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        _ = limit
        return list(self._tick_runs)


class ResearchCycleStatusReportTests(unittest.TestCase):
    def test_render_explains_research_disabled_when_no_real_cycle_exists(self) -> None:
        report = ResearchCycleStatusReport(
            config=object(),
            usage_ledger=_StatusLedger(
                tick_runs=[
                    {
                        "tick_id": "heartbeat-1",
                        "started_at": datetime.now().astimezone(),
                        "state_snapshot_json": {
                            "heartbeat": {
                                "tick_id": "heartbeat-1",
                                "autonomous_learning": {
                                    "autonomous_learning_called": True,
                                    "research_cycle_enabled": False,
                                    "research_cycle_due": False,
                                    "research_cycle_started": False,
                                    "research_cycle_completed": False,
                                    "research_cycle_skipped_reason": "research_disabled",
                                    "research_cycle_source": "real_heartbeat",
                                    "research_cycle_id": "",
                                    "research_decisions_written": 0,
                                    "usable_decisions_count": 0,
                                    "paper_candidates_created": 0,
                                    "paper_removal_candidates_created": 0,
                                    "attention_alerts_resolved": 0,
                                    "attention_alerts_created": 0,
                                },
                            }
                        },
                    }
                ]
            ),
        )

        rendered = report.render()

        self.assertIn("status=not_found", rendered)
        self.assertIn("reason=research_disabled", rendered)
        self.assertIn("autonomous_learning_called=yes", rendered)

    def test_render_explains_storage_write_failure_when_cycle_did_not_persist(self) -> None:
        report = ResearchCycleStatusReport(
            config=object(),
            usage_ledger=_StatusLedger(
                tick_runs=[
                    {
                        "tick_id": "heartbeat-2",
                        "started_at": datetime.now().astimezone(),
                        "state_snapshot_json": {
                            "heartbeat": {
                                "tick_id": "heartbeat-2",
                                "autonomous_learning": {
                                    "autonomous_learning_called": True,
                                    "research_cycle_enabled": True,
                                    "research_cycle_due": True,
                                    "research_cycle_started": True,
                                    "research_cycle_completed": True,
                                    "research_cycle_skipped_reason": "storage_write_failed",
                                    "research_cycle_source": "real_heartbeat",
                                    "research_cycle_id": "researchcycle-2",
                                    "research_decisions_written": 3,
                                    "usable_decisions_count": 3,
                                    "paper_candidates_created": 1,
                                    "paper_removal_candidates_created": 0,
                                    "attention_alerts_resolved": 0,
                                    "attention_alerts_created": 0,
                                    "research_cycle_persistence_error": "RuntimeError: insert failed",
                                },
                            }
                        },
                    }
                ]
            ),
        )

        rendered = report.render()

        self.assertIn("reason=storage_write_failed", rendered)
        self.assertIn("research_cycle_persistence_error=RuntimeError: insert failed", rendered)

    def test_render_explains_not_due_yet_when_recent_real_cycle_exists(self) -> None:
        report = ResearchCycleStatusReport(
            config=object(),
            usage_ledger=_StatusLedger(
                tick_runs=[
                    {
                        "tick_id": "heartbeat-4",
                        "started_at": datetime.now().astimezone(),
                        "state_snapshot_json": {
                            "heartbeat": {
                                "tick_id": "heartbeat-4",
                                "autonomous_learning": {
                                    "autonomous_learning_called": True,
                                    "research_cycle_enabled": True,
                                    "research_cycle_enabled_raw_value": "true",
                                    "research_cycle_enabled_env_file_value": "true",
                                    "research_cycle_enabled_value_source": ".env",
                                    "research_cycle_env_path": "/tmp/test.env",
                                    "research_cycle_due": False,
                                    "research_cycle_last_started_at": "2026-06-06T10:39:30+00:00",
                                    "research_cycle_min_interval_minutes": 60,
                                    "research_cycle_started": False,
                                    "research_cycle_completed": False,
                                    "research_cycle_skipped_reason": "not_due_yet",
                                    "research_cycle_source": "real_heartbeat",
                                    "research_cycle_id": "",
                                    "research_decisions_written": 0,
                                    "usable_decisions_count": 0,
                                    "paper_candidates_created": 0,
                                    "paper_removal_candidates_created": 0,
                                    "attention_alerts_resolved": 0,
                                    "attention_alerts_created": 0,
                                },
                            }
                        },
                    }
                ]
            ),
        )

        rendered = report.render()

        self.assertIn("reason=not_due_yet", rendered)
        self.assertIn("research_cycle_due=no", rendered)
        self.assertIn("research_cycle_enabled_value_source=.env", rendered)

    def test_render_shows_latest_real_cycle_when_present(self) -> None:
        report = ResearchCycleStatusReport(
            config=object(),
            usage_ledger=_StatusLedger(
                tick_runs=[],
                latest_real_cycle={
                    "latest_real_heartbeat_tick_id": "heartbeat-3",
                    "latest_real_research_cycle_id": "researchcycle-3",
                    "source": "real_heartbeat",
                    "latest_real_research_cycle_started_at": "2026-06-06T10:00:00+00:00",
                    "strategy_profiles_evaluated": 5,
                    "historical_windows_selected": 4,
                    "replay_windows_accepted_count": 4,
                    "replay_windows_rejected_count": 2,
                    "latest_valid_replay_window_end": "2026-05-29T09:45:00+00:00",
                    "usable_decisions_count": 2,
                    "paper_candidates_created": 1,
                    "paper_removal_candidates_created": 0,
                    "blockers": ["needs_more_replay_evidence_first"],
                },
            ),
        )

        rendered = report.render()

        self.assertIn("status=ok", rendered)
        self.assertIn("latest_real_cycle_id=researchcycle-3", rendered)
        self.assertIn("latest_real_raw_decisions_count=0", rendered)
        self.assertIn("latest_real_evidence_decisions_count=0", rendered)
        self.assertIn("latest_real_rejected_for_promotion_count=0", rendered)
        self.assertIn("latest_real_promotion_eligible_count=0", rendered)
        self.assertIn("latest_real_paper_candidates_created=1", rendered)
        self.assertIn("research_cycle_source=real_heartbeat", rendered)
        self.assertIn("historical_windows_selected_count=4", rendered)
        self.assertIn("latest_valid_replay_window_end=2026-05-29T09:45:00+00:00", rendered)

    def test_render_labels_real_cycle_decision_counts_by_stage(self) -> None:
        report = ResearchCycleStatusReport(
            config=object(),
            usage_ledger=_StatusLedger(
                tick_runs=[
                    {
                        "tick_id": "researchcycle-4",
                        "started_at": datetime.now().astimezone(),
                        "state_snapshot_json": {
                            "run": {
                                "pipeline": "research_cycle",
                                "source": "real_heartbeat",
                            },
                            "research_cycle": {
                                "historical_windows_selected": 4,
                                "usable_decisions_count": 2,
                                "paper_candidates_created": 1,
                                "paper_removal_candidates_created": 0,
                                "decisions": [
                                    {
                                        "strategy_id": "s1",
                                        "profile_id": "p1",
                                        "recommendation": "paper_sim_candidate",
                                        "proposals_created": 4,
                                        "outcomes_recorded": 3,
                                        "blocker_reasons": [],
                                    },
                                    {
                                        "strategy_id": "s2",
                                        "profile_id": "p2",
                                        "recommendation": "research_only",
                                        "proposals_created": 2,
                                        "outcomes_recorded": 0,
                                        "blocker_reasons": ["insufficient_sample_size"],
                                    },
                                ],
                            },
                        },
                    }
                ],
                latest_real_cycle={
                    "latest_real_heartbeat_tick_id": "heartbeat-4",
                    "latest_real_research_cycle_id": "researchcycle-4",
                    "source": "real_heartbeat",
                    "latest_real_research_cycle_started_at": "2026-06-06T11:00:00+00:00",
                    "strategy_profiles_evaluated": 2,
                    "historical_windows_selected": 4,
                    "replay_windows_accepted_count": 4,
                    "replay_windows_rejected_count": 0,
                    "latest_valid_replay_window_end": "2026-06-05T11:00:00+00:00",
                    "usable_decisions_count": 2,
                    "paper_candidates_created": 1,
                    "paper_removal_candidates_created": 0,
                    "blockers": ["insufficient_sample_size"],
                },
            ),
        )

        rendered = report.render()

        self.assertIn("latest_real_raw_decisions_count=2", rendered)
        self.assertIn("latest_real_evidence_decisions_count=2", rendered)
        self.assertIn("latest_real_rejected_for_promotion_count=1", rendered)
        self.assertIn("latest_real_promotion_eligible_count=1", rendered)
        self.assertIn("latest_real_paper_candidates_created=1", rendered)


if __name__ == "__main__":
    unittest.main()
