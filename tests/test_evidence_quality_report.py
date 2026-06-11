from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from app.framework.reporting.evidence_quality_report import EvidenceQualityReport


class _Ledger:
    backend = "sqlite"

    def __init__(
        self,
        *,
        tick_runs: list[dict[str, object]],
        decisions_by_cycle: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._tick_runs = tick_runs
        self._decisions_by_cycle = decisions_by_cycle or {}

    def list_recent_tick_runs(self, *, limit: int = 400) -> list[dict[str, object]]:
        _ = limit
        return list(self._tick_runs)

    def list_research_cycle_decisions(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        _ = limit
        return list(self._decisions_by_cycle.get(str(cycle_id or ""), []))


class EvidenceQualityReportTests(unittest.TestCase):
    def test_build_report_prefers_real_samples_in_closest_ranking_and_splits_blockers(self) -> None:
        now = datetime(2026, 6, 8, 12, 0).astimezone()
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
        )
        tick_runs = [
            {
                "tick_id": "researchcycle-900",
                "started_at": now,
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                    }
                },
            },
            {
                "tick_id": "researchcycle-899",
                "started_at": now - timedelta(hours=2),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                    }
                },
            },
        ]
        decisions = {
            "researchcycle-900": [
                {
                    "cycle_id": "researchcycle-900",
                    "strategy_id": "with.sample",
                    "profile_id": "balanced",
                    "timeframe": "15Min",
                    "windows_tested_count": 1,
                    "proposals_created": 5,
                    "outcomes_recorded": 2,
                    "symbol_universe_json": ["AAPL", "MSFT"],
                    "blocker_reasons_json": ["insufficient_replay_windows", "timeframe:15Min/no_safe_replay_windows"],
                    "net_return_summary_json": {"avg_pct": 0.20},
                    "win_rate_summary_json": {"avg": 0.70},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-900",
                    "strategy_id": "zero.sample",
                    "profile_id": "balanced",
                    "timeframe": "1Hour",
                    "windows_tested_count": 4,
                    "proposals_created": 0,
                    "outcomes_recorded": 0,
                    "symbol_universe_json": ["TSLA"],
                    "blocker_reasons_json": ["insufficient_sample_size", "timeframe:1Hour/no_matching_historical_rows_for_requested_symbols"],
                    "net_return_summary_json": {"avg_pct": 0.0},
                    "win_rate_summary_json": {"avg": 0.0},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-900",
                    "strategy_id": "bad.performance",
                    "profile_id": "balanced",
                    "timeframe": "1Hour",
                    "windows_tested_count": 4,
                    "proposals_created": 86,
                    "outcomes_recorded": 86,
                    "symbol_universe_json": ["BTC/USD", "ETH/USD"],
                    "blocker_reasons_json": ["net_return_below_threshold", "win_rate_below_threshold"],
                    "net_return_summary_json": {"avg_pct": -1.0},
                    "win_rate_summary_json": {"avg": 0.22},
                    "raw_json": {},
                },
            ],
            "researchcycle-899": [
                {
                    "cycle_id": "researchcycle-899",
                    "strategy_id": "with.sample",
                    "profile_id": "balanced",
                    "timeframe": "15Min",
                    "windows_tested_count": 1,
                    "proposals_created": 3,
                    "outcomes_recorded": 1,
                    "symbol_universe_json": ["AAPL"],
                    "blocker_reasons_json": ["insufficient_replay_windows"],
                    "net_return_summary_json": {"avg_pct": 0.15},
                    "win_rate_summary_json": {"avg": 0.60},
                    "raw_json": {},
                }
            ],
        }
        report = EvidenceQualityReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["status"], "ok")
        self.assertEqual(built["latest_cycle"]["cycle_id"], "researchcycle-900")
        closest = built["closest_to_paper"]
        self.assertEqual(closest[0]["strategy_id"], "with.sample")
        self.assertEqual(closest[1]["strategy_id"], "bad.performance")
        self.assertEqual(closest[2]["strategy_id"], "zero.sample")
        first = built["latest_cycle"]["groups"][0]
        self.assertIn("missing_historical_or_outcome_rows", first["split_blockers"])
        self.assertIn("not_enough_future_windows_yet", first["split_blockers"])
        self.assertEqual(built["single_most_actionable_next_fix"], "fix outcome recording")
        self.assertEqual(built["verdict"], "mixed")


if __name__ == "__main__":
    unittest.main()
