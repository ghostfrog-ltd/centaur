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


class ResearchCycleLastComparisonReportTests(unittest.TestCase):
    def test_render_compares_last_forced_and_natural_real_cycles(self) -> None:
        rows = [
            {
                "tick_id": "20260606-121548",
                "state_snapshot_json": {
                    "heartbeat": {
                        "autonomous_learning": {
                            "forced_research_cycle": False,
                        }
                    }
                },
            },
            {
                "tick_id": "research-natural",
                "started_at": "2026-06-06T12:15:49+01:00",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-natural",
                        "parent_tick_id": "20260606-121548",
                        "research_started_at": "2026-06-06T12:15:49+01:00",
                        "days": 5,
                        "max_replay_timestamps": 500,
                        "replay_setting_sources": {
                            "research_replay_days": {"source": "env"},
                            "research_replay_timeframe": {"source": "env"},
                        },
                    },
                    "research_cycle": {
                        "timeframes_used": [],
                        "timeframes_skipped": [
                            {
                                "timeframe": "15Min",
                                "reason": "not_enough_future_data_for_checkpoint_windows",
                            }
                        ],
                        "selected_symbol_universe": {"equity": ["AAPL"], "crypto": ["AVAX/USD"]},
                        "latest_available_historical_bar_at": "-",
                        "max_required_future_horizon": "-",
                        "latest_valid_replay_window_end": "-",
                        "replay_window_candidate_count": 0,
                        "replay_windows_accepted_count": 0,
                        "replay_windows_rejected_count": 0,
                        "replay_window_rejections": [],
                        "timeframe_historical_coverage": {
                            "15Min": {
                                "latest_available_historical_bar_at": "-",
                                "max_required_future_horizon": "7 days, 0:00:00",
                                "latest_valid_replay_window_end": "-",
                            }
                        },
                    },
                },
            },
            {
                "tick_id": "heartbeat-forced",
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
                "started_at": "2026-06-06T11:16:13+01:00",
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "research_cycle_id": "research-forced",
                        "parent_tick_id": "heartbeat-forced",
                        "research_started_at": "2026-06-06T11:16:13+01:00",
                        "days": 5,
                        "max_replay_timestamps": 500,
                        "replay_setting_sources": {
                            "research_replay_days": {"source": "env"},
                            "research_replay_timeframe": {"source": "env"},
                        },
                    },
                    "research_cycle": {
                        "timeframes_used": ["15Min"],
                        "timeframes_skipped": [],
                        "selected_symbol_universe": {"equity": ["AAPL"], "crypto": ["AVAX/USD"]},
                        "latest_available_historical_bar_at": "2026-06-05T09:45:00+01:00",
                        "max_required_future_horizon": "7 days, 0:00:00",
                        "latest_valid_replay_window_end": "2026-05-29T09:45:00+01:00",
                        "replay_window_candidate_count": 4,
                        "replay_windows_accepted_count": 4,
                        "replay_windows_rejected_count": 0,
                        "replay_window_acceptances": [
                            {
                                "timeframe": "15Min",
                                "start_at": "2026-05-24T09:45:00+01:00",
                                "end_at": "2026-05-25T15:45:00+01:00",
                            }
                        ],
                        "replay_window_rejections": [],
                        "timeframe_historical_coverage": {
                            "15Min": {
                                "latest_available_historical_bar_at": "2026-06-05T09:45:00+01:00",
                                "max_required_future_horizon": "7 days, 0:00:00",
                                "latest_valid_replay_window_end": "2026-05-29T09:45:00+01:00",
                            }
                        },
                    },
                },
            },
        ]
        report = ResearchCycleLastComparisonReport(
            config=SimpleNamespace(),
            usage_ledger=_Ledger(rows),
        )

        rendered = report.render()

        self.assertIn("force_mode_changes_anything_besides_interval_due_state=no", rendered)
        self.assertIn("forced_cycle_status=found", rendered)
        self.assertIn("natural_cycle_status=found", rendered)
        self.assertIn("forced_candidate_windows_accepted=4", rendered)
        self.assertIn("natural_rejection_reasons=not_enough_future_data_for_checkpoint_windows", rendered)


if __name__ == "__main__":
    unittest.main()
