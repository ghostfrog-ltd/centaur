from __future__ import annotations

import contextlib
from io import StringIO
import sys
import unittest

import main as main_module
from app.framework.reporting.replay_dataset_preparation import (
    ReplayDatasetPreparationReport,
    SAFETY_STATEMENT,
)


class _StubLedger:
    def __init__(self) -> None:
        self.recorded: list[dict[str, object]] = []

    def summarize_historical_bar_coverage(self, *, asset_class=None, symbols=None, timeframes=None):
        asset_class = str(asset_class or "")
        timeframe = list(timeframes or [""])[0]
        rows = []
        for symbol in list(symbols or []):
            row_count = 240 if asset_class == "crypto" and timeframe == "15Min" and symbol == "BTCUSD" else 0
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "row_count": row_count,
                    "latest_bar_timestamp": "2026-06-09T11:45:00+00:00" if row_count else None,
                }
            )
        return rows

    def record_strategy_variant_evaluation(self, **kwargs):
        self.recorded.append(dict(kwargs))
        return kwargs["evaluation_id"]


class _StubPlanner:
    def build_report(self):
        return {
            "next_portfolio_action": "optimise_or_precompute_replay_dataset",
            "next_actionable_research_candidate": None,
            "ranked_strategies": [
                {
                    "base_strategy_id": "crypto_research.dip_rebound",
                    "profile_id": "dip_rebound",
                    "timeframe": "15Min",
                    "research_status": "runtime_blocked",
                    "zero_decision_reason": "historical_bar_read_timeout",
                    "latest_sample_size": 0,
                },
                {
                    "base_strategy_id": "mean_reversion.snapback",
                    "profile_id": "snapback",
                    "timeframe": "1Hour",
                    "research_status": "data_gap",
                    "zero_decision_reason": "no_bars_for_timeframe",
                    "latest_sample_size": 0,
                },
            ],
        }


class ReplayDatasetPreparationReportTests(unittest.TestCase):
    def test_report_is_research_only_and_persists_bounded_summaries(self) -> None:
        ledger = _StubLedger()
        report = ReplayDatasetPreparationReport(
            config=type(
                "Cfg",
                (),
                {
                    "discovery_crypto_symbols": ["BTCUSD", "ETHUSD"],
                    "discovery_equity_symbols": ["AAPL", "MSFT"],
                },
            )(),
            usage_ledger=ledger,
            planner=_StubPlanner(),
        ).build_report()

        self.assertEqual(report["paper_trades_created"], "no")
        self.assertEqual(report["live_changed"], "no")
        self.assertEqual(report["thresholds_changed"], "no")
        self.assertEqual(report["promotion_policy_changed"], "no")
        self.assertEqual(report["current_replay_blocker_asset_class"], "crypto")
        self.assertEqual(
            report["strategies_needing_precomputed_replay_outcomes"][0]["base_strategy_id"],
            "crypto_research.dip_rebound",
        )
        self.assertEqual(report["strategy_preparation"][0]["blocker_type"], "slow_reads")
        self.assertEqual(report["strategy_preparation"][1]["blocker_type"], "missing_bars")
        self.assertEqual(report["strategy_preparation"][0]["prep_status"], "replay_prepared_but_still_slow")
        self.assertEqual(report["strategy_preparation"][0]["prep_action"], "precompute_bounded_dip_rebound_15Min_outcomes")
        self.assertEqual(report["strategy_preparation"][1]["prep_status"], "missing_timeframe_bars")
        self.assertEqual(report["strategy_preparation"][1]["prep_action"], "backfill_or_resample_1Hour_bars")
        self.assertEqual(report["replay_prep_outcome"], "replay_prepared_but_still_slow")
        self.assertEqual(report["persistence"]["evaluation_count"], 3)
        self.assertEqual(len(ledger.recorded), 3)
        self.assertTrue(
            all(item["dataset_id"] == "replay_dataset_preparation_summary" for item in ledger.recorded)
        )
        self.assertTrue(
            all(item["notes"] == SAFETY_STATEMENT for item in ledger.recorded)
        )

    def test_cli_command_outputs_json(self) -> None:
        original_reporter = main_module.ReplayDatasetPreparationReport
        original_argv = sys.argv
        sys.argv = ["main.py", "--optimise-or-precompute-replay-dataset", "--json"]

        class _Reporter:
            def build_report(self):
                return {
                    "title": "Replay Dataset Preparation",
                    "paper_trades_created": "no",
                    "live_changed": "no",
                }

        main_module.ReplayDatasetPreparationReport = _Reporter
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.ReplayDatasetPreparationReport = original_reporter
            sys.argv = original_argv

        text = stdout.getvalue()
        self.assertIn('"title": "Replay Dataset Preparation"', text)
        self.assertIn('"paper_trades_created": "no"', text)
