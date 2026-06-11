from __future__ import annotations

from io import StringIO
import contextlib
from datetime import datetime, timedelta
import sys
from types import SimpleNamespace
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

    def test_self_improvement_status_json_outputs_structured_report(self) -> None:
        original_reporter = main_module.SelfImprovementStatusReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--self-improvement-status", "--json"]

        class _StatusReport:
            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "self_improvement_status": "flat_collecting_evidence",
                    "explanation": "x",
                }

        main_module.SelfImprovementStatusReport = _StatusReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.SelfImprovementStatusReport = original_reporter
            sys.argv = original_argv

        self.assertIn('"self_improvement_status": "flat_collecting_evidence"', stdout.getvalue())

    def test_evidence_quality_report_json_outputs_structured_report(self) -> None:
        original_reporter = main_module.EvidenceQualityReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--evidence-quality-report", "--json"]

        class _EvidenceQualityReport:
            def build_report(self, *, lookback_hours: int = 24) -> dict[str, object]:
                return {
                    "status": "ok",
                    "single_most_actionable_next_fix": "fix outcome recording",
                    "verdict": "mixed",
                    "lookback_hours": lookback_hours,
                }

        main_module.EvidenceQualityReport = _EvidenceQualityReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.EvidenceQualityReport = original_reporter
            sys.argv = original_argv

        self.assertIn('"single_most_actionable_next_fix": "fix outcome recording"', stdout.getvalue())

    def test_outcome_recording_status_json_outputs_structured_report(self) -> None:
        original_reporter = main_module.OutcomeRecordingStatusReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--outcome-recording-status", "--json"]

        class _OutcomeRecordingStatusReport:
            def build_report(self, *, lookback_hours: int = 24) -> dict[str, object]:
                return {
                    "status": "ok",
                    "verdict": "mixed",
                    "lookback_hours": lookback_hours,
                    "latest_heartbeat_outcome_step": {"mode": "evaluated"},
                }

        main_module.OutcomeRecordingStatusReport = _OutcomeRecordingStatusReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.OutcomeRecordingStatusReport = original_reporter
            sys.argv = original_argv

        self.assertIn('"latest_heartbeat_outcome_step": {"mode": "evaluated"}', stdout.getvalue())

    def test_historical_coverage_report_json_outputs_structured_report(self) -> None:
        original_reporter = main_module.HistoricalCoverageReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--historical-coverage-report", "--json"]

        class _HistoricalCoverageReport:
            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "verdict": "only_1min_backfilled",
                    "symbol_coverage_gap_count": 0,
                }

        main_module.HistoricalCoverageReport = _HistoricalCoverageReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalCoverageReport = original_reporter
            sys.argv = original_argv

        self.assertIn('"verdict": "only_1min_backfilled"', stdout.getvalue())

    def test_operator_summary_email_renders_block_header(self) -> None:
        original_reporter = main_module.OperatorSummaryReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--operator-summary", "--operator-summary-format", "email"]

        class _OperatorSummaryReport:
            def render_email(self) -> str:
                return "====\nEMAIL\n===="

        main_module.OperatorSummaryReport = _OperatorSummaryReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.OperatorSummaryReport = original_reporter
            sys.argv = original_argv

        self.assertIn("EMAIL", stdout.getvalue())

    def test_operator_summary_json_outputs_structured_report(self) -> None:
        original_reporter = main_module.OperatorSummaryReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--operator-summary", "--json"]

        class _OperatorSummaryReport:
            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "system_healthy": "yes",
                    "fresh_data": "yes",
                }

        main_module.OperatorSummaryReport = _OperatorSummaryReport
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.OperatorSummaryReport = original_reporter
            sys.argv = original_argv

        self.assertIn('"system_healthy": "yes"', stdout.getvalue())

    def test_send_operator_summary_email_uses_smtp_client(self) -> None:
        original_reporter = main_module.OperatorSummaryReport
        original_client = main_module.SmtpEmailClient
        original_loader = main_module.load_runtime_config
        original_argv = sys.argv
        sys.argv = ["main.py", "--send-operator-summary-email"]
        sent: dict[str, object] = {}

        class _OperatorSummaryReport:
            def __init__(self, config=None) -> None:
                self.config = config

            def email_subject(self) -> str:
                return "subject"

            def render_email(self) -> str:
                return "body"

        class _SmtpEmailClient:
            def __init__(self, **kwargs) -> None:
                sent["client_kwargs"] = kwargs

            def send_message(self, **kwargs) -> None:
                sent["message_kwargs"] = kwargs

        main_module.OperatorSummaryReport = _OperatorSummaryReport
        main_module.SmtpEmailClient = _SmtpEmailClient
        main_module.load_runtime_config = lambda: type(
            "Cfg",
            (),
            {
                "smtp_host": "smtp.example.test",
                "smtp_port": 465,
                "smtp_user": "user",
                "smtp_pass": "pass",
                "smtp_use_ssl": True,
                "smtp_timeout_seconds": 10,
                "smtp_from": "from@example.test",
                "smtp_to": ("to@example.test",),
            },
        )()
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.OperatorSummaryReport = original_reporter
            main_module.SmtpEmailClient = original_client
            main_module.load_runtime_config = original_loader
            sys.argv = original_argv

        self.assertEqual(sent["client_kwargs"]["host"], "smtp.example.test")
        self.assertEqual(
            sent["message_kwargs"],
            {
                "subject": "subject",
                "body": "body",
                "from_address": "from@example.test",
                "to_addresses": ("to@example.test",),
            },
        )
        self.assertIn("operator_summary_email_sent=to@example.test", stdout.getvalue())

    def test_operator_summary_handles_lightweight_ledger_fallback(self) -> None:
        from app.framework.reporting.operator_summary import OperatorSummaryReport

        class _Ledger:
            paper_trade_orders_recorded = 0
            live_trade_orders_recorded = 0

        report = OperatorSummaryReport(usage_ledger=_Ledger()).build_report()

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["system_healthy"], "unknown")
        self.assertEqual(report["broker_orders_created"], 0)
        self.assertIn("lightweight test/runtime context", report["why_no_trades_happening"])

    def test_operator_summary_explains_no_newer_cycle_due_yet(self) -> None:
        import app.framework.reporting.operator_summary as operator_summary_module

        original_status = operator_summary_module.SelfImprovementStatusReport
        now = datetime.now().astimezone()
        latest_cycle = now - timedelta(minutes=30)
        latest_tick = now - timedelta(seconds=30)

        class _StatusReport:
            def __init__(self, **_kwargs) -> None:
                pass

            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "self_improvement_status": "stuck",
                    "learning": {
                        "latest_persisted_cycle_time": latest_cycle.isoformat(),
                        "latest_persisted_cycle_origin": "launchd_scheduled",
                        "real_research_cycles_in_lookback": 5,
                    },
                    "evidence_quality": {"evidence_quality_status": "flat"},
                    "freshness_diagnostics": {
                        "fresh_historical_bars_detected": "no",
                        "provider_error_count": 0,
                    },
                    "stuck_analysis": {
                        "system_stuck": False,
                        "strategy_evidence_stuck": True,
                        "replay_window_advancing": "no",
                        "dominant_blocker": "net_return_below_threshold",
                    },
                    "closest_to_promotion": [],
                }

        class _Ledger:
            def get_latest_tick_run(self) -> dict[str, object]:
                return {"started_at": latest_tick.isoformat()}

        operator_summary_module.SelfImprovementStatusReport = _StatusReport
        try:
            report = operator_summary_module.OperatorSummaryReport(
                config=SimpleNamespace(
                    research_cycle_min_interval_minutes=60,
                    control_tick_interval_seconds=60,
                ),
                usage_ledger=_Ledger(),
            ).build_report()
        finally:
            operator_summary_module.SelfImprovementStatusReport = original_status

        self.assertEqual(report["system_healthy"], "yes")
        self.assertEqual(report["data_freshness_status"], "stale_between_cycles")
        self.assertEqual(report["heartbeat_running"], "yes")
        self.assertEqual(report["research_cycle_overdue"], "no")
        self.assertEqual(report["latest_cycle_fresh_at_report_time"], "yes")
        self.assertIn(
            "running normally and the next research cycle is not overdue",
            report["why_no_trades_happening"],
        )

    def test_operator_summary_explains_overdue_research_cycle(self) -> None:
        import app.framework.reporting.operator_summary as operator_summary_module

        original_status = operator_summary_module.SelfImprovementStatusReport
        now = datetime.now().astimezone()
        latest_cycle = now - timedelta(minutes=90)
        latest_tick = now - timedelta(minutes=10)

        class _StatusReport:
            def __init__(self, **_kwargs) -> None:
                pass

            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "self_improvement_status": "stuck",
                    "learning": {
                        "latest_persisted_cycle_time": latest_cycle.isoformat(),
                        "latest_persisted_cycle_origin": "launchd_scheduled",
                        "real_research_cycles_in_lookback": 5,
                    },
                    "evidence_quality": {"evidence_quality_status": "flat"},
                    "freshness_diagnostics": {
                        "fresh_historical_bars_detected": "no",
                        "provider_error_count": 0,
                    },
                    "stuck_analysis": {
                        "system_stuck": False,
                        "strategy_evidence_stuck": True,
                        "replay_window_advancing": "no",
                        "dominant_blocker": "net_return_below_threshold",
                    },
                    "closest_to_promotion": [],
                }

        class _Ledger:
            def get_latest_tick_run(self) -> dict[str, object]:
                return {"started_at": latest_tick.isoformat()}

        operator_summary_module.SelfImprovementStatusReport = _StatusReport
        try:
            report = operator_summary_module.OperatorSummaryReport(
                config=SimpleNamespace(
                    research_cycle_min_interval_minutes=60,
                    control_tick_interval_seconds=60,
                ),
                usage_ledger=_Ledger(),
            ).build_report()
        finally:
            operator_summary_module.SelfImprovementStatusReport = original_status

        self.assertEqual(report["system_healthy"], "no")
        self.assertEqual(report["data_freshness_status"], "stale_overdue")
        self.assertEqual(report["research_cycle_overdue"], "yes")
        self.assertIn("stale or overdue", report["why_no_trades_happening"])

    def test_operator_summary_explains_stale_freshness(self) -> None:
        import app.framework.reporting.operator_summary as operator_summary_module

        original_status = operator_summary_module.SelfImprovementStatusReport
        now = datetime.now().astimezone()
        latest_cycle = now - timedelta(minutes=30)
        latest_tick = now - timedelta(seconds=30)

        class _StatusReport:
            def __init__(self, **_kwargs) -> None:
                pass

            def build_report(self) -> dict[str, object]:
                return {
                    "status": "ok",
                    "self_improvement_status": "stuck",
                    "learning": {
                        "latest_persisted_cycle_time": latest_cycle.isoformat(),
                        "latest_persisted_cycle_origin": "launchd_scheduled",
                        "real_research_cycles_in_lookback": 5,
                    },
                    "evidence_quality": {"evidence_quality_status": "flat"},
                    "freshness_diagnostics": {
                        "fresh_historical_bars_detected": "no",
                        "provider_error_count": 0,
                    },
                    "stuck_analysis": {
                        "system_stuck": True,
                        "strategy_evidence_stuck": True,
                        "replay_window_advancing": "no",
                        "dominant_blocker": "net_return_below_threshold",
                    },
                    "closest_to_promotion": [],
                }

        class _Ledger:
            def get_latest_tick_run(self) -> dict[str, object]:
                return {"started_at": latest_tick.isoformat()}

        operator_summary_module.SelfImprovementStatusReport = _StatusReport
        try:
            report = operator_summary_module.OperatorSummaryReport(
                config=SimpleNamespace(
                    research_cycle_min_interval_minutes=60,
                    control_tick_interval_seconds=60,
                ),
                usage_ledger=_Ledger(),
            ).build_report()
        finally:
            operator_summary_module.SelfImprovementStatusReport = original_status

        self.assertEqual(report["system_healthy"], "yes")
        self.assertEqual(report["fresh_data"], "no")
        self.assertEqual(report["data_freshness_status"], "stale_between_cycles")
        self.assertEqual(report["strategy_evidence_stuck"], "yes")
        self.assertIn("running normally and the next research cycle is not overdue", report["why_no_trades_happening"])


if __name__ == "__main__":
    unittest.main()
