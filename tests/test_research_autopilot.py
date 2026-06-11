from __future__ import annotations

import contextlib
from io import StringIO
import json
import sys
import unittest

import main as main_module
from app.framework.reporting.research_autopilot import ResearchAutopilotRunner


class _StubPlanner:
    def __init__(self, reports):
        self.reports = [dict(item) for item in reports]
        self.calls = 0
        self.kwargs_history = []

    def build_report(self, **kwargs):
        index = min(self.calls, len(self.reports) - 1)
        self.calls += 1
        self.kwargs_history.append(dict(kwargs))
        return json.loads(json.dumps(self.reports[index]))


class _StubPaperReporter:
    def __init__(self, reports):
        self.reports = [dict(item) for item in reports]
        self.calls = 0

    def build_report(self):
        index = min(self.calls, len(self.reports) - 1)
        self.calls += 1
        return json.loads(json.dumps(self.reports[index]))


class _StubLedger:
    def __init__(self):
        self.persisted = []
        self.paper_trade_orders_recorded = 0
        self.live_trade_orders_recorded = 0

    def record_strategy_variant_evaluation(self, **kwargs):
        self.persisted.append(dict(kwargs))
        return dict(kwargs)


class ResearchAutopilotTests(unittest.TestCase):
    def test_executes_allowlisted_next_actionable_research_command(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Day",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        paper = _StubPaperReporter([self._paper_report(), self._paper_report()])
        ledger = _StubLedger()
        executed = []

        runner = ResearchAutopilotRunner(
            usage_ledger=ledger,
            planner=planner,
            paper_reporter=paper,
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(len(executed), 1)
        self.assertIn("--diagnose-next-best-strategy", executed[0])
        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")
        self.assertEqual(report["last_result_status"], "executed_research_only")

    def test_refuses_non_allowlisted_command(self) -> None:
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=_StubPlanner([self._planner_report(
                candidate="momentum.strong/strong/1Day",
                command=".venv-mac/bin/python main.py --promotion-approve-paper --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                next_action="diagnose_next_best_strategy",
            )]),
            paper_reporter=_StubPaperReporter([self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["research_autopilot_status"], "refused")
        self.assertEqual(report["stop_reason"], "command_not_allowlisted")
        self.assertEqual(report["steps_run"], 0)

    def test_executes_signal_generation_diagnosis_command_when_allowlisted(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="",
                    command=".venv-mac/bin/python main.py --signal-generation-diagnosis --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    next_action="adjust_signal_generation_research_only",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(executed[0][2], "--signal-generation-diagnosis")
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_executes_strategy_variant_research_report_when_allowlisted(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_momentum.trend/trend/15Min",
                    command=".venv-mac/bin/python main.py --strategy-variant-research-report --base-strategy crypto_momentum.trend --profile-id trend --timeframe 15Min",
                    next_action="continue_research_for_crypto_momentum.trend",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(executed[0][2], "--strategy-variant-research-report")
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_executes_generated_research_candidate_command_when_allowlisted(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_wide_signal/15Min",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_wide_signal --timeframe 15Min",
                    next_action="continue_research_for_crypto_research.range_breakout",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(executed[0][2], "--run-strategy-variant-research")
        self.assertIn("range_breakout_wide_signal", executed[0])
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_executes_distinct_generated_range_breakout_candidate_when_rotated(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertIn("range_breakout_compression_release", executed[0])
        self.assertNotIn("range_breakout_wide_signal", " ".join(executed[0]))
        self.assertEqual(report["paper_trading_allowed"], "no")

    def test_executes_new_family_generated_candidate_when_allowlisted(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.liquidation_wick_reclaim/liquidation_wick_reclaim_confirmed/15Min",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
                    next_action="run_generated_variant_research",
                    research_universe_status="active_current_strategy_set",
                    portfolio_research_status="research_in_progress",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertIn("liquidation_wick_reclaim_confirmed", " ".join(executed[0]))
        self.assertEqual(report["paper_trading_allowed"], "no")

    def test_prefers_rotated_generated_candidate_over_stale_base_range_breakout_command(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                    research_universe_status="active_current_strategy_set",
                    portfolio_research_status="research_in_progress",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                    research_universe_status="active_current_strategy_set",
                    portfolio_research_status="research_in_progress",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 1)
        self.assertIn("range_breakout_compression_release", " ".join(executed[0]))
        self.assertNotIn("--profile-id range_breakout --timeframe 15Min", " ".join(executed[0]))
        self.assertEqual(report["paper_trading_allowed"], "no")

    def test_stops_with_explicit_exhausted_reason(self) -> None:
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=_StubPlanner(
                [
                    self._planner_report(
                        candidate="",
                        command="",
                        next_action="no_actionable_candidate",
                        research_universe_status="exhausted_current_strategy_set",
                        portfolio_research_status="no_actionable_candidate",
                    )
                ]
            ),
            paper_reporter=_StubPaperReporter([self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["stop_reason"], "stopped_because_strategy_universe_exhausted")
        self.assertEqual(report["research_universe_status"], "exhausted_current_strategy_set")

    def test_executes_research_expansion_planner_when_allowlisted(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="",
                    command=".venv-mac/bin/python main.py --research-expansion-planner",
                    next_action="generate_new_research_candidates",
                    research_universe_status="exhausted_current_strategy_set",
                    portfolio_research_status="no_actionable_candidate",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                    research_universe_status="exhausted_current_strategy_set",
                    portfolio_research_status="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(executed[0][2], "--research-expansion-planner")
        self.assertEqual(report["research_universe_status"], "exhausted_current_strategy_set")

    def test_stops_at_max_steps(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Day",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="crypto_research.dip_rebound/dip_rebound/1Hour",
                    command=".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    next_action="continue_research_for_crypto_research.dip_rebound",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=1)

        self.assertEqual(report["stop_reason"], "stopped_because_max_steps")
        self.assertEqual(report["steps_run"], 1)

    def test_stops_on_repeated_same_command_loop(self) -> None:
        report = self._runner_for_repeating_commands().run(max_steps=3)
        self.assertEqual(report["stop_reason"], "loop_detected")
        self.assertEqual(
            report["no_advance_reason"],
            "diagnosis_result_not_consumed_or_candidate_still_requires_same_action",
        )
        self.assertEqual(report["steps_run"], 1)

    def test_stops_if_paper_candidate_status_requires_manual_review(self) -> None:
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=_StubPlanner([self._planner_report()]),
            paper_reporter=_StubPaperReporter([self._paper_report(status="requires_manual_review")]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["stop_reason"], "candidate_ready_for_manual_paper_audit")
        self.assertEqual(report["candidate_ready_for_manual_paper_audit"], "yes")
        self.assertEqual(report["steps_run"], 0)

    def test_does_not_create_paper_trades_or_enable_live_or_lower_thresholds(self) -> None:
        ledger = _StubLedger()
        runner = ResearchAutopilotRunner(
            usage_ledger=ledger,
            planner=_StubPlanner([self._planner_report(), self._planner_report(candidate="", command="", next_action="no_actionable_candidate")]),
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "Research-only. No paper or live approval has been changed.", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(ledger.paper_trade_orders_recorded, 0)
        self.assertEqual(ledger.live_trade_orders_recorded, 0)
        self.assertEqual(report["paper_trading_allowed"], "no")
        self.assertNotIn("threshold", report["last_command"].lower())
        self.assertNotIn("live", report["last_command"].lower())

    def test_persists_step_summaries(self) -> None:
        ledger = _StubLedger()
        runner = ResearchAutopilotRunner(
            usage_ledger=ledger,
            planner=_StubPlanner([self._planner_report(), self._planner_report(candidate="", command="", next_action="no_actionable_candidate")]),
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        runner.run(max_steps=2)

        self.assertEqual(len(ledger.persisted), 1)
        self.assertEqual(ledger.persisted[0]["raw"]["report_type"], "research_autopilot_step_summary")
        self.assertIn(ledger.persisted[0]["raw"]["step_advanced"], {"yes", "partial"})

    def test_consumes_updated_planner_state_between_steps(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Day",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="momentum.balanced/balanced/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.balanced --profile-id balanced --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 2)
        self.assertIn("momentum.strong", executed[0])
        self.assertIn("momentum.balanced", executed[1])
        self.assertIn(report["step_log"][0]["step_advanced"], {"yes", "partial"})
        self.assertEqual(report["step_log"][1]["step_advanced"], "yes")

    def test_records_before_after_planner_state_and_no_advance_reason(self) -> None:
        report = self._runner_for_repeating_commands().run(max_steps=3)

        self.assertEqual(report["steps_run"], 1)
        step = report["step_log"][0]
        self.assertEqual(step["before_candidate"], "momentum.strong/strong/1Day")
        self.assertEqual(step["after_candidate"], "momentum.strong/strong/1Day")
        self.assertEqual(step["before_command"], step["after_command"])
        self.assertEqual(step["before_action"], step["after_action"])
        self.assertEqual(step["evidence_changed"], "no")
        self.assertEqual(step["candidate_status_changed"], "no")
        self.assertEqual(step["step_advanced"], "no")
        self.assertEqual(step["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(
            step["classification_reason"],
            "no_progress_after_research_step_with_negative_replay_edge",
        )
        self.assertEqual(step["sample_size_before"], 0)
        self.assertEqual(step["sample_size_after"], 0)
        self.assertEqual(step["net_return_after_costs_before"], 0.0)
        self.assertEqual(step["net_return_after_costs_after"], 0.0)
        self.assertEqual(step["win_rate_before"], 0.0)
        self.assertEqual(step["win_rate_after"], 0.0)
        self.assertEqual(
            step["no_advance_reason"],
            "diagnosis_result_not_consumed_or_candidate_still_requires_same_action",
        )

    def test_autopilot_does_not_loop_on_dip_rebound_once_planner_rotates_away_after_classification(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.dip_rebound/dip_rebound/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="liquidity_probe.steady_flow/steady_flow/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 2)
        self.assertIn("crypto_research.dip_rebound", executed[0])
        self.assertIn("liquidity_probe.steady_flow", executed[1])
        self.assertNotEqual(executed[0], executed[1])
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_no_progress_classification_replans_and_continues_to_next_candidate(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="mean_reversion.snapback/snapback/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="mean_reversion.snapback/snapback/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="liquidity_probe.steady_flow/steady_flow/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 2)
        self.assertEqual(report["step_log"][0]["step_advanced"], "no")
        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertIn("mean_reversion.snapback", executed[0])
        self.assertIn("liquidity_probe.steady_flow", executed[1])
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_no_progress_with_rotated_alternative_at_step_cap_reports_alternatives_remain(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="momentum.strong/strong/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="liquidity_probe.steady_flow/steady_flow/15Min",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                    next_action="diagnose_next_best_strategy",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=1)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(report["stop_reason"], "no_progress_but_alternatives_remain")
        self.assertEqual(
            report["next_actionable_research_candidate"],
            "liquidity_probe.steady_flow/steady_flow/15Min",
        )

    def test_no_progress_without_alternative_candidate_reports_no_alternative_candidate(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="momentum.strong/strong/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")
        self.assertEqual(report["parked_candidates_this_run"], ["momentum.strong/strong/1Hour"])
        self.assertEqual(report["planner_candidate_before_parking"], "momentum.strong/strong/1Hour")
        self.assertEqual(report["planner_candidate_after_parking"], "")
        self.assertEqual(report["data_runtime_action_detected"], "no")

    def test_post_precompute_weak_dip_rebound_is_classified_and_rotates(self) -> None:
        planner = _StubPlanner(
            [
                {
                    **self._planner_report(
                        candidate="crypto_research.dip_rebound/dip_rebound/15Min",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                        next_action="diagnose_next_best_strategy",
                    ),
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "crypto_research.dip_rebound",
                            "profile_id": "dip_rebound",
                            "timeframe": "15Min",
                            "latest_sample_size": 3,
                            "latest_net_return_after_costs": -0.305701,
                            "win_rate": 0.333333,
                            "latest_replay_preparation": {
                                "runtime_status": "precomputed",
                                "cache_status": "fresh",
                            },
                        }
                    ],
                },
                {
                    **self._planner_report(
                        candidate="crypto_research.dip_rebound/dip_rebound/15Min",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 15Min",
                        next_action="diagnose_next_best_strategy",
                    ),
                    "next_safe_operator_action": "precompute_specific_replay_cache",
                    "next_safe_operator_command": "",
                    "next_data_runtime_action": {
                        "action": "precompute_specific_replay_cache",
                        "data_or_runtime_action": "precompute_specific_replay_cache",
                        "base_strategy_id": "crypto_research.dip_rebound",
                        "profile_id": "dip_rebound",
                        "timeframe": "15Min",
                    },
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "crypto_research.dip_rebound",
                            "profile_id": "dip_rebound",
                            "timeframe": "15Min",
                            "latest_sample_size": 3,
                            "latest_net_return_after_costs": -0.305701,
                            "win_rate": 0.333333,
                            "latest_replay_preparation": {
                                "runtime_status": "precomputed",
                                "cache_status": "fresh",
                            },
                        }
                    ],
                },
                {
                    **self._planner_report(
                        candidate="liquidity_probe.steady_flow/steady_flow/15Min",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy liquidity_probe.steady_flow --profile-id steady_flow --timeframe 15Min",
                        next_action="diagnose_next_best_strategy",
                    ),
                },
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 2)
        self.assertNotEqual(report["stop_reason"], "manual_runtime_action_required")
        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(
            report["step_log"][0]["classification_reason"],
            "precompute_completed_but_only_3_negative_samples",
        )
        self.assertEqual(
            planner.kwargs_history[2]["parked_candidate_keys_this_run"],
            ["crypto_research.dip_rebound/dip_rebound/15Min"],
        )
        self.assertIn("crypto_research.dip_rebound", executed[0])
        self.assertIn("liquidity_probe.steady_flow", executed[1])
        self.assertEqual(report["paper_trading_allowed"], "no")

    def test_runtime_blocked_produces_safe_stop(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="optimise_or_precompute_replay_dataset",
                    data_runtime_action="optimise_or_precompute_replay_dataset",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "runtime_blocked", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["stop_reason"], "stopped_because_data_runtime_action_required")
        self.assertEqual(report["last_result_status"], "runtime_blocked")
        self.assertEqual(report["data_runtime_action_detected"], "yes")
        self.assertEqual(report["data_runtime_stop_selection_reason"], "planner_reported_explicit_data_runtime_action")

    def test_no_progress_deprioritise_does_not_stop_as_data_runtime_when_no_real_data_action_exists(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.balanced/balanced/1Hour",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                    next_action="diagnose_next_best_strategy",
                ),
                {
                    **self._planner_report(
                        candidate="momentum.balanced/balanced/1Hour",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                        next_action="diagnose_next_best_strategy",
                    ),
                    "next_data_runtime_action": {
                        "action": "adjust_signal_generation_research_only",
                        "data_or_runtime_action": "deprioritise_until_new_data",
                    },
                },
                {
                    **self._planner_report(
                        candidate="momentum.balanced/balanced/1Hour",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                        next_action="diagnose_next_best_strategy",
                    ),
                    "next_data_runtime_action": {
                        "action": "adjust_signal_generation_research_only",
                        "data_or_runtime_action": "deprioritise_until_new_data",
                    },
                    "run_scoped_parked_candidates_received": ["momentum.balanced/balanced/1Hour"],
                    "next_actionable_research_candidate_diagnostics": {
                        "candidate_key": "momentum.balanced/balanced/1Hour",
                        "parked_candidates_received": ["momentum.balanced/balanced/1Hour"],
                        "parked_candidate_returned": True,
                        "returned_parked_candidate_reason": "selected_candidate_key_was_present_in_run_scoped_parked_candidates",
                        "ranked_alternatives_considered": [
                            {
                                "candidate_key": "momentum.balanced/balanced/1Hour",
                                "selected": True,
                                "rejection_reason": "",
                            }
                        ],
                    },
                },
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 1)
        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(report["stop_reason"], "loop_detected")
        self.assertNotEqual(report["stop_reason"], "stopped_because_data_runtime_action_required")
        self.assertEqual(report["parked_candidates_this_run"], ["momentum.balanced/balanced/1Hour"])
        self.assertEqual(report["run_scoped_parked_candidates_received"], ["momentum.balanced/balanced/1Hour"])
        self.assertEqual(report["planner_candidate_before_parking"], "momentum.balanced/balanced/1Hour")
        self.assertEqual(report["planner_candidate_after_parking"], "momentum.balanced/balanced/1Hour")
        self.assertEqual(report["parked_candidate_returned"], "yes")
        self.assertEqual(
            report["parked_candidate_return_reason"],
            "selected_candidate_key_was_present_in_run_scoped_parked_candidates",
        )
        self.assertEqual(
            report["ranked_alternatives_considered"][0]["rejection_reason"],
            "",
        )
        self.assertEqual(report["data_runtime_action_detected"], "yes")
        self.assertEqual(
            report["data_runtime_stop_selection_reason"],
            "planner_retained_same_candidate_after_deprioritise_until_new_data_without_real_data_runtime_action",
        )

    def test_generated_candidate_no_progress_reports_operator_readable_reason(self) -> None:
        planner = _StubPlanner(
            [
                {
                    **self._planner_report(
                        candidate="crypto_research.liquidation_wick_reclaim/liquidation_wick_reclaim_confirmed/15Min",
                        command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
                        next_action="run_generated_variant_research",
                        lifecycle_status="variant_research_pending",
                    ),
                    "next_actionable_research_candidate": {
                        "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                        "profile_id": "liquidation_wick_reclaim_confirmed",
                        "timeframe": "15Min",
                        "lifecycle_status": "variant_research_pending",
                    },
                },
                {
                    **self._planner_report(
                        candidate="crypto_research.liquidation_wick_reclaim/liquidation_wick_reclaim_confirmed/15Min",
                        command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
                        next_action="run_generated_variant_research",
                        lifecycle_status="variant_research_pending",
                    ),
                    "next_actionable_research_candidate": {
                        "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                        "profile_id": "liquidation_wick_reclaim_confirmed",
                        "timeframe": "15Min",
                        "lifecycle_status": "variant_research_pending",
                        "no_progress_classification": "insufficient_history",
                        "no_progress_reason": "history coverage was too thin to open any eligible replay windows",
                    },
                },
                {
                    **self._planner_report(
                        candidate="crypto_research.liquidation_wick_reclaim/liquidation_wick_reclaim_confirmed/15Min",
                        command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.liquidation_wick_reclaim --profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min",
                        next_action="run_generated_variant_research",
                        lifecycle_status="variant_research_pending",
                    ),
                    "next_actionable_research_candidate": {
                        "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                        "profile_id": "liquidation_wick_reclaim_confirmed",
                        "timeframe": "15Min",
                        "lifecycle_status": "variant_research_pending",
                        "no_progress_classification": "insufficient_history",
                        "no_progress_reason": "history coverage was too thin to open any eligible replay windows",
                    },
                },
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["stop_reason"], "loop_detected")
        self.assertEqual(
            report["step_log"][0]["classification_reason"],
            "generated_candidate_insufficient_history_for_variant_research",
        )

    def test_stops_before_paper_candidate_audit_command(self) -> None:
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=_StubPlanner(
                [
                    self._planner_report(
                        candidate="mean_reversion.snapback/snapback/1Hour",
                        command=".venv-mac/bin/python main.py --paper-candidate-audit --base-strategy mean_reversion.snapback --profile-id snapback --timeframe 1Hour",
                        next_action="audit_paper_candidate",
                    )
                ]
            ),
            paper_reporter=_StubPaperReporter([self._paper_report(status="approved_for_manual_review")]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["steps_run"], 0)
        self.assertEqual(report["stop_reason"], "candidate_ready_for_manual_paper_audit")
        self.assertEqual(report["candidate_ready_for_manual_paper_audit"], "yes")

    def test_step_summary_captures_before_after_metrics(self) -> None:
        planner = _StubPlanner(
            [
                {
                    **self._planner_report(
                        candidate="momentum.strong/strong/1Day",
                        command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                        next_action="diagnose_next_best_strategy",
                    ),
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "momentum.strong",
                            "profile_id": "strong",
                            "timeframe": "1Day",
                            "latest_sample_size": 4,
                            "latest_net_return_after_costs": -0.2,
                            "win_rate": 0.25,
                        }
                    ],
                },
                {
                    **self._planner_report(
                        candidate="momentum.strong/strong/1Day",
                        command=".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy momentum.strong --profile-id strong --timeframe 1Day --variant-id v1 --symbol MRVL",
                        next_action="validate_symbol_subset_stability",
                    ),
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "momentum.strong",
                            "profile_id": "strong",
                            "timeframe": "1Day",
                            "latest_sample_size": 9,
                            "latest_net_return_after_costs": -0.05,
                            "win_rate": 0.44,
                        }
                    ],
                },
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        step = report["step_log"][0]
        self.assertEqual(step["sample_size_before"], 4)
        self.assertEqual(step["sample_size_after"], 9)
        self.assertEqual(step["net_return_after_costs_before"], -0.2)
        self.assertEqual(step["net_return_after_costs_after"], -0.05)
        self.assertEqual(step["win_rate_before"], 0.25)
        self.assertEqual(step["win_rate_after"], 0.44)
        self.assertIn("--symbol-subset-stability-report", step["next_recommendation"])

    def test_zero_sample_generated_candidate_is_classified_without_reentering_diagnosis(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                    lifecycle_status="variant_research_pending",
                ),
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                    lifecycle_status="insufficient_history_after_variant_research",
                    terminal_research_state="generate_new_strategy_family_or_wait_for_new_market_data",
                    no_actionable_reason="All current and generated candidates are exhausted, blocked, or zero-sample.",
                    next_safe_operator_action="wait_for_new_market_data_or_generate_new_strategy_family",
                    next_check_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                ),
                self._planner_report(
                    candidate="",
                    command=".venv-mac/bin/python main.py --research-expansion-planner",
                    next_action="no_actionable_candidate",
                    research_universe_status="exhausted_current_strategy_set",
                    portfolio_research_status="no_actionable_candidate",
                    terminal_research_state="generate_new_strategy_family_or_wait_for_new_market_data",
                    no_actionable_reason="All current and generated candidates are exhausted, blocked, or zero-sample.",
                    next_safe_operator_action="wait_for_new_market_data_or_generate_new_strategy_family",
                    next_check_command=".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["step_log"][0]["classification_applied"], "deprioritise_until_new_data")
        self.assertEqual(
            report["step_log"][0]["classification_reason"],
            "generated_candidate_was_classified_deprioritised",
        )
        self.assertNotIn("--diagnose-next-best-strategy --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour", executed)
        self.assertEqual(report["paper_trading_allowed"], "no")
        self.assertEqual(
            report["terminal_research_state"],
            "generate_new_strategy_family_or_wait_for_new_market_data",
        )
        self.assertEqual(
            report["next_safe_operator_action"],
            "wait_for_new_market_data_or_generate_new_strategy_family",
        )
        self.assertEqual(
            report["next_check_command"],
            ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
        )

    def test_runtime_blocked_range_breakout_stop_preserves_operator_action(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout/15Min",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout --timeframe 15Min",
                    next_action="continue_research_for_crypto_research.range_breakout",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="optimise_or_precompute_replay_dataset",
                    data_runtime_action="precompute_specific_range_breakout_15Min_replay_cache",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {
                "exit_code": 0,
                "stdout": "runtime_blocked\nnext_required_action=precompute_specific_range_breakout_15Min_replay_cache",
                "stderr": "",
            },
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["last_result_status"], "runtime_blocked")
        self.assertEqual(report["next_required_operator_action"], "precompute_specific_range_breakout_15Min_replay_cache")

    def test_stops_with_replay_prep_did_not_unlock_candidate_when_generic_prep_repeats(self) -> None:
        planner = _StubPlanner(
            [
                {
                    **self._planner_report(
                        candidate="",
                        command="",
                        next_action="optimise_or_precompute_replay_dataset",
                        data_runtime_action="optimise_or_precompute_replay_dataset",
                    ),
                    "ranked_strategies": [
                        {
                            "base_strategy_id": "crypto_research.dip_rebound",
                            "profile_id": "dip_rebound",
                            "timeframe": "15Min",
                            "research_status": "runtime_blocked",
                            "latest_replay_preparation": {
                                "prep_status": "replay_prepared_but_still_slow",
                                "prep_action": "precompute_bounded_dip_rebound_15Min_outcomes",
                            },
                        }
                    ],
                    "next_data_runtime_action": {
                        "action": "optimise_or_precompute_replay_dataset",
                        "data_or_runtime_action": "precompute_bounded_dip_rebound_15Min_outcomes",
                    },
                }
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["stop_reason"], "stopped_because_replay_prep_did_not_unlock_candidate")
        self.assertEqual(report["next_required_operator_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(report["paper_trading_allowed"], "no")

    def test_executes_safe_precompute_command_and_replans(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="",
                    command=".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
                    next_action="precompute_bounded_dip_rebound_15Min_outcomes",
                    data_runtime_action="precompute_bounded_dip_rebound_15Min_outcomes",
                    next_safe_operator_action="precompute_bounded_dip_rebound_15Min_outcomes",
                    next_safe_operator_command=".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes",
                ),
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(executed[0][2], "--precompute-bounded-dip-rebound-15min-outcomes")
        self.assertEqual(executed[1][2], "--run-strategy-variant-research")
        self.assertEqual(report["steps_run"], 2)
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_executes_specific_safe_precompute_command_and_replans(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="",
                    command=".venv-mac/bin/python main.py --precompute-specific-replay-cache --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                    next_action="precompute_specific_replay_cache",
                    data_runtime_action="precompute_specific_replay_cache",
                    next_safe_operator_action="precompute_specific_replay_cache",
                    next_safe_operator_command=".venv-mac/bin/python main.py --precompute-specific-replay-cache --base-strategy momentum.balanced --profile-id balanced --timeframe 1Hour",
                ),
                self._planner_report(
                    candidate="crypto_research.range_breakout/range_breakout_compression_release/1Hour",
                    command=".venv-mac/bin/python main.py --run-strategy-variant-research --base-strategy crypto_research.range_breakout --profile-id range_breakout_compression_release --timeframe 1Hour",
                    next_action="run_generated_variant_research",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(list(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(executed[0][2], "--precompute-specific-replay-cache")
        self.assertEqual(executed[1][2], "--run-strategy-variant-research")
        self.assertEqual(report["steps_run"], 2)
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_manual_runtime_action_required_when_no_safe_precompute_command_exists(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="precompute_specific_replay_cache",
                    data_runtime_action="precompute_specific_replay_cache",
                    next_safe_operator_action="precompute_specific_replay_cache",
                ),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "", "stderr": ""},
        )

        report = runner.run(max_steps=2)

        self.assertEqual(report["stop_reason"], "manual_runtime_action_required")
        self.assertEqual(report["next_required_operator_action"], "precompute_specific_replay_cache")
        self.assertEqual(report["next_safe_operator_command"], "")
        self.assertEqual(report["precompute_mapping_attempted"], "")
        self.assertEqual(report["why_next_safe_operator_command_blank"], "")

    def test_rotation_counts_as_advance_and_continues(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Day",
                    command=".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    next_action="diagnose_next_best_strategy",
                ),
                self._planner_report(
                    candidate="crypto_research.dip_rebound/dip_rebound/1Hour",
                    command=".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    next_action="continue_research_for_crypto_research.dip_rebound",
                ),
                self._planner_report(candidate="", command="", next_action="no_actionable_candidate"),
            ]
        )
        executed = []
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda argv: executed.append(" ".join(argv)) or {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertEqual(report["steps_run"], 2)
        self.assertIn(report["step_log"][0]["step_advanced"], {"yes", "partial"})
        self.assertEqual(report["step_log"][0]["after_candidate"], "crypto_research.dip_rebound/dip_rebound/1Hour")
        self.assertEqual(report["step_log"][1]["before_candidate"], "crypto_research.dip_rebound/dip_rebound/1Hour")
        self.assertIn("crypto_research.dip_rebound", executed[1])
        self.assertEqual(report["stop_reason"], "no_alternative_candidate")

    def test_negative_candidate_rotation_does_not_stop_as_no_progress(self) -> None:
        planner = _StubPlanner(
            [
                self._planner_report(
                    candidate="momentum.strong/strong/1Day",
                    command=".venv-mac/bin/python main.py --strategy-research-planner --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    next_action="continue_research_for_momentum.strong",
                ),
                self._planner_report(
                    candidate="crypto_research.dip_rebound/dip_rebound/1Hour",
                    command=".venv-mac/bin/python main.py --strategy-research-planner --base-strategy crypto_research.dip_rebound --profile-id dip_rebound --timeframe 1Hour",
                    next_action="continue_research_for_crypto_research.dip_rebound",
                ),
                self._planner_report(
                    candidate="",
                    command="",
                    next_action="no_actionable_candidate",
                ),
            ]
        )
        paper = _StubPaperReporter(
            [
                self._paper_report(status="blocked"),
                self._paper_report(status="blocked"),
                self._paper_report(status="blocked"),
            ]
        )
        runner = ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=planner,
            paper_reporter=paper,
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

        report = runner.run(max_steps=3)

        self.assertNotEqual(report["stop_reason"], "stopped_because_no_progress")
        self.assertIn(report["step_log"][0]["step_advanced"], {"yes", "partial"})
        self.assertEqual(report["step_log"][0]["classification_applied"], "")

    def test_main_cli_renders_research_autopilot_summary(self) -> None:
        original_runner = main_module.ResearchAutopilotRunner

        class _StubRunner:
            def run(self, *, max_steps):
                self.max_steps = max_steps
                return {
                    "research_autopilot_status": "stopped",
                    "steps_run": 1,
                    "stop_reason": "stopped_because_max_steps",
                    "last_candidate": "momentum.strong/strong/1Day",
                    "last_command": ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
                    "last_result_status": "executed_research_only",
                    "current_known_best_candidate": "momentum.strong/strong/1Day",
                    "current_paper_candidate": "",
                    "paper_candidate_status": "blocked",
                    "paper_trading_allowed": "no",
                    "next_actionable_research_candidate": "",
                    "next_actionable_research_command": "",
                    "next_required_operator_action": "no_actionable_candidate",
                    "step_log": [],
                }

            def render(self, *, report):
                return f"research_autopilot_status={report['research_autopilot_status']}\nsteps_run={report['steps_run']}"

        main_module.ResearchAutopilotRunner = _StubRunner
        sys.argv = ["main.py", "--research-autopilot", "--max-steps", "5"]
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.ResearchAutopilotRunner = original_runner

        rendered = stdout.getvalue()
        self.assertIn("research_autopilot_status=stopped", rendered)
        self.assertIn("steps_run=1", rendered)

    def _runner_for_repeating_commands(self) -> ResearchAutopilotRunner:
        return ResearchAutopilotRunner(
            usage_ledger=_StubLedger(),
            planner=_StubPlanner([self._planner_report(), self._planner_report(), self._planner_report()]),
            paper_reporter=_StubPaperReporter([self._paper_report(), self._paper_report(), self._paper_report()]),
            command_executor=lambda _argv: {"exit_code": 0, "stdout": "ok", "stderr": ""},
        )

    def _planner_report(
        self,
        *,
        candidate: str = "momentum.strong/strong/1Day",
        command: str = ".venv-mac/bin/python main.py --diagnose-next-best-strategy --base-strategy momentum.strong --profile-id strong --timeframe 1Day",
        next_action: str = "diagnose_next_best_strategy",
        data_runtime_action: str = "",
        research_universe_status: str = "",
        portfolio_research_status: str = "",
        lifecycle_status: str = "",
        terminal_research_state: str = "",
        no_actionable_reason: str = "",
        next_safe_operator_action: str = "",
        next_safe_operator_command: str = "",
        next_check_command: str = "",
    ) -> dict[str, object]:
        candidate_summary = {}
        if candidate:
            base_strategy_id, profile_id, timeframe = candidate.split("/")
            candidate_summary = {
                "base_strategy_id": base_strategy_id,
                "profile_id": profile_id,
                "timeframe": timeframe,
                "lifecycle_status": lifecycle_status,
            }
        return {
            "next_actionable_research_candidate": candidate_summary,
            "next_actionable_research_command": command,
            "next_portfolio_action": next_action,
            "next_data_runtime_action": {"action": data_runtime_action},
            "research_universe_status": research_universe_status,
            "portfolio_research_status": portfolio_research_status,
            "terminal_research_state": terminal_research_state,
            "no_actionable_reason": no_actionable_reason,
            "next_safe_operator_action": next_safe_operator_action,
            "next_safe_operator_command": next_safe_operator_command,
            "next_check_command": next_check_command,
        }

    def _paper_report(self, *, status: str = "blocked", paper_trading_allowed: str = "no") -> dict[str, object]:
        return {
            "current_known_best_candidate": "momentum.strong/strong/1Day",
            "current_paper_candidate": "",
            "paper_candidate_status": status,
            "paper_trading_allowed": paper_trading_allowed,
            "next_required_action": "review_portfolio_research",
        }


if __name__ == "__main__":
    unittest.main()
