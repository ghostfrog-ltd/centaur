from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.engine.control_graph import (
    build_control_graph,
    control_graph_edges,
    control_graph_step_names,
    run_control_graph,
)
from app.engine.pipelines import StepDefinition, build_default_pipeline
from app.runtime.models import TickContext


class ControlGraphTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
