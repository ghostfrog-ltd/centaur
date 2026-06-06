from __future__ import annotations

from datetime import datetime
from importlib import import_module
from types import SimpleNamespace
import unittest

import app.framework.runtime.autonomous_learning as autonomous_learning_module
from app.framework.runtime.autonomous_learning import run_autonomous_learning_cycle
from app.framework.runtime.models import TickContext

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


if __name__ == "__main__":
    unittest.main()
