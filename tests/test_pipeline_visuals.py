from __future__ import annotations

import unittest

from app.engine.pipelines import build_default_pipeline
from scripts.export_pipeline_mermaid import build_mermaid


class PipelineVisualTests(unittest.TestCase):
    def test_pipeline_visual_includes_runner_code_references(self) -> None:
        mermaid = build_mermaid()

        for step in build_default_pipeline():
            with self.subTest(step=step.name):
                runner_ref = f"app/engine/pipelines.py::{step.runner.__name__}"
                self.assertIn(step.name, mermaid)
                self.assertIn(runner_ref, mermaid)

    def test_pipeline_visual_includes_ownership_lanes(self) -> None:
        mermaid = build_mermaid()

        self.assertIn("Runtime control / app.runtime + app.engine", mermaid)
        self.assertIn("Broker adapters / app.adapters", mermaid)
        self.assertIn("Risk gates / app.runtime + app.engine", mermaid)
        self.assertIn("Execution routing / app.runtime", mermaid)


if __name__ == "__main__":
    unittest.main()
