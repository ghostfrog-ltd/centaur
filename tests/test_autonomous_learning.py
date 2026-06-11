from __future__ import annotations

from datetime import datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from datetime import timedelta
from zoneinfo import ZoneInfo

import app.framework.runtime.autonomous_learning as autonomous_learning_module
import app.framework.engine.research_cycle as research_cycle_module
from app.framework.runtime.autonomous_learning import run_autonomous_learning_cycle
from app.framework.runtime.models import TickContext
from app.framework.engine.research_cycle import (
    ResearchCycleAlreadyRunningError,
    ResearchCycleRunner,
)

control_step_main = import_module(
    "app.heartbeat.steps.01_control_heartbeat.implementation.main"
)


class AutonomousLearningTests(unittest.TestCase):
    def test_autonomous_learning_skips_cleanly_when_disabled(self) -> None:
        original_runner = autonomous_learning_module.ResearchCycleRunner
        autonomous_learning_module.ResearchCycleRunner = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("research cycle should not run when disabled")
        )
        try:
            context = TickContext(
                tick_id="tick-disabled",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(
                    research_cycle_enabled=False,
                    research_cycle_enabled_raw_value="false",
                    research_cycle_enabled_env_file_value="false",
                    research_cycle_enabled_value_source=".env",
                    research_cycle_env_path="/tmp/test.env",
                ),
                usage_ledger=SimpleNamespace(),
                state={},
            )
            result = run_autonomous_learning_cycle(context)
        finally:
            autonomous_learning_module.ResearchCycleRunner = original_runner

        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["triggered"])
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertEqual(result["auto_paper_approved"], 0)
        self.assertTrue(result["autonomous_learning_called"])
        self.assertFalse(result["research_cycle_enabled"])
        self.assertEqual(result["research_cycle_skipped_reason"], "research_disabled")
        self.assertEqual(result["research_cycle_enabled_value_source"], ".env")

    def test_autonomous_learning_runs_one_safe_cycle_without_manual_intervention(self) -> None:
        calls: list[str] = []
        original_runner = autonomous_learning_module.ResearchCycleRunner
        original_discover = autonomous_learning_module._discover_strategy_profiles

        class _FakeRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self):
                calls.append("run")
                return SimpleNamespace(
                    tick_id="researchcycle-proof",
                    state_snapshot={
                        "research_cycle": {
                            "decisions": [
                                {
                                    "strategy_id": "s1",
                                    "profile_id": "p1",
                                    "recommendation": "paper_sim_candidate",
                                    "outcomes_recorded": 5,
                                    "data_integrity_status": "pass",
                                }
                            ],
                            "timeframes_used": ["15Min"],
                            "timeframes_skipped": [],
                            "live_execution_remains_disabled": True,
                        }
                    },
                )

        autonomous_learning_module.ResearchCycleRunner = _FakeRunner
        autonomous_learning_module._discover_strategy_profiles = lambda **_kwargs: [
            {
                "strategy_id": "s1",
                "profile_id": "p1",
                "asset_classes": ["crypto"],
                "research_only_profile": True,
                "paper_allowed": False,
                "live_allowed": False,
            }
        ]
        try:
            context = TickContext(
                tick_id="tick-enabled",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(research_cycle_enabled=True),
                usage_ledger=SimpleNamespace(
                    get_strategy_promotion=lambda **_kwargs: {
                        "strategy_id": "s1",
                        "profile_id": "p1",
                        "stage": "paper_candidate",
                        "paper_approved": 0,
                        "live_approved": 0,
                    },
                    get_attention_alert=lambda **_kwargs: {
                        "attention_status": "open",
                    },
                ),
                state={},
            )
            result = run_autonomous_learning_cycle(context)
        finally:
            autonomous_learning_module.ResearchCycleRunner = original_runner
            autonomous_learning_module._discover_strategy_profiles = original_discover

        self.assertEqual(calls, ["run"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["triggered"])
        self.assertTrue(result["manual_approval_required"])
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertEqual(result["live_orders_created"], 0)
        self.assertEqual(result["auto_paper_approved"], 0)
        self.assertEqual(result["auto_live_approved"], 0)
        self.assertEqual(result["research_cycle_source"], "real_heartbeat")
        self.assertTrue(result["research_cycle_started"])
        self.assertTrue(result["research_cycle_completed"])
        self.assertEqual(result["usable_decisions_count"], 1)
        self.assertEqual(result["paper_candidates_created"], 1)
        heartbeat = context.state["heartbeat"]["autonomous_learning"]
        self.assertTrue(heartbeat["autonomous_learning_called"])
        self.assertEqual(heartbeat["research_cycle_id"], "researchcycle-proof")

    def test_autonomous_learning_skips_when_real_cycle_is_not_due(self) -> None:
        context = TickContext(
            tick_id="tick-not-due",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                research_cycle_enabled=True,
                research_cycle_enabled_raw_value="true",
                research_cycle_enabled_env_file_value="true",
                research_cycle_enabled_value_source=".env",
                research_cycle_env_path="/tmp/test.env",
                research_cycle_min_interval_minutes=60,
            ),
            usage_ledger=SimpleNamespace(
                latest_real_heartbeat_research_cycle_summary=lambda: {
                    "latest_real_research_cycle_started_at": datetime.now().astimezone().isoformat(),
                }
            ),
            state={"heartbeat": {"tick_id": "tick-not-due"}},
        )

        result = run_autonomous_learning_cycle(context)

        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["triggered"])
        self.assertTrue(result["autonomous_learning_called"])
        self.assertTrue(result["research_cycle_enabled"])
        self.assertFalse(result["research_cycle_due"])
        self.assertEqual(result["research_cycle_skipped_reason"], "not_due_yet")

    def test_autonomous_learning_force_only_bypasses_interval_gate(self) -> None:
        calls: list[str] = []
        original_runner = autonomous_learning_module.ResearchCycleRunner
        original_discover = autonomous_learning_module._discover_strategy_profiles

        class _ForcedRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self):
                calls.append("run")
                return SimpleNamespace(
                    tick_id="researchcycle-forced",
                    persisted_tick_run=True,
                    persistence_error="",
                    state_snapshot={
                        "run": {"source": "real_heartbeat"},
                        "research_cycle": {
                            "decisions": [],
                            "research_decisions_written": 0,
                            "timeframes_used": ["15Min"],
                            "timeframes_skipped": [],
                            "live_execution_remains_disabled": True,
                        },
                    },
                )

        autonomous_learning_module.ResearchCycleRunner = _ForcedRunner
        autonomous_learning_module._discover_strategy_profiles = lambda **_kwargs: []
        try:
            context = TickContext(
                tick_id="tick-forced",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(
                    research_cycle_enabled=True,
                    research_cycle_min_interval_minutes=60,
                ),
                usage_ledger=SimpleNamespace(
                    latest_real_heartbeat_research_cycle_summary=lambda: {
                        "latest_real_research_cycle_started_at": datetime.now().astimezone().isoformat(),
                    }
                ),
                state={"diagnostics": {"force_research_cycle": True}},
            )
            result = run_autonomous_learning_cycle(context)
        finally:
            autonomous_learning_module.ResearchCycleRunner = original_runner
            autonomous_learning_module._discover_strategy_profiles = original_discover

        self.assertEqual(calls, ["run"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["research_cycle_due"])
        self.assertTrue(result["forced_research_cycle"])
        self.assertEqual(result["research_cycle_skipped_reason"], "no_usable_decisions")
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertEqual(result["live_orders_created"], 0)
        self.assertEqual(result["auto_paper_approved"], 0)
        self.assertEqual(result["auto_live_approved"], 0)

    def test_forced_one_shot_skips_cleanly_when_research_cycle_already_running(self) -> None:
        original_runner = autonomous_learning_module.ResearchCycleRunner

        class _BusyRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self):
                raise ResearchCycleAlreadyRunningError(
                    "Another research cycle is already running; skipping overlapping forced one-shot."
                )

        autonomous_learning_module.ResearchCycleRunner = _BusyRunner
        try:
            context = TickContext(
                tick_id="tick-overlap",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(
                    research_cycle_enabled=True,
                    research_cycle_min_interval_minutes=60,
                ),
                usage_ledger=SimpleNamespace(
                    latest_real_heartbeat_research_cycle_summary=lambda: {}
                ),
                state={"diagnostics": {"force_research_cycle": True}},
            )
            result = run_autonomous_learning_cycle(context)
        finally:
            autonomous_learning_module.ResearchCycleRunner = original_runner

        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["triggered"])
        self.assertEqual(result["research_cycle_skipped_reason"], "research_cycle_already_running")
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertEqual(result["live_orders_created"], 0)
        self.assertEqual(result["auto_paper_approved"], 0)
        self.assertEqual(result["auto_live_approved"], 0)

    def test_control_heartbeat_triggers_autonomous_learning_hook(self) -> None:
        calls: list[str] = []
        original = control_step_main.run_autonomous_learning_cycle
        control_step_main.run_autonomous_learning_cycle = lambda context: calls.append(context.tick_id) or {
            "status": "ok"
        }
        try:
            context = TickContext(
                tick_id="tick-heartbeat",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(research_cycle_enabled=True),
                usage_ledger=SimpleNamespace(),
                state={},
            )
            result = control_step_main.run_implementation(context)
        finally:
            control_step_main.run_autonomous_learning_cycle = original

        self.assertEqual(result["status"], "alive")
        self.assertEqual(calls, ["tick-heartbeat"])

    def test_natural_scheduled_cycle_uses_same_historical_window_selection_as_forced_path(self) -> None:
        tz = ZoneInfo("UTC")
        lock_root = TemporaryDirectory()
        research_cycle_lock_dir = str(Path(lock_root.name) / "research-cycle.lock")
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
        current = earliest_bar
        while current <= (latest_bar - timedelta(minutes=45)):
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "1Hour",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(hours=1)

        class _CoverageLedger:
            backend = "sqlite"
            backend_detail = "test"

            def __init__(self) -> None:
                self.tick_runs: list[object] = []
                self.decisions: list[dict[str, object]] = []
                self.promotion_updates: list[dict[str, object]] = []
                self.attention_alerts: dict[str, dict[str, object]] = {}

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

            def summarize_historical_bars(self, *, as_of: datetime | None = None) -> dict[str, object]:
                _ = as_of
                return {
                    "backend": self.backend,
                    "backend_detail": self.backend_detail,
                    "historical": {
                        "rows_by_source": [{"source": "alpaca_crypto_data", "rows": len(rows)}],
                        "rows_by_timeframe": [
                            {"timeframe": "15Min", "rows": sum(1 for row in rows if row["timeframe"] == "15Min")},
                            {"timeframe": "1Hour", "rows": sum(1 for row in rows if row["timeframe"] == "1Hour")},
                        ],
                        "symbol_rows": [{"symbol": "AVAX/USD"}],
                        "min_bar_timestamp": earliest_bar,
                        "max_bar_timestamp": latest_bar,
                        "distinct_symbols": 1,
                    },
                    "latest": {},
                    "replay_readiness": {},
                }

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
                    }
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
                    }
                ]

            def get_strategy_promotion(self, *, strategy_id: str, profile_id: str):
                _ = (strategy_id, profile_id)
                return None

            def latest_real_heartbeat_research_cycle_summary(self) -> dict[str, object]:
                return {
                    "latest_real_research_cycle_started_at": (
                        latest_bar - timedelta(days=10)
                    ).isoformat()
                }

            def get_attention_alert(self, *, event_id: str):
                return self.attention_alerts.get(event_id)

            def upsert_attention_alert(self, *, alert: dict[str, object]) -> None:
                self.attention_alerts[str(alert.get("event_id", ""))] = dict(alert)

            def resolve_attention_alert(self, **_kwargs) -> None:
                return None

            def list_due_attention_alerts(self, *, due_at: datetime):
                _ = due_at
                return []

            def mark_attention_alert_sent(self, **_kwargs) -> None:
                return None

        class _FakeProfile:
            strategy_id = "crypto_pullback.downside_continuation_watch"
            profile_id = "downside_continuation_watch"
            asset_classes = ("crypto",)
            parameters = {"research_only": True}

        class _FakeStrategy:
            def build_profiles(self, _config) -> list[_FakeProfile]:
                return [_FakeProfile()]

        def _config():
            return SimpleNamespace(
                research_cycle_enabled=True,
                research_cycle_enabled_raw_value="true",
                research_cycle_enabled_env_file_value="true",
                research_cycle_enabled_value_source=".env",
                research_cycle_env_path="/tmp/test.env",
                research_cycle_min_interval_minutes=60,
                research_cycle_singleton_dir=research_cycle_lock_dir,
                research_replay_days=5,
                research_replay_timeframe="15Min",
                research_max_replay_timestamps=500,
                research_min_windows=4,
                research_min_proposals=1,
                research_min_net_return_pct=0.10,
                research_min_net_win_rate=0.55,
                research_allowed_strategies=("crypto_pullback.downside_continuation_watch",),
                discovery_equity_symbols=(),
                discovery_crypto_symbols=("AVAX/USD",),
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
                simulated_crypto_fee_bps=10.0,
                simulated_crypto_slippage_bps=8.0,
                simulated_crypto_spread_bps=12.0,
                shadow_checkpoint_windows=("15m", "1h", "1d", "7d"),
                historical_replay_default_days=5,
                historical_replay_default_timeframe="15Min",
                shadow_enabled=True,
            )

        class _NaturalRunner(ResearchCycleRunner):
            def __init__(self, **kwargs) -> None:
                super().__init__(
                    **kwargs,
                )
                self.replay_runner = SimpleNamespace(
                    run=lambda **kwargs: self._replay_run(**kwargs)
                )
                self.summary_report = SimpleNamespace(
                    build_report=lambda replay_run_id: {
                        "status": "ok",
                        "replay_run_id": replay_run_id,
                        "candidates_evaluated": 12,
                    }
                )
                self.comparison_report = SimpleNamespace(
                    build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
                )

            def run(self):
                return super().run()

            def _replay_run(self, **kwargs):
                timeframe = str(kwargs.get("timeframe", ""))
                run_id = f"{timeframe}-run-1"
                return SimpleNamespace(tick_id=run_id)

        original_auto_runner = autonomous_learning_module.ResearchCycleRunner
        original_auto_registry = autonomous_learning_module.build_strategy_registry
        original_research_registry = research_cycle_module.build_strategy_registry
        autonomous_learning_module.ResearchCycleRunner = _NaturalRunner
        autonomous_learning_module.build_strategy_registry = lambda: [_FakeStrategy()]
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            forced_ledger = _CoverageLedger()
            forced_report = _NaturalRunner(
                config=_config(),
                usage_ledger=forced_ledger,
                source="real_heartbeat",
                parent_tick_id="forced-heartbeat",
            ).run()
            forced_state = forced_report.state_snapshot["research_cycle"]

            natural_ledger = _CoverageLedger()
            context = TickContext(
                tick_id="natural-heartbeat",
                started_at=datetime(2026, 6, 20, 12, 15, tzinfo=tz),
                config=_config(),
                usage_ledger=natural_ledger,
                state={"heartbeat": {"tick_id": "natural-heartbeat"}},
            )
            result = run_autonomous_learning_cycle(context)
            self.assertEqual(result["status"], "ok")
            natural_row = next(
                report for report in natural_ledger.tick_runs if getattr(report, "tick_id", "").startswith("researchcycle-")
            )
            natural_state = natural_row.state_snapshot["research_cycle"]
        finally:
            autonomous_learning_module.ResearchCycleRunner = original_auto_runner
            autonomous_learning_module.build_strategy_registry = original_auto_registry
            research_cycle_module.build_strategy_registry = original_research_registry
            lock_root.cleanup()

        self.assertEqual(forced_state["historical_windows_selected"], 8)
        self.assertEqual(natural_state["historical_windows_selected"], 8)
        self.assertEqual(
            forced_state["replay_window_acceptances"],
            natural_state["replay_window_acceptances"],
        )
        self.assertEqual(
            forced_state["latest_available_historical_bar_at"],
            natural_state["latest_available_historical_bar_at"],
        )
        self.assertEqual(
            forced_state["latest_valid_replay_window_end"],
            natural_state["latest_valid_replay_window_end"],
        )
        self.assertEqual(
            forced_state["max_required_future_horizon"],
            natural_state["max_required_future_horizon"],
        )


if __name__ == "__main__":
    unittest.main()
