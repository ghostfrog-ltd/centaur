from __future__ import annotations

from io import StringIO
import contextlib
import sys
import unittest

import main as main_module


class MainRealLearningCliTests(unittest.TestCase):
    def test_real_learning_proof_run_fresh_forces_real_heartbeat_first(self) -> None:
        original_force_runner = main_module._run_heartbeat_autonomous_learning_once
        original_reporter = main_module.RealLearningProofReport
        original_argv = sys.argv
        calls: list[object] = []

        sys.argv = ["main.py", "--real-learning-proof", "--run-fresh"]
        main_module._run_heartbeat_autonomous_learning_once = (
            lambda *, force_research_cycle=False: calls.append(force_research_cycle)
            or f"forced={force_research_cycle}"
        )

        class _ProofReport:
            def render(self) -> str:
                calls.append("proof")
                return "proof-output"

        main_module.RealLearningProofReport = _ProofReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module._run_heartbeat_autonomous_learning_once = original_force_runner
            main_module.RealLearningProofReport = original_reporter
            sys.argv = original_argv

        self.assertEqual(calls, [True, "proof"])
        self.assertEqual(stdout.getvalue().splitlines(), ["forced=True", "", "proof-output"])


if __name__ == "__main__":
    unittest.main()
