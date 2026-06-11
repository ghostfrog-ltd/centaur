from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.framework.reporting.research_cycle_last_comparison import (
    ResearchCycleLastComparisonReport,
)


class _Ledger:
    backend = "postgres"

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return self.rows[:limit]


class ResearchCycleLaunchdComparisonTests(unittest.TestCase):
    def test_prefers_actual_launchd_cycle_over_simulated_cycle(self) -> None:
        rows = [
            {
                "tick_id": "sim-natural-1",
                "state_snapshot_json": {
                    "heartbeat": {
                        "autonomous_learning": {
                            "forced_research_cycle": False,
                        }
                    }
                },
            },
            {
                "tick_id": "research-sim",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-sim",
                        "parent_tick_id": "sim-natural-1",
                    },
                    "research_cycle": {
                        "replay_windows_accepted_count": 8,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
            {
                "tick_id": "20260606-141213",
                "state_snapshot_json": {
                    "heartbeat": {
                        "autonomous_learning": {
                            "forced_research_cycle": False,
                        }
                    }
                },
            },
            {
                "tick_id": "research-launchd",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-launchd",
                        "parent_tick_id": "20260606-141213",
                    },
                    "research_cycle": {
                        "replay_windows_accepted_count": 0,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
            {
                "tick_id": "20260606-130353",
                "state_snapshot_json": {
                    "heartbeat": {
                        "autonomous_learning": {
                            "forced_research_cycle": True,
                        }
                    }
                },
            },
            {
                "tick_id": "research-forced",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-forced",
                        "parent_tick_id": "20260606-130353",
                    },
                    "research_cycle": {
                        "replay_windows_accepted_count": 8,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
        ]
        report = ResearchCycleLastComparisonReport(
            config=SimpleNamespace(),
            usage_ledger=_Ledger(rows),
        )

        built = report.build_report()

        self.assertEqual(built["real_launchd_cycle_status"], "found")
        self.assertEqual(built["natural_cycle_status"], "found")
        self.assertEqual(built["natural_cycle"]["cycle_origin"], "launchd_scheduled")

    def test_marks_simulated_only_when_no_launchd_cycle_exists(self) -> None:
        rows = [
            {
                "tick_id": "sim-natural-1",
                "state_snapshot_json": {
                    "heartbeat": {
                        "autonomous_learning": {
                            "forced_research_cycle": False,
                        }
                    }
                },
            },
            {
                "tick_id": "research-sim",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-sim",
                        "parent_tick_id": "sim-natural-1",
                    },
                    "research_cycle": {},
                },
            },
        ]
        report = ResearchCycleLastComparisonReport(
            config=SimpleNamespace(),
            usage_ledger=_Ledger(rows),
        )

        rendered = report.render()

        self.assertIn("natural_cycle_status=simulated_only", rendered)
        self.assertIn("real_launchd_cycle_status=missing", rendered)


if __name__ == "__main__":
    unittest.main()
