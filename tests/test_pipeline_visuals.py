from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from app.framework.engine.pipelines import build_default_pipeline
from app.heartbeat.pipeline import STEP_MODULES
from scripts.export_pipeline_mermaid import build_mermaid


class PipelineVisualTests(unittest.TestCase):
    def test_pipeline_visual_includes_runner_code_references(self) -> None:
        mermaid = build_mermaid()

        for step in build_default_pipeline():
            with self.subTest(step=step.name):
                source_file = inspect.getsourcefile(step.runner)
                self.assertIsNotNone(source_file)
                source_ref = Path(source_file).relative_to(Path.cwd())
                runner_ref = f"{source_ref}::{step.runner.__name__}"
                self.assertIn(step.name, mermaid)
                self.assertIn(runner_ref, mermaid)
                self.assertIn("app/heartbeat/steps/", runner_ref)

    def test_pipeline_visual_includes_ownership_lanes(self) -> None:
        mermaid = build_mermaid()

        self.assertIn(
            "Runtime control / app.heartbeat.steps + app.framework.runtime",
            mermaid,
        )
        self.assertIn(
            "Broker sync / app.heartbeat.steps + app.framework.adapters",
            mermaid,
        )
        self.assertIn(
            "Risk gates / app.heartbeat.steps + app.framework.runtime",
            mermaid,
        )
        self.assertIn(
            "Execution routing / app.heartbeat.steps + app.framework.runtime",
            mermaid,
        )
        self.assertNotIn("Other runtime ownership", mermaid)

    def test_heartbeat_folder_order_matches_default_pipeline(self) -> None:
        steps = build_default_pipeline()

        self.assertEqual(len(STEP_MODULES), len(steps))
        for index, (module_name, step) in enumerate(
            zip(STEP_MODULES, steps),
            start=1,
        ):
            with self.subTest(step=step.name):
                prefix = f"app.heartbeat.steps.{index:02d}_"
                self.assertTrue(module_name.startswith(prefix), module_name)
                source_file = inspect.getsourcefile(step.runner)
                self.assertIsNotNone(source_file)
                self.assertIn(
                    f"{index:02d}_",
                    str(Path(source_file)),
                )


if __name__ == "__main__":
    unittest.main()
