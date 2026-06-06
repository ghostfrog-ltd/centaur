from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.reporting.research_status import ResearchStatusReport


class _ResearchLedger:
    def __init__(self, rows: list[dict[str, object]], decisions: list[dict[str, object]]) -> None:
        self.rows = rows
        self.decisions = decisions

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return self.rows[:limit]

    def list_research_cycle_decisions(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        _ = limit
        if cycle_id:
            return [item for item in self.decisions if item["cycle_id"] == cycle_id]
        return list(self.decisions)

    def list_latest_research_cycle_decisions(self) -> list[dict[str, object]]:
        return list(self.decisions)

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str) -> dict[str, object] | None:
        if strategy_id == "crypto_pullback.downside_continuation_watch" and profile_id == "downside_continuation_watch":
            return None
        return {
            "strategy_id": strategy_id,
            "profile_id": profile_id,
            "paper_approved": 1,
            "stage": "paper_approved",
            "live_approved": 0,
            "max_paper_notional_usd": 10.0,
            "max_open_trades": 1,
            "cooldown_minutes": 30,
            "paper_execution_profile": 1,
            "research_only_profile": 0,
        }


class ResearchStatusReportTests(unittest.TestCase):
    def test_render_surfaces_recommendations_blockers_and_manual_approval_state(self) -> None:
        tz = ZoneInfo("UTC")
        report = ResearchStatusReport(
            config=SimpleNamespace(),
            usage_ledger=_ResearchLedger(
                [
                    {
                        "tick_id": "researchcycle-1",
                        "started_at": datetime(2026, 6, 6, 10, 0, tzinfo=tz),
                        "state_snapshot_json": {
                            "run": {
                                "pipeline": "research_cycle",
                                "timeframe": "15Min",
                                "days": 5,
                            },
                            "research_cycle": {
                                "replay_windows_tested": [{}, {}, {}, {}],
                                "timeframes_used": ["15Min", "1Hour"],
                                "timeframes_skipped": [
                                    {"timeframe": "1Min", "reason": "timeframe_not_present_in_historical_store"}
                                ],
                                "allocation_guardrails": {
                                    "include_backtest_evidence_in_paper_fitness": False,
                                    "include_backtest_evidence_in_live_fitness": False,
                                },
                            },
                        },
                    }
                ],
                [
                    {
                        "cycle_id": "researchcycle-1",
                        "strategy_id": "crypto_pullback.downside_continuation_watch",
                        "profile_id": "downside_continuation_watch",
                        "timeframe": "15Min",
                        "windows_tested_count": 4,
                        "sample_size_status": "sufficient",
                        "data_integrity_status": "warn",
                        "recommendation": "paper_sim_candidate",
                        "gross_return_summary_json": {"avg_pct": 0.31},
                        "net_return_summary_json": {"avg_pct": 0.11},
                        "win_rate_summary_json": {"avg": 0.58},
                        "outcomes_recorded": 72,
                        "blocker_reasons_json": [
                            "research_only_strategy",
                            "manual_promotion_required",
                            "timeframe:1Min/timeframe_not_present_in_historical_store",
                        ],
                    }
                ],
            ),
        ).render()

        self.assertIn("last_research_cycle_time=2026-06-06T10:00:00+00:00", report)
        self.assertIn("timeframes_used=15Min,1Hour", report)
        self.assertIn("timeframes_skipped=1Min/timeframe_not_present_in_historical_store", report)
        self.assertIn("recommendation=paper_sim_candidate", report)
        self.assertIn("data_integrity_status=warn", report)
        self.assertIn("blocker_reasons=research_only_strategy,manual_promotion_required,timeframe:1Min/timeframe_not_present_in_historical_store", report)
        self.assertIn("backtest_evidence_in_allocation=paper:no/live:no", report)
        self.assertIn("broker_paper_approved=no", report)
        self.assertIn("live_execution_status=disabled_manual_only", report)


if __name__ == "__main__":
    unittest.main()
