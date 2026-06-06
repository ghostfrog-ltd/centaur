from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

import app.framework.engine.research_cycle as research_cycle_module
from app.framework.engine.research_cycle import ResearchCycleRunner


@dataclass(frozen=True)
class _FakeProfile:
    strategy_id: str
    profile_id: str
    asset_classes: tuple[str, ...] = ("crypto",)
    parameters: dict[str, object] = field(default_factory=lambda: {"research_only": True})


class _FakeStrategy:
    def build_profiles(self, _config) -> list[_FakeProfile]:
        return [_FakeProfile("crypto_pullback.downside_continuation_watch", "downside_continuation_watch")]


class _FakeLedger:
    def __init__(self) -> None:
        self.tick_runs: list[object] = []
        self.decisions: list[dict[str, object]] = []
        self.promotion_updates: list[dict[str, object]] = []
        self.attention_alerts: dict[str, dict[str, object]] = {}
        self.resolved_alerts: list[dict[str, object]] = []
        self.paper_trade_orders_recorded = 0
        self.backend = "sqlite"
        self.backend_detail = "test"

    def record_tick_run(self, report: object) -> bool:
        self.tick_runs.append(report)
        return True

    def record_research_cycle_decisions(self, *, decisions: list[dict[str, object]]) -> int:
        self.decisions.extend(decisions)
        return len(decisions)

    def record_strategy_promotion_evaluation(self, **kwargs) -> None:
        self.promotion_updates.append(kwargs)

    def list_shadow_trade_proposals_by_note_prefix(self, *, note_prefix: str) -> list[dict[str, object]]:
        if "15Min-run-1" not in note_prefix:
            return []
        return [
            {
                "proposal_id": "p1",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "AVAX/USD",
            },
            {
                "proposal_id": "p2",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "SOL/USD",
            },
        ]

    def list_shadow_trade_outcomes_by_note_prefix(self, *, note_prefix: str) -> list[dict[str, object]]:
        if "15Min-run-1" not in note_prefix:
            return []
        return [
            {
                "proposal_id": "p1",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "AVAX/USD",
                "realized_return_pct": 0.44,
                "max_adverse_excursion_pct": -0.18,
            },
            {
                "proposal_id": "p2",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "SOL/USD",
                "realized_return_pct": 0.24,
                "max_adverse_excursion_pct": -0.11,
            },
        ]

    def record_paper_trade_orders(self, **_kwargs) -> int:
        self.paper_trade_orders_recorded += 1
        raise AssertionError("research cycle must not record broker paper trades")

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str):
        return None

    def get_attention_alert(self, *, event_id: str):
        return self.attention_alerts.get(event_id)

    def upsert_attention_alert(self, *, alert: dict[str, object]) -> None:
        self.attention_alerts[str(alert.get("event_id", ""))] = dict(alert)

    def resolve_attention_alert(
        self,
        *,
        event_id: str,
        status: str,
        reason: str,
        resolved_at: datetime | None = None,
    ) -> None:
        self.resolved_alerts.append(
            {
                "event_id": event_id,
                "status": status,
                "reason": reason,
                "resolved_at": resolved_at,
            }
        )

    def list_due_attention_alerts(self, *, due_at: datetime):
        _ = due_at
        return []

    def mark_attention_alert_sent(self, **_kwargs) -> None:
        return None


class ResearchCycleRunnerTests(unittest.TestCase):
    def test_build_historical_replay_diagnostics_anchors_windows_to_latest_historical_bar(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 5, 9, 45, tzinfo=tz)
        earliest_bar = latest_bar - timedelta(days=20)
        rows = []
        current = earliest_bar
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _CoverageLedger(_FakeLedger):
            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                _ = (sources, symbols)
                selected = [dict(row) for row in rows if str(row.get("timeframe")) == timeframe]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        runner = ResearchCycleRunner(
            config=self._config(),
            usage_ledger=_CoverageLedger(),
            source="real_heartbeat",
            parent_tick_id="heartbeat-1",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)

        diagnostics = runner.build_historical_replay_diagnostics(end_at=datetime(2026, 6, 6, 11, 2, tzinfo=tz))

        self.assertEqual(
            diagnostics["latest_valid_replay_window_end"].isoformat(),
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(diagnostics["window_anchor_mode"], "latest_historical_bar_minus_future_horizon")
        self.assertGreater(diagnostics["replay_windows_accepted_count"], 0)
        accepted = diagnostics["replay_window_acceptances"]
        self.assertTrue(all(item["timeframe"] == "15Min" for item in accepted))
        self.assertTrue(
            all(item["end_at"] <= "2026-05-29T09:45:00+00:00" for item in accepted)
        )

    def test_research_cycle_skips_unsupported_timeframes_and_only_records_evidence(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="real_heartbeat",
                parent_tick_id="heartbeat-1",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            run_calls: list[tuple[str, str]] = []
            runner.replay_runner = SimpleNamespace(
                run=lambda **kwargs: self._replay_run(run_calls, **kwargs)
            )
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            report = runner.run()

            self.assertEqual(report.status, "ok")
            self.assertEqual(ledger.paper_trade_orders_recorded, 0)
            self.assertEqual(len(run_calls), 4)
            self.assertTrue(all(call[0] == "15Min" for call in run_calls))
            self.assertEqual(len(ledger.decisions), 1)
            decision = ledger.decisions[0]
            self.assertEqual(decision["timeframe"], "15Min")
            self.assertEqual(decision["recommendation"], "research_only")
            self.assertIn(
                "timeframe:1Min/timeframe_not_present_in_historical_store",
                decision["blocker_reasons"],
            )
            self.assertFalse(self._any_paper_approved(ledger.promotion_updates))
            self.assertEqual(len(ledger.tick_runs), 1)
            snapshot = ledger.tick_runs[0].state_snapshot["research_cycle"]
            self.assertEqual(snapshot["timeframes_used"], ["15Min"])
            self.assertEqual(
                snapshot["timeframes_skipped"],
                [
                    {"timeframe": "1Min", "reason": "timeframe_not_present_in_historical_store"},
                    {
                        "timeframe": "1Hour",
                        "reason": "not_enough_future_data_for_checkpoint_windows",
                    },
                ],
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_research_cycle_resolves_previous_no_usable_decisions_alert_when_later_cycle_succeeds(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            ledger.attention_alerts["research_cycle_failure"] = {
                "event_id": "research_cycle_failure",
                "attention_status": "open",
            }
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="real_heartbeat",
                parent_tick_id="heartbeat-1",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            runner.replay_runner = SimpleNamespace(run=lambda **kwargs: self._replay_run([], **kwargs))
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            runner.run()

            self.assertTrue(
                any(
                    item["event_id"] == "research_cycle_failure"
                    and item["status"] == "resolved"
                    and item["reason"] == "later_real_heartbeat_cycle_recorded_usable_decisions"
                    for item in ledger.resolved_alerts
                )
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_autopilot_proof_cycle_does_not_resolve_real_heartbeat_failure_alert(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            ledger.attention_alerts["research_cycle_failure"] = {
                "event_id": "research_cycle_failure",
                "attention_status": "open",
            }
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="autopilot_proof",
                parent_tick_id="autopilot-proof",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            runner.replay_runner = SimpleNamespace(run=lambda **kwargs: self._replay_run([], **kwargs))
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            runner.run()

            self.assertEqual(ledger.resolved_alerts, [])
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def _replay_run(self, run_calls: list[tuple[str, str]], **kwargs):
        timeframe = kwargs["timeframe"]
        run_calls.append((timeframe, kwargs["start_at"].isoformat()))
        return SimpleNamespace(tick_id=f"{timeframe}-run-1")

    def _bars_report(self, *, timeframe: str, **_kwargs):
        if timeframe == "1Min":
            return {
                "historical": {
                    "rows_by_timeframe": [{"timeframe": "15Min"}, {"timeframe": "1Hour"}],
                    "symbol_rows": [{"symbol": "AVAX/USD"}, {"symbol": "SOL/USD"}],
                    "distinct_symbols": 2,
                },
                "replay_readiness": {
                    "requested_timeframe": "1Min",
                    "eligible_timestamps": 0,
                    "can_replay_requested_range": False,
                    "reason": "timeframe_not_present_in_historical_store",
                },
            }
        return {
            "historical": {
                "rows_by_timeframe": [{"timeframe": "15Min"}, {"timeframe": "1Hour"}],
                "symbol_rows": [{"symbol": "AVAX/USD"}, {"symbol": "SOL/USD"}],
                "distinct_symbols": 2,
            },
            "replay_readiness": {
                "requested_timeframe": timeframe,
                "eligible_timestamps": 120,
                "can_replay_requested_range": timeframe == "15Min",
                "reason": "ok" if timeframe == "15Min" else "not_enough_future_data_for_checkpoint_windows",
            },
        }

    def _config(self):
        return SimpleNamespace(
            research_cycle_enabled=False,
            research_replay_days=5,
            research_replay_timeframe="1Min",
            research_max_replay_timestamps=500,
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            research_allowed_strategies=("crypto_pullback.downside_continuation_watch",),
            discovery_equity_symbols=(),
            discovery_crypto_symbols=("AVAX/USD", "SOL/USD"),
            include_backtest_evidence_in_paper_fitness=False,
            include_backtest_evidence_in_live_fitness=False,
            simulated_crypto_fee_bps=10.0,
            simulated_crypto_slippage_bps=8.0,
            simulated_crypto_spread_bps=12.0,
        )

    def _any_paper_approved(self, updates: list[dict[str, object]]) -> bool:
        return any(str(item.get("stage", "")) == "paper_approved" for item in updates)


if __name__ == "__main__":
    unittest.main()
