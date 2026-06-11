from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.framework.reporting.proposal_suppression_funnel import (
    ProposalSuppressionFunnelReport,
)


class _Ledger:
    backend = "sqlite"

    def __init__(
        self,
        *,
        tick_runs: list[dict[str, object]],
        decisions_by_cycle: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._tick_runs = tick_runs
        self._decisions_by_cycle = decisions_by_cycle or {}

    def list_recent_tick_runs(self, *, limit: int = 400) -> list[dict[str, object]]:
        _ = limit
        return list(self._tick_runs)

    def list_research_cycle_decisions(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        _ = limit
        return list(self._decisions_by_cycle.get(str(cycle_id or ""), []))


class ProposalSuppressionFunnelReportTests(unittest.TestCase):
    def test_selects_newest_real_heartbeat_cycle_and_ignores_replay_rows(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.01,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=0.25,
        )
        tick_runs = [
            {
                "tick_id": "researchcycle-old",
                "started_at": datetime(2026, 6, 8, 19, 38, 21).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-old",
                        "parent_tick_id": "heartbeat-old",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 1,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 1,
                    },
                },
            },
            {
                "tick_id": "replayrun-newer",
                "started_at": datetime(2026, 6, 8, 20, 5, 47).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "historical_replay",
                        "source": "manual_cli",
                    },
                },
            },
            {
                "tick_id": "heartbeat-newest",
                "started_at": datetime(2026, 6, 8, 20, 5, 29).astimezone(),
                "state_snapshot_json": {
                    "heartbeat": {"tick_id": "heartbeat-newest"},
                    "strategy_signals": {"allocation": {"signals_in": 0, "signals_out": 0, "suppressed": 0}},
                    "shadow_trade_proposals": {"proposals_created": 0},
                    "tick_blockers": {"primary_stage": "no_raw_signals", "rejected_trades": 0},
                },
            },
            {
                "tick_id": "researchcycle-new",
                "started_at": datetime(2026, 6, 8, 20, 2, 43).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "forced_one_shot",
                        "research_cycle_id": "researchcycle-new",
                        "parent_tick_id": "20260608-200529",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 1,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-old": [
                {
                    "cycle_id": "researchcycle-old",
                    "strategy_id": "old",
                    "profile_id": "p",
                    "timeframe": "1Hour",
                    "signals_generated": 10,
                    "proposals_created": 10,
                    "windows_tested_count": 1,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["insufficient_replay_windows"],
                    "net_return_summary_json": {"avg_pct": 0.0},
                    "win_rate_summary_json": {"avg": 0.0},
                    "raw_json": {},
                }
            ],
            "researchcycle-new": [
                {
                    "cycle_id": "researchcycle-new",
                    "strategy_id": "new",
                    "profile_id": "p",
                    "timeframe": "1Hour",
                    "signals_generated": 12,
                    "proposals_created": 12,
                    "windows_tested_count": 2,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["insufficient_sample_size"],
                    "net_return_summary_json": {"avg_pct": 0.02},
                    "win_rate_summary_json": {"avg": 0.6},
                    "raw_json": {},
                }
            ],
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()
        rendered = report.render(report=built)

        self.assertEqual(built["heartbeat"]["tick_id"], "heartbeat-newest")
        self.assertEqual(built["research_cycle"]["cycle_id"], "researchcycle-new")
        self.assertEqual(built["research_cycle"]["parent_tick_id"], "20260608-200529")
        self.assertIn("tick_id=heartbeat-newest", rendered)
        self.assertIn("cycle_id=researchcycle-new | parent_tick_id=20260608-200529", rendered)
        self.assertNotIn("tick_id=replayrun-newer", rendered)
        self.assertNotIn("cycle_id=researchcycle-old", rendered)

    def test_render_shows_heartbeat_and_research_gate_details(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.01,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=0.25,
        )
        tick_runs = [
            {
                "tick_id": "heartbeat-200",
                "started_at": datetime(2026, 6, 8, 9, 0).astimezone(),
                "state_snapshot_json": {
                    "heartbeat": {"tick_id": "heartbeat-200"},
                    "strategy_signals": {
                        "allocation": {
                            "signals_in": 3,
                            "signals_out": 0,
                            "suppressed": 3,
                            "suppressed_signals": [
                                {
                                    "strategy_id": "mean_reversion.snapback",
                                    "symbol": "AAPL",
                                    "holding_window_code": "1h",
                                    "signal_score": 92.0,
                                    "fitness_composite_score": -0.20,
                                    "suppress_threshold_used": 0.25,
                                    "allocation_note": "Suppressed by shadow fitness: composite -0.200 vs threshold 0.250 over 8 checkpoints.",
                                }
                            ],
                        }
                    },
                    "shadow_trade_proposals": {
                        "proposals_created": 0,
                        "proposals": [],
                    },
                    "tick_blockers": {
                        "primary_stage": "all_signals_suppressed",
                        "rejected_trades": 0,
                    },
                },
            },
            {
                "tick_id": "researchcycle-200",
                "started_at": datetime(2026, 6, 8, 9, 1).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-200",
                        "parent_tick_id": "heartbeat-200",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 2,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 2,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-200": [
                {
                    "cycle_id": "researchcycle-200",
                    "strategy_id": "mean_reversion.snapback",
                    "profile_id": "eq-core",
                    "timeframe": "1Hour",
                    "signals_generated": 40,
                    "proposals_created": 40,
                    "windows_tested_count": 3,
                    "recommendation": "research_only",
                    "blocker_reasons_json": [
                        "insufficient_replay_windows",
                        "insufficient_sample_size",
                    ],
                    "paper_blocker_reasons_json": [
                        "insufficient_replay_windows",
                        "insufficient_sample_size",
                    ],
                    "live_blocker_reasons_json": [
                        "insufficient_replay_windows",
                        "insufficient_sample_size",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": 0.012},
                    "win_rate_summary_json": {"avg": 0.57},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-200",
                    "strategy_id": "crypto_momentum.trend",
                    "profile_id": "crypto-core",
                    "timeframe": "15Min",
                    "signals_generated": 58,
                    "proposals_created": 58,
                    "windows_tested_count": 4,
                    "recommendation": "rejected_research",
                    "blocker_reasons_json": ["net_return_below_threshold"],
                    "paper_blocker_reasons_json": ["net_return_below_threshold"],
                    "live_blocker_reasons_json": [
                        "net_return_below_threshold",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": 0.004},
                    "win_rate_summary_json": {"avg": 0.52},
                    "raw_json": {},
                },
            ]
        }

        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        rendered = report.render()

        self.assertIn("Latest Real Heartbeat", rendered)
        self.assertIn("raw_signals=3 | survived=0 | suppressed=3 | raw_proposals=0 | created_proposals=0", rendered)
        self.assertIn("heartbeat_candidate=mean_reversion.snapback/- | timeframe=1h | symbol=AAPL", rendered)
        self.assertIn("heartbeat_live_path_verdict=thresholds_too_strict", rendered)
        self.assertIn("Latest Real Research Cycle", rendered)
        self.assertIn("cycle_id=researchcycle-200 | parent_tick_id=heartbeat-200", rendered)
        self.assertIn("research_candidate=mean_reversion.snapback/eq-core | timeframe=1Hour", rendered)
        self.assertIn("replay_windows 3/4, sample_size 40/50", rendered)
        self.assertIn("research_candidate=crypto_momentum.trend/crypto-core | timeframe=15Min", rendered)
        self.assertIn("research_replay_path_verdict=mixed", rendered)
        self.assertIn("paper_promotion_path_verdict=mixed", rendered)
        self.assertIn("live_promotion_path_verdict=allocation_policy_block", rendered)
        self.assertIn("promotion_path_verdict=mixed", rendered)
        self.assertIn("single_biggest_bottleneck=", rendered)
        self.assertIn("verdict=", rendered)

    def test_build_report_classifies_allocation_policy_and_future_window_verdicts(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.01,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=0.25,
        )
        tick_runs = [
            {
                "tick_id": "heartbeat-300",
                "started_at": datetime(2026, 6, 8, 10, 0).astimezone(),
                "state_snapshot_json": {
                    "heartbeat": {"tick_id": "heartbeat-300"},
                    "strategy_signals": {"allocation": {"signals_in": 0, "signals_out": 0, "suppressed": 0}},
                    "shadow_trade_proposals": {"proposals_created": 0},
                    "tick_blockers": {"primary_stage": "no_raw_signals", "rejected_trades": 0},
                },
            },
            {
                "tick_id": "researchcycle-300",
                "started_at": datetime(2026, 6, 8, 10, 1).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-300",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 2,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 1,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-300": [
                {
                    "cycle_id": "researchcycle-300",
                    "strategy_id": "s1",
                    "profile_id": "p1",
                    "timeframe": "1Hour",
                    "signals_generated": 60,
                    "proposals_created": 60,
                    "windows_tested_count": 4,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["paper_allocation_excludes_backtest_evidence"],
                    "paper_blocker_reasons_json": ["paper_allocation_excludes_backtest_evidence"],
                    "live_blocker_reasons_json": ["live_allocation_excludes_backtest_evidence"],
                    "net_return_summary_json": {"avg_pct": 0.02},
                    "win_rate_summary_json": {"avg": 0.60},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-300",
                    "strategy_id": "s2",
                    "profile_id": "p2",
                    "timeframe": "15Min",
                    "signals_generated": 60,
                    "proposals_created": 60,
                    "windows_tested_count": 4,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["timeframe:15Min/not_enough_elapsed_future_window"],
                    "net_return_summary_json": {"avg_pct": 0.02},
                    "win_rate_summary_json": {"avg": 0.60},
                    "raw_json": {},
                },
            ]
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["status"], "ok")
        self.assertEqual(built["biggest_bottleneck_category"], "allocation_policy_block")
        self.assertEqual(built["verdict"], "waiting_for_future_windows")
        self.assertEqual(built["research_replay_path_verdict"], "mixed")
        self.assertEqual(built["paper_promotion_path_verdict"], "waiting_for_future_windows")
        self.assertEqual(built["live_promotion_path_verdict"], "allocation_policy_block")
        self.assertEqual(built["promotion_path_verdict"], "waiting_for_future_windows")
        categories = [
            item["blocker_categories"]
            for item in built["research_cycle"]["suppressed_candidates"]
        ]
        self.assertIn(["allocation_policy_block"], categories)
        self.assertIn(["waiting_for_future_windows"], categories)

    def test_build_report_distinguishes_missing_samples_vs_underperformance(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=-7.1,
        )
        tick_runs = [
            {
                "tick_id": "heartbeat-400",
                "started_at": datetime(2026, 6, 8, 11, 0).astimezone(),
                "state_snapshot_json": {
                    "heartbeat": {"tick_id": "heartbeat-400"},
                    "strategy_signals": {
                        "allocation": {
                            "signals_in": 2,
                            "signals_out": 0,
                            "suppressed": 2,
                            "suppressed_signals": [
                                {
                                    "strategy_id": "momentum.balanced",
                                    "symbol": "TSLA",
                                    "holding_window_code": "1h",
                                    "signal_score": 90.0,
                                    "fitness_composite_score": -12.65943,
                                    "suppress_threshold_used": -7.1,
                                    "allocation_note": "Suppressed by shadow fitness: composite -12.659 vs threshold -7.100 over 151 checkpoints.",
                                }
                            ],
                        }
                    },
                    "shadow_trade_proposals": {"proposals_created": 0, "proposals": []},
                    "tick_blockers": {"primary_stage": "all_signals_suppressed", "rejected_trades": 0},
                },
            },
            {
                "tick_id": "researchcycle-400",
                "started_at": datetime(2026, 6, 8, 11, 1).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-400",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 3,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 2,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-400": [
                {
                    "cycle_id": "researchcycle-400",
                    "strategy_id": "waiting",
                    "profile_id": "p1",
                    "timeframe": "15Min",
                    "signals_generated": 98,
                    "proposals_created": 0,
                    "windows_tested_count": 1,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["timeframe:15Min/not_enough_elapsed_future_window"],
                    "paper_blocker_reasons_json": ["timeframe:15Min/not_enough_elapsed_future_window"],
                    "live_blocker_reasons_json": [
                        "timeframe:15Min/not_enough_elapsed_future_window",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": 0.0},
                    "win_rate_summary_json": {"avg": 0.0},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-400",
                    "strategy_id": "sampleless",
                    "profile_id": "p2",
                    "timeframe": "1Hour",
                    "signals_generated": 98,
                    "proposals_created": 0,
                    "windows_tested_count": 4,
                    "recommendation": "research_only",
                    "blocker_reasons_json": ["insufficient_sample_size"],
                    "paper_blocker_reasons_json": ["insufficient_sample_size"],
                    "live_blocker_reasons_json": [
                        "insufficient_sample_size",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": 0.0},
                    "win_rate_summary_json": {"avg": 0.0},
                    "raw_json": {},
                },
                {
                    "cycle_id": "researchcycle-400",
                    "strategy_id": "badperf",
                    "profile_id": "p3",
                    "timeframe": "1Hour",
                    "signals_generated": 98,
                    "proposals_created": 86,
                    "windows_tested_count": 4,
                    "recommendation": "rejected_research",
                    "blocker_reasons_json": ["net_return_below_threshold", "win_rate_below_threshold"],
                    "paper_blocker_reasons_json": ["net_return_below_threshold", "win_rate_below_threshold"],
                    "live_blocker_reasons_json": [
                        "net_return_below_threshold",
                        "win_rate_below_threshold",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": -1.000418},
                    "win_rate_summary_json": {"avg": 0.227908},
                    "raw_json": {},
                },
            ]
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["heartbeat_live_path_verdict"], "strategies_underperforming")
        self.assertEqual(built["research_replay_path_verdict"], "mixed")
        self.assertEqual(built["paper_promotion_path_verdict"], "mixed")
        self.assertEqual(built["live_promotion_path_verdict"], "allocation_policy_block")
        self.assertEqual(built["promotion_path_verdict"], "mixed")
        blocker_counts = built["research_cycle"]["blocker_type_counts"]
        self.assertEqual(blocker_counts["waiting_for_future_windows"], 1)
        self.assertEqual(blocker_counts["missing_outcome_samples"], 2)
        self.assertEqual(blocker_counts["strategies_underperforming"], 1)

    def test_reporting_separates_paper_and_live_blockers(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=-7.1,
        )
        tick_runs = [
            {
                "tick_id": "researchcycle-500",
                "started_at": datetime(2026, 6, 8, 12, 1).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-500",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 1,
                        "paper_candidates_created": 1,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-500": [
                {
                    "cycle_id": "researchcycle-500",
                    "strategy_id": "s1",
                    "profile_id": "p1",
                    "timeframe": "1Hour",
                    "signals_generated": 60,
                    "proposals_created": 60,
                    "windows_tested_count": 4,
                    "recommendation": "paper_sim_candidate",
                    "blocker_reasons_json": [],
                    "paper_blocker_reasons_json": [],
                    "live_blocker_reasons_json": ["live_allocation_excludes_backtest_evidence"],
                    "net_return_summary_json": {"avg_pct": 0.20},
                    "win_rate_summary_json": {"avg": 0.70},
                    "raw_json": {},
                }
            ]
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["paper_promotion_path_verdict"], "mixed")
        self.assertEqual(built["live_promotion_path_verdict"], "allocation_policy_block")
        self.assertEqual(built["promotion_path"]["paper_blocker_type_counts"], {})
        self.assertEqual(
            built["promotion_path"]["live_blocker_type_counts"]["allocation_policy_block"],
            1,
        )

    def test_paper_allocation_exclusion_is_policy_note_not_paper_blocker(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=-7.1,
        )
        tick_runs = [
            {
                "tick_id": "researchcycle-600",
                "started_at": datetime(2026, 6, 8, 12, 2).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-600",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 1,
                        "paper_candidates_created": 1,
                        "replay_windows_rejected_count": 0,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-600": [
                {
                    "cycle_id": "researchcycle-600",
                    "strategy_id": "s1",
                    "profile_id": "p1",
                    "timeframe": "1Hour",
                    "signals_generated": 60,
                    "proposals_created": 60,
                    "windows_tested_count": 4,
                    "recommendation": "paper_candidate",
                    "blocker_reasons_json": ["paper_allocation_excludes_backtest_evidence"],
                    "live_blocker_reasons_json": ["live_allocation_excludes_backtest_evidence"],
                    "net_return_summary_json": {"avg_pct": 0.20},
                    "win_rate_summary_json": {"avg": 0.70},
                    "raw_json": {},
                }
            ]
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()

        self.assertEqual(built["paper_promotion_path_verdict"], "mixed")
        self.assertEqual(built["live_promotion_path_verdict"], "allocation_policy_block")
        self.assertEqual(built["promotion_path"]["paper_blocker_type_counts"], {})

    def test_old_format_fallback_strips_live_only_blocker_from_paper_path(self) -> None:
        config = SimpleNamespace(
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            strategy_allocation_suppress_threshold=-7.1,
        )
        tick_runs = [
            {
                "tick_id": "researchcycle-700",
                "started_at": datetime(2026, 6, 8, 12, 3).astimezone(),
                "state_snapshot_json": {
                    "run": {
                        "pipeline": "research_cycle",
                        "source": "real_heartbeat",
                        "cycle_origin": "launchd_scheduled",
                        "research_cycle_id": "researchcycle-700",
                    },
                    "research_cycle": {
                        "usable_decisions_count": 1,
                        "paper_candidates_created": 0,
                        "replay_windows_rejected_count": 1,
                    },
                },
            },
        ]
        decisions = {
            "researchcycle-700": [
                {
                    "cycle_id": "researchcycle-700",
                    "strategy_id": "s1",
                    "profile_id": "p1",
                    "timeframe": "15Min",
                    "signals_generated": 10,
                    "proposals_created": 2,
                    "windows_tested_count": 1,
                    "recommendation": "research_only",
                    "blocker_reasons_json": [
                        "insufficient_replay_windows",
                        "insufficient_sample_size",
                        "live_allocation_excludes_backtest_evidence",
                    ],
                    "net_return_summary_json": {"avg_pct": 0.20},
                    "win_rate_summary_json": {"avg": 0.70},
                    "raw_json": {},
                }
            ]
        }
        report = ProposalSuppressionFunnelReport(
            config=config,
            usage_ledger=_Ledger(tick_runs=tick_runs, decisions_by_cycle=decisions),
        )

        built = report.build_report()
        candidate = built["research_cycle"]["promotion_candidates"][0]

        self.assertEqual(
            candidate["paper_blocker_reasons"],
            ["insufficient_replay_windows", "insufficient_sample_size"],
        )
        self.assertEqual(
            candidate["live_blocker_reasons"],
            [
                "insufficient_replay_windows",
                "insufficient_sample_size",
                "live_allocation_excludes_backtest_evidence",
            ],
        )
        self.assertNotIn(
            "allocation_policy_block",
            built["promotion_path"]["paper_blocker_type_counts"],
        )
        self.assertEqual(
            built["paper_promotion_path_verdict"],
            "missing_outcome_samples",
        )
        self.assertEqual(
            built["live_promotion_path_verdict"],
            "allocation_policy_block",
        )


if __name__ == "__main__":
    unittest.main()
