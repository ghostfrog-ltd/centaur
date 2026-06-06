from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from app.framework.reporting.replay_summary import ReplayComparisonReport, ReplaySummaryReport


class _ReplaySummaryLedger:
    def __init__(self) -> None:
        self.backend = "test"
        tz = ZoneInfo("UTC")
        self.tick_run = {
            "state_snapshot_json": {
                "historical_replay_training": {
                    "replay_timestamps_processed": 12,
                    "candidates_evaluated": 40,
                    "signals_generated": 8,
                    "paper_research_signals_generated": 5,
                    "outcomes_recorded": 8,
                    "outcome_checkpoints_skipped_not_enough_future_data": 1,
                    "replay_started_at": datetime(2026, 6, 6, 12, 0, tzinfo=tz).isoformat(),
                    "replay_config_hash": "abc123",
                    "dry_run": False,
                    "top_blockers_by_strategy": [],
                },
                "run": {},
            }
        }
        self.proposals = [
            {
                "proposal_id": "p1",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "AVAX/USD",
                "note": "historical_replay:run-1:proposal",
                "discovery_score": 2.8,
                "raw_json": {
                    "movement_pct": -0.22,
                    "discovery_score": 2.8,
                    "trade_count": 3,
                    "volume_gbp": 60000.0,
                },
            },
            {
                "proposal_id": "p2",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "SOL/USD",
                "note": "historical_replay:run-1:proposal",
                "discovery_score": 4.5,
                "raw_json": {
                    "movement_pct": -1.2,
                    "discovery_score": 4.5,
                    "trade_count": 1,
                    "volume_gbp": 0.0,
                },
            },
            {
                "proposal_id": "p3",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "BTC/USD",
                "note": "historical_replay:run-2:proposal",
                "discovery_score": 3.2,
                "raw_json": {
                    "movement_pct": -0.45,
                    "discovery_score": 3.2,
                    "trade_count": 2,
                    "volume_gbp": 75000.0,
                },
            },
            {
                "proposal_id": "p4",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "ETH/USD",
                "note": "historical_replay:run-2:proposal",
                "discovery_score": 4.1,
                "raw_json": {
                    "movement_pct": -1.4,
                    "discovery_score": 4.1,
                    "trade_count": 1,
                    "volume_gbp": 12000.0,
                },
            },
        ]
        self.outcomes = [
            {
                "proposal_id": "p1",
                "checkpoint_code": "15m",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "AVAX/USD",
                "realized_return_pct": -0.4,
                "max_favorable_excursion_pct": 0.1,
                "max_adverse_excursion_pct": -0.7,
                "note": "historical_replay:run-1:proposal",
            },
            {
                "proposal_id": "p1",
                "checkpoint_code": "1h",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "AVAX/USD",
                "realized_return_pct": -0.2,
                "max_favorable_excursion_pct": 0.3,
                "max_adverse_excursion_pct": -0.9,
                "note": "historical_replay:run-1:proposal",
            },
            {
                "proposal_id": "p2",
                "checkpoint_code": "15m",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "SOL/USD",
                "realized_return_pct": 0.1,
                "max_favorable_excursion_pct": 0.5,
                "max_adverse_excursion_pct": -0.2,
                "note": "historical_replay:run-1:proposal",
            },
            {
                "proposal_id": "p2",
                "checkpoint_code": "1h",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "SOL/USD",
                "realized_return_pct": -0.6,
                "max_favorable_excursion_pct": 0.2,
                "max_adverse_excursion_pct": -1.1,
                "note": "historical_replay:run-1:proposal",
            },
            {
                "proposal_id": "p3",
                "checkpoint_code": "15m",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "BTC/USD",
                "realized_return_pct": -0.3,
                "max_favorable_excursion_pct": 0.2,
                "max_adverse_excursion_pct": -0.4,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p3",
                "checkpoint_code": "1h",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "BTC/USD",
                "realized_return_pct": -0.1,
                "max_favorable_excursion_pct": 0.4,
                "max_adverse_excursion_pct": -0.5,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p3",
                "checkpoint_code": "1d",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "BTC/USD",
                "realized_return_pct": -0.25,
                "max_favorable_excursion_pct": 0.6,
                "max_adverse_excursion_pct": -0.8,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p3",
                "checkpoint_code": "7d",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "BTC/USD",
                "realized_return_pct": 0.2,
                "max_favorable_excursion_pct": 1.0,
                "max_adverse_excursion_pct": -1.2,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p4",
                "checkpoint_code": "15m",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "ETH/USD",
                "realized_return_pct": 0.15,
                "max_favorable_excursion_pct": 0.3,
                "max_adverse_excursion_pct": -0.1,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p4",
                "checkpoint_code": "1h",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "ETH/USD",
                "realized_return_pct": 0.05,
                "max_favorable_excursion_pct": 0.25,
                "max_adverse_excursion_pct": -0.2,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p4",
                "checkpoint_code": "1d",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "ETH/USD",
                "realized_return_pct": -0.1,
                "max_favorable_excursion_pct": 0.5,
                "max_adverse_excursion_pct": -0.4,
                "note": "historical_replay:run-2:proposal",
            },
            {
                "proposal_id": "p4",
                "checkpoint_code": "7d",
                "strategy_id": "crypto_pullback.downside_reversal_watch",
                "profile_id": "downside_reversal_watch",
                "symbol": "ETH/USD",
                "realized_return_pct": -0.2,
                "max_favorable_excursion_pct": 0.8,
                "max_adverse_excursion_pct": -0.6,
                "note": "historical_replay:run-2:proposal",
            },
        ]

    def get_tick_run(self, *, tick_id: str) -> dict[str, object] | None:
        if tick_id == "run-1":
            return self.tick_run
        if tick_id == "run-2":
            return {
                "state_snapshot_json": {
                    "historical_replay_training": {
                        "replay_timestamps_processed": 18,
                        "candidates_evaluated": 60,
                        "signals_generated": 10,
                        "paper_research_signals_generated": 6,
                        "outcomes_recorded": 8,
                        "outcome_checkpoints_skipped_not_enough_future_data": 0,
                        "replay_started_at": datetime(2026, 5, 31, 12, 0, tzinfo=ZoneInfo("UTC")).isoformat(),
                        "replay_config_hash": "def456",
                        "dry_run": False,
                        "top_blockers_by_strategy": [],
                    },
                    "run": {
                        "pipeline": "historical_replay",
                        "range_start": "2026-05-24T00:00:00+00:00",
                        "range_end": "2026-05-31T00:00:00+00:00",
                        "timeframe": "1Min",
                    },
                }
            }
        return None

    def list_shadow_trade_proposals_by_note_prefix(
        self,
        *,
        note_prefix: str,
    ) -> list[dict[str, object]]:
        return [row for row in self.proposals if str(row.get("note", "")).startswith(note_prefix)]

    def list_shadow_trade_outcomes_by_note_prefix(
        self,
        *,
        note_prefix: str,
    ) -> list[dict[str, object]]:
        return [row for row in self.outcomes if str(row.get("note", "")).startswith(note_prefix)]

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return [
            {
                "tick_id": "run-1",
                "started_at": datetime(2026, 6, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "historical_replay",
                        "range_start": "2026-06-01T00:00:00+00:00",
                        "range_end": "2026-06-06T00:00:00+00:00",
                        "timeframe": "1Min",
                    }
                },
            },
            {
                "tick_id": "run-2",
                "started_at": datetime(2026, 5, 31, 12, 0, tzinfo=ZoneInfo("UTC")),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "historical_replay",
                        "range_start": "2026-05-24T00:00:00+00:00",
                        "range_end": "2026-05-31T00:00:00+00:00",
                        "timeframe": "1Min",
                    }
                },
            },
        ][:limit]


class ReplaySummaryReportTests(unittest.TestCase):
    def test_build_report_adds_pullback_deep_dive(self) -> None:
        report = ReplaySummaryReport(usage_ledger=_ReplaySummaryLedger()).build_report(
            replay_run_id="run-1"
        )

        analysis = report["strategy_analyses"]["crypto_pullback.downside_reversal_watch"]
        continuation = report["strategy_analyses"]["crypto_pullback.downside_continuation_watch"]
        extreme_reversal = report["strategy_analyses"]["crypto_pullback.extreme_drop_reversal_watch"]
        regime_comparison = {
            row["strategy_id"]: row for row in report["regime_comparison"]
        }
        self.assertEqual(analysis["proposal_count"], 2)
        self.assertEqual(continuation["proposal_count"], 1)
        self.assertEqual(extreme_reversal["proposal_count"], 1)
        self.assertEqual(len(analysis["by_symbol"]), 2)
        self.assertEqual(analysis["by_symbol"][0]["symbol"], "AVAX/USD")
        movement_buckets = {row["bucket"] for row in analysis["by_movement_bucket"]}
        self.assertIn("-0.15% to -0.30%", movement_buckets)
        self.assertIn("worse than -1.00%", movement_buckets)
        discovery_buckets = {row["bucket"] for row in analysis["by_discovery_bucket"]}
        self.assertIn("2.5-3.0", discovery_buckets)
        self.assertIn("4.0+", discovery_buckets)
        trade_buckets = {row["bucket"] for row in analysis["trade_count_comparison"]}
        self.assertIn("trade_count>=2", trade_buckets)
        self.assertIn("trade_count<2", trade_buckets)
        volume_buckets = {row["bucket"] for row in analysis["volume_threshold_comparison"]}
        self.assertIn("volume_gbp>=50000", volume_buckets)
        self.assertIn("volume_gbp<50000_or_missing", volume_buckets)
        short_side = {row["checkpoint_code"]: row for row in analysis["short_side_interpretation"]}
        self.assertAlmostEqual(short_side["15m"]["inverse_win_rate"], 0.5, places=6)
        self.assertAlmostEqual(short_side["15m"]["avg_inverse_return_pct"], 0.15, places=6)
        self.assertTrue(short_side["15m"]["positive_average_return"])
        self.assertEqual(continuation["strategy_id"], "crypto_pullback.downside_continuation_watch")
        self.assertEqual(continuation["source_strategy_id"], "crypto_pullback.downside_reversal_watch")
        self.assertFalse(continuation["paper_execution_allowed"])
        self.assertTrue(continuation["paper_research_allowed"])
        self.assertFalse(continuation["live_execution_allowed"])
        self.assertTrue(continuation["research_only"])
        continuation_movement_buckets = {row["bucket"] for row in continuation["by_movement_bucket"]}
        self.assertEqual(continuation_movement_buckets, {"-0.15% to -0.30%"})
        continuation_buckets = {row["bucket"] for row in continuation["signal_score_comparison"]}
        self.assertIn("signal_score_unknown", continuation_buckets)
        top_symbol = continuation["top_symbols_by_inverse_return"][0]
        self.assertEqual(top_symbol["symbol"], "AVAX/USD")
        self.assertAlmostEqual(top_symbol["avg_inverse_return_pct"], 0.3, places=6)
        self.assertEqual(
            continuation["minimum_sample_warning"],
            "minimum sample warning: proposals=1 < 50",
        )
        self.assertEqual(extreme_reversal["strategy_id"], "crypto_pullback.extreme_drop_reversal_watch")
        extreme_movement_buckets = {row["bucket"] for row in extreme_reversal["by_movement_bucket"]}
        self.assertEqual(extreme_movement_buckets, {"worse than -1.00%"})
        extreme_short_side = {row["checkpoint_code"]: row for row in extreme_reversal["short_side_interpretation"]}
        self.assertAlmostEqual(extreme_short_side["15m"]["avg_inverse_return_pct"], -0.1, places=6)
        moderate_regime = regime_comparison["crypto_pullback.downside_continuation_watch"]
        self.assertEqual(moderate_regime["interpretation"], "inverse_continuation_only")
        self.assertEqual(moderate_regime["movement_label"], "-0.15% to -1.00%")
        self.assertEqual(moderate_regime["minimum_sample_warning"], "minimum sample warning: proposals=1 < 50")
        self.assertEqual(moderate_regime["checkpoint_recommendation"]["checkpoint_code"], "15m")
        self.assertAlmostEqual(moderate_regime["checkpoint_recommendation"]["avg_return_pct"], 0.4, places=6)
        self.assertAlmostEqual(moderate_regime["checkpoint_recommendation"]["win_rate"], 1.0, places=6)
        self.assertEqual(moderate_regime["best_symbols"][0]["symbol"], "AVAX/USD")
        extreme_regime = regime_comparison["crypto_pullback.extreme_drop_reversal_watch"]
        self.assertEqual(extreme_regime["interpretation"], "long_reversal_only")
        self.assertEqual(extreme_regime["movement_label"], "worse than -1.00%")
        self.assertEqual(extreme_regime["minimum_sample_warning"], "minimum sample warning: proposals=1 < 50")
        self.assertEqual(extreme_regime["checkpoint_recommendation"]["checkpoint_code"], "15m")
        self.assertAlmostEqual(extreme_regime["checkpoint_recommendation"]["avg_return_pct"], 0.1, places=6)
        self.assertAlmostEqual(extreme_regime["checkpoint_recommendation"]["win_rate"], 1.0, places=6)
        self.assertEqual(extreme_regime["best_symbols"][0]["symbol"], "SOL/USD")

    def test_render_includes_deep_dive_sections(self) -> None:
        rendered = ReplaySummaryReport(usage_ledger=_ReplaySummaryLedger()).render(
            replay_run_id="run-1"
        )

        self.assertIn("Replay Regime Comparison", rendered)
        self.assertIn("interpretation=inverse_continuation_only", rendered)
        self.assertIn("interpretation=long_reversal_only", rendered)
        self.assertIn("sample_warning=minimum sample warning: proposals=1 < 50", rendered)
        self.assertIn("checkpoint_recommendation=15m", rendered)
        self.assertIn("research_only=yes | paper_execution_allowed=no | live_execution_allowed=no", rendered)
        self.assertIn("Strategy Deep Dive: crypto_pullback.downside_reversal_watch", rendered)
        self.assertIn("Strategy Deep Dive: crypto_pullback.downside_continuation_watch", rendered)
        self.assertIn("Strategy Deep Dive: crypto_pullback.extreme_drop_reversal_watch", rendered)
        self.assertIn("By Symbol", rendered)
        self.assertIn("By Movement Bucket", rendered)
        self.assertIn("Trade Count Comparison", rendered)
        self.assertIn("Short-Side Continuation Interpretation", rendered)
        self.assertIn("Continuation Checkpoints", rendered)
        self.assertIn("Top Symbols By Inverse Return", rendered)

    def test_replay_comparison_report_compares_multiple_windows(self) -> None:
        report = ReplayComparisonReport(usage_ledger=_ReplaySummaryLedger()).build_report(
            replay_limit=4
        )
        rendered = ReplayComparisonReport(usage_ledger=_ReplaySummaryLedger()).render(
            replay_limit=4
        )

        self.assertEqual(report["simulation_assumptions"]["fee_bps"], 10.0)
        self.assertEqual(report["simulation_assumptions"]["slippage_bps"], 8.0)
        self.assertEqual(report["simulation_assumptions"]["spread_bps"], 12.0)
        continuation_sim = report["regimes"]["crypto_pullback.downside_continuation_watch"]["continuation_simulation"]
        sensitivity = report["regimes"]["crypto_pullback.downside_continuation_watch"]["cost_sensitivity"]
        run_2 = next(item for item in continuation_sim if item["replay_run_id"] == "run-2")
        run_2_15m = run_2["by_checkpoint"]["15m"]
        self.assertAlmostEqual(run_2_15m["gross_inverse_return_pct"], 0.3, places=6)
        self.assertAlmostEqual(run_2_15m["estimated_fee_pct"], 0.2, places=6)
        self.assertAlmostEqual(run_2_15m["estimated_spread_slippage_pct"], 0.28, places=6)
        self.assertAlmostEqual(run_2_15m["net_inverse_return_pct"], -0.18, places=6)
        self.assertAlmostEqual(run_2_15m["net_inverse_win_rate"], 0.0, places=6)
        self.assertAlmostEqual(run_2_15m["avg_adverse_excursion_pct"], -0.2, places=6)
        self.assertAlmostEqual(run_2_15m["avg_favourable_excursion_pct"], 0.4, places=6)
        self.assertAlmostEqual(run_2_15m["worst_adverse_excursion_pct"], -0.2, places=6)
        self.assertAlmostEqual(run_2_15m["best_favourable_excursion_pct"], 0.4, places=6)
        run_2_sensitivity = next(item for item in sensitivity["windows"] if item["replay_run_id"] == "run-2")
        self.assertEqual(run_2_sensitivity["best_checkpoint_by_net_return"], "15m")
        run_2_1d_sensitivity = run_2_sensitivity["by_checkpoint"]["1d"]
        self.assertAlmostEqual(run_2_1d_sensitivity["break_even_total_cost_bps"], 25.0, places=6)
        optimistic = next(item for item in run_2_1d_sensitivity["cost_scenarios"] if item["scenario"] == "optimistic")
        conservative = next(item for item in run_2_1d_sensitivity["cost_scenarios"] if item["scenario"] == "conservative")
        harsh = next(item for item in run_2_1d_sensitivity["cost_scenarios"] if item["scenario"] == "harsh")
        self.assertAlmostEqual(optimistic["net_inverse_return_pct"], 0.15, places=6)
        self.assertAlmostEqual(optimistic["net_inverse_win_rate"], 1.0, places=6)
        self.assertAlmostEqual(conservative["net_inverse_return_pct"], -0.23, places=6)
        self.assertAlmostEqual(harsh["net_inverse_return_pct"], -0.5, places=6)
        moderate_consistency = next(item for item in sensitivity["consistency_by_scenario"] if item["scenario"] == "moderate")
        self.assertTrue(moderate_consistency["survives_consistently"])
        self.assertIn("Replay Comparison Report", rendered)
        self.assertIn("Continuation Simulation Assumptions", rendered)
        self.assertIn("fee_bps=10.0 | slippage_bps=8.0 | spread_bps=12.0", rendered)
        self.assertIn("Continuation Simulation", rendered)
        self.assertIn("Continuation Cost Sensitivity", rendered)
        self.assertIn("scenario=optimistic | total_cost_bps=10.0", rendered)
        self.assertIn("best_checkpoint_by_net_return=15m", rendered)
        self.assertIn("break_even_total_cost_bps=25.0", rendered)
        self.assertIn("Regime: crypto_pullback.downside_continuation_watch", rendered)
        self.assertIn("Regime: crypto_pullback.extreme_drop_reversal_watch", rendered)
        self.assertIn("replay_run_id=run-1", rendered)
        self.assertIn("replay_run_id=run-2", rendered)
        self.assertIn("date_range=2026-06-01T00:00:00+00:00 to 2026-06-06T00:00:00+00:00", rendered)
        self.assertIn("date_range=2026-05-24T00:00:00+00:00 to 2026-05-31T00:00:00+00:00", rendered)
        self.assertIn("15m | win_rate=1.0 | avg_return_pct=0.4", rendered)
        self.assertIn("1d | win_rate=1.0 | avg_return_pct=0.25", rendered)
        self.assertIn("7d | win_rate=0.0 | avg_return_pct=-0.2", rendered)
        self.assertIn("checkpoint=15m | proposals=1 | gross_inverse_return_pct=0.3", rendered)
        self.assertIn("net_inverse_return_pct=-0.18", rendered)
        self.assertIn("sample_warning=minimum sample warning: proposals=1 < 50", rendered)
        self.assertIn("best_symbols=BTC/USD:outcomes=4,avg_return_pct=0.1125", rendered)
        self.assertIn("worst_symbols=ETH/USD:outcomes=4,avg_return_pct=-0.025", rendered)


if __name__ == "__main__":
    unittest.main()
