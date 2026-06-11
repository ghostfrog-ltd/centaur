from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import contextlib
import sys
import unittest

import main as main_module
from app.framework.reporting.symbol_replay_evidence_plan import (
    ALLOWED_EVIDENCE_ACTION_VERDICTS,
    SAFETY_STATEMENT,
    SymbolReplayEvidencePlanReport,
)


class _FakeLedger:
    backend = "sqlite"

    def __init__(self, *, coverage_rows=None, historical_rows=None, definitions=None):
        self.coverage_rows = list(coverage_rows or [])
        self.historical_rows = list(historical_rows or [])
        self.definitions = list(definitions or [])
        self.persisted = []

    def list_strategy_variant_definitions(self, **_kwargs):
        return list(self.definitions)

    def summarize_historical_bar_coverage(self, **_kwargs):
        return list(self.coverage_rows)

    def list_historical_bars(self, **kwargs):
        start_at = kwargs.get("start_at")
        end_at = kwargs.get("end_at")
        symbol_filter = {str(item).upper() for item in list(kwargs.get("symbols", []) or [])}
        rows = []
        for row in self.historical_rows:
            symbol = str(row.get("symbol", "")).upper()
            stamp = row.get("bar_timestamp")
            if symbol_filter and symbol not in symbol_filter:
                continue
            if isinstance(start_at, datetime) and isinstance(stamp, datetime) and stamp < start_at:
                continue
            if isinstance(end_at, datetime) and isinstance(stamp, datetime) and stamp > end_at:
                continue
            rows.append(dict(row))
        return rows

    def record_strategy_variant_evaluation(self, **kwargs):
        self.persisted.append(dict(kwargs))
        return dict(kwargs)


class _FakeService:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def _resolve_profile(self, **_kwargs):
        return object()

    def _profile_from_variant(self, **_kwargs):
        return object()

    def collect_variant_outcomes(self, **_kwargs):
        return {"outcomes": list(self.outcomes)}


class _FakeSymbolStabilityReporter:
    def build_report(self, **kwargs):
        return {
            "stability_verdict": "symbol_unstable_across_periods",
            "selected_symbol_summary": {
                "sample_size": 31,
                "gross_return_before_costs": -0.02,
                "net_return_after_costs": -0.05,
                "win_rate": 0.41,
                "drawdown": 1.1,
            },
            "cohort_comparison": {"rows": [{"symbol": "WDC"}, {"symbol": "STX"}]},
            "narrow_vs_wide_comparison": {
                "narrow_net_return": 0.19,
                "narrow_win_rate": 0.57,
                "signal_survives_wider_period": False,
            },
        }

    def render(self, **kwargs):
        return f"symbol-stability-for-{kwargs['symbol']}"


class SymbolReplayEvidencePlanTests(unittest.TestCase):
    def test_current_symbol_evidence_summary_is_produced(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        current = built["current_symbol_evidence"]
        self.assertEqual(current["number_of_bars"], 40)
        self.assertEqual(current["existing_stability_sample_size"], 21)
        self.assertGreaterEqual(current["number_of_months_covered"], 2)

    def test_missing_symbol_is_handled_safely(self) -> None:
        report = _report(definitions=[])
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="missing-variant",
            symbol="WDC",
        )
        self.assertEqual(built["evidence_action_verdict"], "no_action_available")
        self.assertFalse(built["execution_available"])

    def test_variant_generation_reason_alias_is_resolved(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="holding-window-240",
            symbol="WDC",
        )
        self.assertEqual(built["variant_id"], "holding-window-240")
        self.assertIn(built["evidence_action_verdict"], ALLOWED_EVIDENCE_ACTION_VERDICTS)

    def test_evidence_action_verdict_is_allowed(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertIn(built["evidence_action_verdict"], ALLOWED_EVIDENCE_ACTION_VERDICTS)

    def test_no_paper_or_live_state_can_be_produced(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        joined = str(built).lower()
        self.assertNotIn("paper_approved", joined)
        self.assertNotIn("live_candidate", joined)

    def test_thresholds_remain_unchanged(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        joined = f"{built['proposed_next_research_action']} {built['proposed_next_command']}".lower()
        self.assertNotIn("lower threshold", joined)
        self.assertNotIn("widen risk", joined)

    def test_safety_statement_included(self) -> None:
        report = _report()
        rendered = report.render(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
        )
        self.assertIn(SAFETY_STATEMENT, rendered)

    def test_execute_only_runs_research_only_follow_up(self) -> None:
        report = _report()
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
            execute=True,
        )
        self.assertEqual(built["execution"]["status"], "executed_research_only")
        self.assertIn("symbol-stability-for-WDC", built["execution"]["output_preview"])
        self.assertIn("--wider-period", built["execution"]["executed_command"])
        self.assertTrue(report.usage_ledger.persisted)

    def test_cli_command_auto_executes_safe_follow_up(self) -> None:
        original_reporter = main_module.SymbolReplayEvidencePlanReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--collect-symbol-replay-evidence",
            "--base-strategy",
            "mean_reversion.snapback",
            "--variant-id",
            "variant-240",
            "--symbol",
            "WDC",
        ]

        class _Reporter:
            def render(self, **kwargs):
                return f"execute={kwargs['execute']}"

        main_module.SymbolReplayEvidencePlanReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.SymbolReplayEvidencePlanReport = original_reporter
            sys.argv = original_argv
        self.assertIn("execute=True", stdout.getvalue())

    def test_unsupported_execution_is_reported_safely(self) -> None:
        report = _report(coverage_rows=[], historical_rows=[])
        built = report.build_report(
            base_strategy_id="mean_reversion.snapback",
            variant_id="variant-240",
            symbol="WDC",
            execute=True,
        )
        self.assertEqual(built["execution"]["status"], "refused_unsupported")
        self.assertEqual(built["evidence_action_verdict"], "no_action_available")
        self.assertTrue(report.usage_ledger.persisted)

    def test_cli_command_invokes_report(self) -> None:
        original_reporter = main_module.SymbolReplayEvidencePlanReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--collect-symbol-replay-evidence",
            "--base-strategy",
            "mean_reversion.snapback",
            "--variant-id",
            "variant-240",
            "--symbol",
            "WDC",
        ]

        class _Reporter:
            def render(self, **kwargs):
                return f"evidence-plan-for-{kwargs['symbol']}-execute-{kwargs['execute']}"

        main_module.SymbolReplayEvidencePlanReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.SymbolReplayEvidencePlanReport = original_reporter
            sys.argv = original_argv
        self.assertIn("evidence-plan-for-WDC-execute-True", stdout.getvalue())


def _report(*, coverage_rows=None, historical_rows=None, definitions=None, outcomes=None):
    report = SymbolReplayEvidencePlanReport.__new__(SymbolReplayEvidencePlanReport)
    report.config = _FakeConfig()
    report.usage_ledger = _FakeLedger(
        coverage_rows=[_coverage_row()] if coverage_rows is None else coverage_rows,
        historical_rows=_historical_rows() if historical_rows is None else historical_rows,
        definitions=[_definition()] if definitions is None else definitions,
    )
    report.service = _FakeService(outcomes or _outcomes())
    report.symbol_stability_reporter = _FakeSymbolStabilityReporter()
    return report


class _FakeConfig:
    shadow_checkpoint_windows = ("15m", "1h", "4h")
    historical_replay_default_days = 5


def _definition():
    return {
        "variant_id": "variant-240",
        "base_strategy_id": "mean_reversion.snapback",
        "profile_id": "snapback",
        "timeframe": "15Min",
        "params_json": {
            "holding_window_minutes": 240,
            "max_movement_pct": -0.18,
            "min_discovery_score": 4.0,
            "min_trade_count": 40,
            "stop_loss_pct": 0.01,
            "target_multiple": 1.75,
        },
    }


def _coverage_row():
    start = datetime.now().astimezone() - timedelta(days=80)
    end = datetime.now().astimezone() - timedelta(days=2)
    return {
        "earliest_bar_timestamp": start,
        "latest_bar_timestamp": end,
        "sources": ["alpaca_market_data"],
        "venues": ["iex"],
    }


def _historical_rows():
    start = datetime.now().astimezone() - timedelta(days=80)
    rows = []
    for idx in range(40):
        rows.append(
            {
                "symbol": "WDC",
                "source": "alpaca_market_data",
                "bar_timestamp": start + timedelta(days=2 * idx),
            }
        )
    return rows


def _outcomes():
    base = datetime.now().astimezone() - timedelta(days=120)
    return [
        {
            "evaluated_at": (base + timedelta(days=7 * idx)).isoformat(),
            "realized_return_pct": 0.2 if idx % 3 else -0.1,
            "proposal_context": {"symbol": "WDC"},
        }
        for idx in range(21)
    ]


if __name__ == "__main__":
    unittest.main()
