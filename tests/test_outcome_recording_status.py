from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.framework.reporting.outcome_recording_status import OutcomeRecordingStatusReport


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

    def get_market_bars_for_window(
        self,
        *,
        source: str,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, object]]:
        _ = (source, start_at, end_at)
        if symbol == "AAPL":
            return [{"captured_at": end_at, "close_price": 1.0}]
        return []


class _TestReport(OutcomeRecordingStatusReport):
    def __init__(self, *, replay_rows: list[dict[str, object]], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._replay_rows = replay_rows

    def _load_replay_checkpoint_rows(self, *, replay_run_ids: set[str]) -> list[dict[str, object]]:
        _ = replay_run_ids
        return list(self._replay_rows)


class OutcomeRecordingStatusReportTests(unittest.TestCase):
    def test_build_report_flags_pending_replay_rows_with_bars_as_lookup_bug(self) -> None:
        now = datetime(2026, 6, 8, 12, 0).astimezone()
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
        )
        tick_runs = [
            {
                "tick_id": "heartbeat-1",
                "started_at": now,
                "state_snapshot_json": {
                    "shadow_trade_outcomes": {
                        "mode": "evaluated",
                        "checkpoints_due": 2,
                        "checkpoints_evaluated": 2,
                        "waiting_for_future_bars": 0,
                        "bars_loaded": 10,
                    }
                },
            },
            {
                "tick_id": "researchcycle-1",
                "started_at": now,
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                    },
                    "research_cycle": {
                        "replay_run_ids": ["replay-1"],
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-1": [
                {
                    "strategy_id": "liquidity_probe.steady_flow",
                    "profile_id": "steady_flow",
                    "timeframe": "15Min",
                    "windows_tested_count": 1,
                    "proposals_created": 2,
                    "outcomes_recorded": 8,
                    "symbol_universe_json": ["AAPL"],
                    "blocker_reasons_json": ["insufficient_replay_windows"],
                    "net_return_summary_json": {"avg_pct": 0.4},
                    "win_rate_summary_json": {"avg": 0.62},
                }
            ]
        }
        replay_rows = [
            {
                "proposal_id": "p1",
                "proposed_at": now,
                "strategy_id": "liquidity_probe.steady_flow",
                "profile_id": "steady_flow",
                "source": "alpaca_market_data",
                "symbol": "AAPL",
                "note": "historical_replay:replay-1:15min:x",
                "holding_window_code": "15m",
                "holding_window_minutes": 15,
                "checkpoint_code": "15m",
                "checkpoint_minutes": 15,
                "due_at": now,
                "evaluated_at": None,
                "outcome_status": "pending",
                "replay_timeframe": "15Min",
                "replay_run_id": "replay-1",
            }
        ]
        report = _TestReport(
            replay_rows=replay_rows,
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["status"], "ok")
        self.assertEqual(built["lookback_24h"]["missing_matured_outcomes"], 1)
        self.assertEqual(
            built["lookback_24h"]["missing_by_group"][0]["mismatch_reason"],
            "bars_found_pending_outcome",
        )
        self.assertEqual(built["verdict"], "outcome_lookup_bug")


if __name__ == "__main__":
    unittest.main()
