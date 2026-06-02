from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.framework.engine.control_graph import (
    ControlGraphState,
    build_control_graph,
    control_graph_edges,
    control_graph_step_names,
    run_control_graph,
)
from app.framework.engine.pipelines import StepDefinition, build_default_pipeline
from app.framework.runtime.control import ControlPipelineRunner
from app.framework.runtime.models import TickContext
from app.heartbeat.graph import (
    HeartbeatCronGraphState,
    build_heartbeat_cron_graph,
    heartbeat_cron_edges,
    heartbeat_cron_step_names,
)


class _Logger:
    def tick_start(self, **kwargs: object) -> None:
        pass

    def runtime_summary(self, **kwargs: object) -> None:
        pass

    def step_start(self, **kwargs: object) -> None:
        pass

    def step_end(self, **kwargs: object) -> None:
        pass

    def profiling_summary(self, report: object) -> None:
        pass

    def api_usage_summary(self, report: object) -> None:
        pass

    def tick_end(self, report: object) -> None:
        pass

    def line(self, message: str) -> None:
        pass


class _UsageLedger:
    backend = "test"
    backend_detail = "test"

    def list_tick_usage(self, **kwargs: object) -> list[object]:
        return []

    def list_daily_usage(self, **kwargs: object) -> list[object]:
        return []

    def total_estimated_cost_usd(self, usage: list[object]) -> float:
        return 0.0

    def total_requests(self, usage: list[object]) -> int:
        return 0

    def budget_status(self, **kwargs: object) -> str:
        return "ok"

    def record_tick_run(self, report: object) -> bool:
        return True


class ControlGraphTests(unittest.TestCase):
    def test_control_graph_imports_are_heartbeat_facade(self) -> None:
        self.assertIs(ControlGraphState, HeartbeatCronGraphState)
        self.assertEqual(control_graph_step_names(), heartbeat_cron_step_names())
        self.assertEqual(control_graph_edges(), heartbeat_cron_edges())
        self.assertIsNotNone(build_heartbeat_cron_graph())

    def test_graph_step_names_match_default_pipeline(self) -> None:
        pipeline_names = [step.name for step in build_default_pipeline()]

        self.assertEqual(control_graph_step_names(), pipeline_names)

    def test_graph_edges_match_default_pipeline_order(self) -> None:
        names = [step.name for step in build_default_pipeline()]
        expected_edges = [("__start__", names[0])]
        expected_edges.extend((left, right) for left, right in zip(names, names[1:]))
        expected_edges.append((names[-1], "__end__"))

        self.assertEqual(control_graph_edges(), expected_edges)

    def test_default_graph_compiles(self) -> None:
        graph = build_control_graph()

        self.assertIsNotNone(graph)

    def test_graph_runs_typed_state_and_halts_after_error(self) -> None:
        def first_step(context: TickContext) -> dict[str, object]:
            context.state.setdefault("visited", []).append("first")
            return {"status": "first_ok"}

        def failing_step(context: TickContext) -> dict[str, object]:
            context.state.setdefault("visited", []).append("failing")
            raise RuntimeError("stop here")

        def unreachable_step(context: TickContext) -> dict[str, object]:
            context.state.setdefault("visited", []).append("unreachable")
            return {"status": "should_not_run"}

        context = TickContext(
            tick_id="test-tick",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(),
            usage_ledger=SimpleNamespace(),
        )
        graph_state = run_control_graph(
            context,
            steps=[
                StepDefinition(name="test.first", runner=first_step),
                StepDefinition(name="test.failing", runner=failing_step),
                StepDefinition(name="test.unreachable", runner=unreachable_step),
            ],
        )

        self.assertTrue(graph_state.halted)
        self.assertEqual(context.state["visited"], ["first", "failing"])
        self.assertEqual(
            [profile.name for profile in graph_state.step_profiles],
            ["test.first", "test.failing"],
        )
        self.assertEqual(graph_state.step_profiles[-1].status, "error")
        self.assertEqual(
            context.state["last_error"],
            {"step": "test.failing", "message": "stop here"},
        )

    def test_control_pipeline_runner_executes_heartbeat_langgraph(self) -> None:
        visited: list[str] = []

        def first_step(context: TickContext) -> dict[str, object]:
            visited.append("first")
            context.state["first"] = True
            return {"status": "first_ok"}

        def failing_step(context: TickContext) -> dict[str, object]:
            visited.append("failing")
            raise RuntimeError("graph halt")

        def unreachable_step(context: TickContext) -> dict[str, object]:
            visited.append("unreachable")
            return {"status": "should_not_run"}

        runner = ControlPipelineRunner(
            steps=[
                StepDefinition(name="test.first", runner=first_step),
                StepDefinition(name="test.failing", runner=failing_step),
                StepDefinition(name="test.unreachable", runner=unreachable_step),
            ],
            logger=_Logger(),
            config=SimpleNamespace(
                api_daily_cost_warning_usd=1.0,
                api_daily_cost_limit_usd=2.0,
            ),
            usage_ledger=_UsageLedger(),
        )

        report = runner.run_tick()

        self.assertEqual(visited, ["first", "failing"])
        self.assertEqual(report.status, "error")
        self.assertEqual(
            [profile.name for profile in report.step_profiles],
            ["test.first", "test.failing"],
        )
        self.assertEqual(
            report.state_snapshot["last_error"],
            {"step": "test.failing", "message": "graph halt"},
        )


if __name__ == "__main__":
    unittest.main()
