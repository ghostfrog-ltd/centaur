from __future__ import annotations

import contextlib
from io import StringIO
import sys
import unittest

import main as main_module
from app.framework.reporting.paper_candidate_audit import (
    MANUAL_APPROVAL_REMINDER,
    SAFETY_STATEMENT,
    PaperCandidateAuditReport,
)


class _Ledger:
    backend = "sqlite"

    def __init__(self) -> None:
        self.definitions = [
            {
                "variant_id": "baseline",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
                "params_json": {"max_movement_pct": -0.18, "min_trade_count": 40, "min_discovery_score": 4.0, "stop_loss_pct": 0.01, "target_multiple": 1.75},
                "generation_reason": "baseline_profile",
                "created_at": "2026-06-08T22:00:00+01:00",
                "latest_evaluation_at": "2026-06-08T22:05:00+01:00",
            },
            {
                "variant_id": "holding-window-240",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "1Hour",
                "params_json": {"max_movement_pct": -0.18, "min_trade_count": 40, "min_discovery_score": 4.0, "stop_loss_pct": 0.01, "target_multiple": 1.75, "holding_window_minutes": 240},
                "generation_reason": "holding_window_240",
                "created_at": "2026-06-08T22:00:00+01:00",
                "latest_evaluation_at": "2026-06-08T22:10:00+01:00",
            },
        ]
        self.evaluations = [
            {
                "variant_id": "holding-window-240",
                "sample_size": 148,
                "gross_return": 0.927728,
                "net_return_after_costs": 0.547019,
                "win_rate": 0.682432,
                "drawdown": 0.659232,
                "average_winner": 1.301388,
                "average_loser": -1.074072,
                "symbols_tested": ["WDC", "MU", "QCOM"],
                "gross_positive_net_negative_count": 12,
                "beats_baseline": True,
                "beats_thresholds": True,
                "recommended_status": "paper_candidate_requires_manual_approval",
                "evaluated_at": "2026-06-08T22:10:00+01:00",
                "raw_json": {"target_hit_count": 90, "stop_hit_count": 30, "time_exit_count": 23},
            },
            {
                "variant_id": "baseline",
                "sample_size": 191,
                "gross_return": 0.662526,
                "net_return_after_costs": 0.282029,
                "win_rate": 0.544503,
                "drawdown": 0.546362,
                "average_winner": 1.137886,
                "average_loser": -0.741065,
                "symbols_tested": ["WDC", "MU", "QCOM"],
                "gross_positive_net_negative_count": 19,
                "beats_baseline": False,
                "beats_thresholds": False,
                "recommended_status": "evaluated",
                "evaluated_at": "2026-06-08T22:05:00+01:00",
                "raw_json": {"target_hit_count": 79, "stop_hit_count": 9, "time_exit_count": 98},
            },
        ]

    def list_strategy_variant_definitions(self, **_kwargs):
        return list(self.definitions)

    def list_strategy_variant_evaluations(self, **_kwargs):
        return list(self.evaluations)


class _VariantReporter:
    def build_report(self, **_kwargs):
        return {
            "baseline": {
                "variant_id": "baseline",
                "params_json": {"stop_loss_pct": 0.01},
                "metrics": {
                    "sample_size": 191,
                    "net_return_after_costs": 0.282029,
                    "win_rate": 0.544503,
                    "drawdown": 0.546362,
                    "raw_json": {"target_hit_count": 79, "stop_hit_count": 9, "time_exit_count": 98},
                },
            },
            "variants_generated": 15,
            "variants_evaluated": 16,
            "variants": [
                {
                    "variant_id": "holding-window-240",
                    "net_return_after_costs": 0.547019,
                    "win_rate": 0.682432,
                    "drawdown": 0.659232,
                    "beats_baseline": True,
                    "beats_thresholds": True,
                }
            ],
        }


class _VariantService:
    def _resolve_profile(self, **_kwargs):
        return object()

    def _profile_from_variant(self, **_kwargs):
        return object()

    def collect_variant_outcomes(self, **_kwargs):
        return {"outcomes": _sample_outcomes()}


class _LossReporter:
    from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport as _Real

    def __init__(self) -> None:
        real = self._Real.__new__(self._Real)
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)


class PaperCandidateAuditTests(unittest.TestCase):
    def test_default_report_uses_read_only_skip_bootstrap_ledger(self) -> None:
        calls: list[dict[str, object]] = []
        original_usage_ledger = PaperCandidateAuditReport.__init__.__globals__["UsageLedger"]

        class _StubLedger:
            def __init__(self, **kwargs: object) -> None:
                calls.append(dict(kwargs))

            def list_strategy_variant_definitions(self, **_kwargs):
                return []

            def list_strategy_variant_evaluations(self, **_kwargs):
                return []

        PaperCandidateAuditReport.__init__.__globals__["UsageLedger"] = _StubLedger
        try:
            report = PaperCandidateAuditReport(config=type("Cfg", (), {})())
        finally:
            PaperCandidateAuditReport.__init__.__globals__["UsageLedger"] = original_usage_ledger

        self.assertIsInstance(report.usage_ledger, _StubLedger)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["read_only"])
        self.assertTrue(calls[0]["skip_schema_bootstrap"])
        self.assertEqual(calls[0]["query_timeout_ms"], 15000)
        self.assertIsNone(calls[0]["lock_timeout_ms"])

    def _report(self) -> PaperCandidateAuditReport:
        report = PaperCandidateAuditReport.__new__(PaperCandidateAuditReport)
        report.config = type("Cfg", (), {"research_min_proposals": 50})()
        report.usage_ledger = _Ledger()
        report.variant_reporter = _VariantReporter()
        report.variant_service = _VariantService()
        report.loss_reporter = _LossReporter()
        return report

    def test_audit_finds_paper_candidate_variant_and_compares_to_baseline(self) -> None:
        built = self._report().build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback", timeframe="1Hour")
        self.assertEqual(built["candidate_variant"]["variant_id"], "holding-window-240")
        self.assertTrue(built["candidate_vs_baseline"]["beats_baseline"])
        self.assertTrue(built["candidate_vs_baseline"]["beats_thresholds"])

    def test_audit_flags_concentration_risk(self) -> None:
        built = self._report().build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback", timeframe="1Hour")
        self.assertIn("one_symbol_dominates_profit", built["fragility_flags"])
        self.assertEqual(built["audit_verdict"], "paper_candidate_reject_due_to_concentration")
        self.assertEqual(built["audit_status"], "parked_until_new_data")
        self.assertEqual(built["paper_trading_allowed"], "no")
        self.assertEqual(built["paper_block_reason"], "concentration_fragility")
        self.assertEqual(built["required_next_action"], "collect_wider_replay_evidence")
        self.assertIn("--collect-symbol-replay-evidence", built["next_recommended_command"])

    def test_audit_includes_manual_approval_and_safety_statement(self) -> None:
        rendered = self._report().render(base_strategy_id="mean_reversion.snapback", profile_id="snapback", timeframe="1Hour")
        self.assertIn(MANUAL_APPROVAL_REMINDER, rendered)
        self.assertIn(SAFETY_STATEMENT, rendered)
        self.assertIn("audit_status=parked_until_new_data", rendered)
        self.assertIn("paper_trading_allowed=no", rendered)
        self.assertNotIn("paper approved", rendered.lower())
        self.assertNotIn("live enabled", rendered.lower())

    def test_cli_renders_audit(self) -> None:
        original_reporter = main_module.PaperCandidateAuditReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--paper-candidate-audit", "--base-strategy", "mean_reversion.snapback", "--profile-id", "snapback", "--timeframe", "1Hour"]

        class _Reporter:
            def render(self, **_kwargs):
                return f"Paper Candidate Audit\n{MANUAL_APPROVAL_REMINDER}\n{SAFETY_STATEMENT}"

        main_module.PaperCandidateAuditReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.PaperCandidateAuditReport = original_reporter
            sys.argv = original_argv
        text = stdout.getvalue()
        self.assertIn("Paper Candidate Audit", text)
        self.assertIn(MANUAL_APPROVAL_REMINDER, text)
        self.assertIn(SAFETY_STATEMENT, text)


def _sample_outcomes() -> list[dict[str, object]]:
    rows = []
    for idx in range(80):
        rows.append(_outcome("WDC", "2026-05-02T12:00:00+01:00", "target_hit", 1.4, 1.8, 120, -0.55, 1.45, 150, -0.42, 5.2))
    for idx in range(10):
        rows.append(_outcome("MU", "2026-05-10T12:00:00+01:00", "stop_hit", -1.3, -1.0, 120, -0.85, 0.7, 130, -0.38, 5.1))
    for idx in range(40):
        rows.append(_outcome("QCOM", "2026-06-03T12:00:00+01:00", "time_exit", -0.2, 0.1, 120, -0.35, 1.0, 140, -0.31, 5.4))
    for idx in range(18):
        rows.append(_outcome("MU", "2026-06-10T12:00:00+01:00", "target_hit", 0.9, 1.3, 120, -0.4, 1.0, 160, -0.33, 5.3))
    return rows


def _outcome(symbol, evaluated_at, status, net_return, gross_return, minutes, mae, mfe, trade_count, movement_pct, discovery_score):
    return {
        "evaluated_at": evaluated_at,
        "checkpoint_minutes": minutes,
        "outcome_status": status,
        "realized_return_pct": net_return,
        "gross_realized_return_pct": gross_return,
        "max_adverse_excursion_pct": mae,
        "max_favorable_excursion_pct": mfe,
        "proposal_context": {
            "symbol": symbol,
            "trade_count": trade_count,
            "movement_pct": movement_pct,
            "discovery_score": discovery_score,
            "signal_rank": 1,
        },
    }


if __name__ == "__main__":
    unittest.main()
