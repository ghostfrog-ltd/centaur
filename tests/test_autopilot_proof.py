from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import sys
import unittest

import main as main_module
from app.framework.reporting.autopilot_proof import AutopilotProofRunner


class AutopilotProofTests(unittest.TestCase):
    def test_autopilot_proof_runner_reports_safe_manual_boundaries(self) -> None:
        runner = AutopilotProofRunner()
        result = runner.run()
        rendered = runner.render(result)

        self.assertEqual(result["status"], "pass")
        self.assertIn("autopilot_research_cycle", result["autonomous_work_performed"])
        self.assertIn("paper_sim_evidence_evaluation", result["autonomous_work_performed"])
        self.assertGreaterEqual(int(result["strategy_profiles_discovered"]), 2)
        self.assertGreaterEqual(int(result["strategy_profiles_evaluated"]), 1)
        self.assertGreaterEqual(int(result["internal_stage_changes"]), 1)
        self.assertGreaterEqual(int(result["paper_candidates_created"]), 1)
        self.assertGreaterEqual(int(result["paper_removal_candidates_created"]), 1)
        self.assertTrue(result["manual_approval_required"])
        self.assertTrue(result["slack_notified"])
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertEqual(result["live_orders_created"], 0)
        self.assertEqual(result["auto_paper_approved"], 0)
        self.assertEqual(result["auto_paper_removed"], 0)
        self.assertEqual(result["auto_live_approved"], 0)
        self.assertEqual(result["auto_live_removed"], 0)
        self.assertIn("paper_candidate", rendered)
        self.assertIn("paper_removal_candidate", rendered)
        self.assertIn("proof_mode=synthetic_safety_harness", rendered)
        self.assertIn("real_learning_proven=false", rendered)
        self.assertIn("uses_synthetic_replay_evidence=yes", rendered)
        self.assertIn("uses_synthetic_paper_sim_evidence=yes", rendered)
        self.assertIn("strategy_profiles_discovered=", rendered)
        self.assertIn("strategy_profiles_evaluated=", rendered)
        self.assertIn("strategy_profiles_skipped=", rendered)
        self.assertIn("internal_stage_changes=", rendered)
        self.assertIn("paper_candidates_created=", rendered)
        self.assertIn("paper_removal_candidates_created=", rendered)
        self.assertIn("manual_approval_required=true", rendered)
        self.assertIn("broker_orders_created=0", rendered)
        self.assertIn("live_orders_created=0", rendered)
        self.assertIn("auto_paper_approved=0", rendered)
        self.assertIn("auto_paper_removed=0", rendered)
        self.assertIn("auto_live_approved=0", rendered)
        self.assertIn("auto_live_removed=0", rendered)
        self.assertIn("final_safety_summary=PASS", rendered)

    def test_main_autopilot_proof_command_prints_required_summary(self) -> None:
        original_argv = sys.argv
        buffer = StringIO()
        sys.argv = ["main.py", "--autopilot-proof"]
        try:
            with redirect_stdout(buffer):
                main_module.main()
        finally:
            sys.argv = original_argv

        output = buffer.getvalue()
        self.assertIn("Centaur Autopilot Proof", output)
        self.assertIn("proof_mode=synthetic_safety_harness", output)
        self.assertIn("real_learning_proven=false", output)
        self.assertIn("strategy_profiles_discovered=", output)
        self.assertIn("strategy_profiles_evaluated=", output)
        self.assertIn("strategy_profiles_skipped=", output)
        self.assertIn("internal_stage_changes=", output)
        self.assertIn("paper_candidates_created=", output)
        self.assertIn("paper_removal_candidates_created=", output)
        self.assertIn("manual_approval_required=true", output)
        self.assertIn("broker_orders_created=0", output)
        self.assertIn("live_orders_created=0", output)
        self.assertIn("auto_paper_approved=0", output)
        self.assertIn("auto_paper_removed=0", output)
        self.assertIn("auto_live_approved=0", output)
        self.assertIn("auto_live_removed=0", output)
        self.assertIn("slack_attention_alerts_created=", output)
        self.assertIn("final_safety_summary=PASS", output)


if __name__ == "__main__":
    unittest.main()
