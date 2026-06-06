from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.framework.reporting.proposal_pipeline_diagnostics import (
    ProposalPipelineDiagnosticsReport,
)


class _FakeUsageLedger:
    def __init__(self, latest_tick: dict[str, object] | None) -> None:
        self._latest_tick = latest_tick
        self.backend = "sqlite"

    def get_latest_tick_run(self) -> dict[str, object] | None:
        return self._latest_tick

    def list_recent_shadow_proposal_keys(self, *, since: datetime) -> set[tuple[str, str, str]]:
        return set()


class ProposalPipelineDiagnosticsReportTests(unittest.TestCase):
    def test_build_report_handles_missing_tick(self) -> None:
        report = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger(None),
        ).build_report()

        self.assertEqual(report["status"], "no_tick")
        self.assertIn("No persisted control tick", report["reason"])

    def test_build_report_explains_strategy_never_firing(self) -> None:
        latest_tick = {
            "tick_id": "20260605-120000",
            "started_at": datetime.fromisoformat("2026-06-05T12:00:00+00:00"),
            "ended_at": datetime.fromisoformat("2026-06-05T12:00:05+00:00"),
            "state_snapshot_json": {
                "market_gate": {
                    "account_trade_ready": True,
                    "crypto_scan_ready": True,
                },
                "alpaca_account": {"summary": {"equity": 100.0}},
                "market_scan": {
                    "result": {
                        "source_freshness_status": {
                            "alpaca_equity_data": {"status": "fresh"},
                        },
                        "stale_sources_excluded": [],
                        "candidates_excluded_due_to_stale_source": 0,
                        "market_data_source_used_for_strategy": {"equity": "alpaca_equity_data"},
                        "account_data_source_used_for_positions": {
                            "alpaca": "alpaca_account_positions_api"
                        },
                    },
                    "ranked_candidates": [
                        {
                            "source": "alpaca_equity_data",
                            "symbol": "AAPL",
                            "asset_class": "equity",
                            "canonical_instrument_id": "AAPL-US-EQUITY",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "previous_close_price": 100.1,
                            "movement_pct": -0.10,
                            "discovery_score": 5.0,
                            "trade_count": 100,
                            "volume": 10000,
                        }
                    ],
                    "selected_candidates": [
                        {
                            "source": "alpaca_equity_data",
                            "symbol": "AAPL",
                            "asset_class": "equity",
                            "canonical_instrument_id": "AAPL-US-EQUITY",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "previous_close_price": 100.1,
                            "movement_pct": -0.10,
                            "discovery_score": 5.0,
                            "trade_count": 100,
                            "volume": 10000,
                        }
                    ],
                },
                "context_enrichment": {
                    "candidates": [
                        {
                            "source": "alpaca_equity_data",
                            "symbol": "AAPL",
                            "asset_class": "equity",
                            "canonical_instrument_id": "AAPL-US-EQUITY",
                            "close_price": 100.0,
                            "movement_pct": -0.10,
                            "discovery_score": 5.0,
                            "trade_count": 100,
                            "volume": 10000,
                        }
                    ]
                },
                "strategy_fitness": {"summaries": []},
                "strategy_signals": {
                    "threshold_adaptive": {
                        "effective_threshold": -6.5,
                    }
                },
            },
        }
        report = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).build_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["primary_issue"], "strategy never firing")
        self.assertEqual(report["asset_coverage"]["total_equity_candidates"], 1)
        self.assertEqual(report["asset_coverage"]["selected_equity_candidates"], 1)
        self.assertEqual(report["queue_diagnostics"]["current_pending_count"], 0)
        self.assertEqual(report["selected_for_strategy_eval_count"], 1)
        self.assertEqual(report["universe"]["selected_for_fast_strategy_evaluation"], 1)
        self.assertEqual(report["universe"]["newly_enriched_this_tick"], 1)
        self.assertEqual(report["universe"]["deferred_candidates_not_in_fast_batch"], 0)
        self.assertIn("latest_market_data_at", report["universe"])
        self.assertEqual(report["strategy_coverage"][0]["available_matching_candidates"], 1)
        self.assertEqual(report["strategy_coverage"][0]["selected_matching_candidates"], 1)
        self.assertGreaterEqual(len(report["strategies"]), 1)
        strategy = next(
            item for item in report["strategies"] if item["strategy_id"] == "mean_reversion.snapback"
        )
        self.assertEqual(strategy["strategy_id"], "mean_reversion.snapback")
        self.assertEqual(strategy["symbols_scanned"], 1)
        self.assertEqual(strategy["enough_data"], 1)
        self.assertEqual(strategy["raw_signals"], 0)
        self.assertEqual(
            strategy["rejections"]["strategy.movement_above_snapback_max"],
            1,
        )
        self.assertEqual(strategy["closest_misses"][0]["symbol"], "AAPL")
        rendered = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).render(report=report)
        self.assertIn("selected_for_strategy_eval=1", rendered)
        self.assertIn("selected_for_fast_strategy_evaluation=1", rendered)
        self.assertIn("newly_enriched_this_tick=1", rendered)
        self.assertIn("latest_market_data_at=", rendered)
        self.assertIn("source_freshness_status=", rendered)
        self.assertIn("market_data_source_used_for_strategy=", rendered)
        self.assertIn("Asset Coverage", rendered)
        self.assertIn("Strategy Coverage", rendered)
        self.assertIn("Slow Queue", rendered)

    def test_build_report_distinguishes_fast_selection_from_missing_enrichment_payload(self) -> None:
        latest_tick = {
            "tick_id": "20260605-120100",
            "started_at": datetime.fromisoformat("2026-06-05T12:01:00+00:00"),
            "ended_at": datetime.fromisoformat("2026-06-05T12:01:05+00:00"),
            "state_snapshot_json": {
                "market_gate": {"account_trade_ready": True, "crypto_scan_ready": True},
                "alpaca_account": {"summary": {"equity": 100.0}},
                "market_scan": {
                    "ranked_candidates": [
                        {
                            "source": "alpaca_equity_data",
                            "symbol": f"EQ{index}",
                            "asset_class": "equity",
                            "canonical_instrument_id": f"EQ{index}-US-EQUITY",
                            "rank": index,
                            "selected": index <= 6,
                            "close_price": 100.0,
                            "previous_close_price": 100.0,
                            "movement_pct": 0.0,
                            "discovery_score": 5.0,
                            "trade_count": 100,
                            "volume": 10000,
                        }
                        for index in range(1, 32)
                    ],
                    "selected_candidates": [
                        {
                            "source": "alpaca_equity_data",
                            "symbol": f"EQ{index}",
                            "asset_class": "equity",
                            "canonical_instrument_id": f"EQ{index}-US-EQUITY",
                            "rank": index,
                            "selected": True,
                            "close_price": 100.0,
                            "previous_close_price": 100.0,
                            "movement_pct": 0.0,
                            "discovery_score": 5.0,
                            "trade_count": 100,
                            "volume": 10000,
                        }
                        for index in range(1, 7)
                    ],
                },
                "strategy_fitness": {"summaries": []},
                "strategy_signals": {"threshold_adaptive": {"effective_threshold": -6.5}},
            },
        }
        config = self._config()
        config.paper_execution_allowed_strategies = ("crypto_momentum.trend",)
        report = ProposalPipelineDiagnosticsReport(
            config=config,
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).build_report()

        self.assertEqual(report["selected_for_strategy_eval_count"], 6)
        self.assertEqual(report["universe"]["selected_for_fast_strategy_evaluation"], 6)
        self.assertEqual(report["universe"]["newly_enriched_this_tick"], 0)
        self.assertEqual(report["universe"]["deferred_candidates_not_in_fast_batch"], 25)
        self.assertIn("did not persist slow-enrichment queue step output", report["universe"]["queue_state_note"])

    def test_build_report_keeps_account_only_discoveries_out_of_strategy_scan(self) -> None:
        latest_tick = {
            "tick_id": "20260605-120200",
            "started_at": datetime.fromisoformat("2026-06-05T12:02:00+00:00"),
            "ended_at": datetime.fromisoformat("2026-06-05T12:02:05+00:00"),
            "state_snapshot_json": {
                "market_gate": {"account_trade_ready": True, "crypto_scan_ready": True},
                "alpaca_account": {"summary": {"equity": 100.0}},
                "market_scan": {
                    "result": {
                        "source_freshness_status": {
                            "trading212_market_data": {"status": "account_only"},
                        },
                        "stale_sources_excluded": ["trading212_market_data"],
                        "candidates_excluded_due_to_stale_source": 3,
                        "candidates_excluded_due_to_account_only_source": 3,
                        "market_data_source_used_for_strategy": {},
                        "account_data_source_used_for_positions": {
                            "trading212_paper": "trading212_positions_api"
                        },
                    },
                    "discovered_candidates": [
                        {
                            "source": "trading212_market_data",
                            "symbol": symbol,
                            "asset_class": "equity",
                            "market_data_eligible": False,
                            "market_data_status": "account_only",
                            "market_data_rejection_reason": "market_data_source_account_only_positions_api",
                        }
                        for symbol in ("VOD", "ULVR", "TSCO")
                    ],
                    "ranked_candidates": [],
                    "selected_candidates": [],
                    "excluded_candidates": [
                        {
                            "source": "trading212_market_data",
                            "symbol": symbol,
                            "asset_class": "equity",
                            "market_data_eligible": False,
                            "market_data_status": "account_only",
                            "market_data_rejection_reason": "market_data_source_account_only_positions_api",
                        }
                        for symbol in ("VOD", "ULVR", "TSCO")
                    ],
                },
                "context_enrichment": {"candidates": []},
                "strategy_fitness": {"summaries": []},
                "strategy_signals": {
                    "threshold_adaptive": {"effective_threshold": -6.5},
                    "rejection_summary": {
                        "total_rejections": 1,
                        "by_strategy_reason": [
                            {
                                "strategy_id": "equity",
                                "reason": "strategy.skipped_no_fresh_market_data",
                                "count": 1,
                            }
                        ],
                        "samples": [],
                    },
                },
            },
        }
        config = self._config()
        config.paper_execution_allowed_strategies = ("crypto_momentum.trend",)
        report = ProposalPipelineDiagnosticsReport(
            config=config,
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).build_report()

        self.assertEqual(report["universe"]["discovered_candidates"], 3)
        self.assertEqual(report["universe"]["eligible_for_strategy_evaluation"], 0)
        self.assertEqual(report["universe"]["selected_for_fast_strategy_evaluation"], 0)
        self.assertEqual(report["universe"]["candidates_excluded_due_to_stale_source"], 3)
        self.assertEqual(report["universe"]["candidates_excluded_due_to_account_only_source"], 3)
        self.assertEqual(report["strategies"][0]["symbols_scanned"], 0)
        self.assertEqual(report["strategies"][0]["closest_misses"], [])
        self.assertEqual(report["strategy_coverage"][0]["available_matching_candidates"], 0)
        self.assertEqual(report["strategy_coverage"][0]["selected_matching_candidates"], 0)
        self.assertEqual(report["proposal_data_integrity"]["status"], "pass")
        self.assertEqual(report["proposal_data_integrity"]["failure_reasons"], [])
        self.assertEqual(report["proposal_data_integrity"]["stale_or_account_only_selected_count"], 0)
        self.assertEqual(
            report["proposal_data_integrity"]["stale_or_account_only_with_strategy_batch_index_count"],
            0,
        )
        self.assertEqual(
            report["proposal_data_integrity"]["stale_or_account_only_in_strategy_misses_count"],
            0,
        )
        self.assertEqual(
            report["proposal_data_integrity"]["stale_or_account_only_in_symbols_scanned_count"],
            0,
        )
        self.assertFalse(report["proposal_data_integrity"]["queue_health_affects_proposal_data_integrity"])
        first_candidate = report["candidate_details"][0]
        self.assertEqual(first_candidate["discovery_rank"], 0)
        self.assertEqual(first_candidate["eligible_rank"], "-")
        self.assertFalse(first_candidate["selected"])
        self.assertEqual(first_candidate["strategy_batch_index"], "-")
        self.assertEqual(first_candidate["queue_position"], "-")
        self.assertEqual(
            first_candidate["exclusion_reason"],
            "market_data_source_account_only_positions_api",
        )
        rendered = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).render(report=report)
        self.assertIn("stale_or_account_only_candidates=3", rendered)
        self.assertIn("eligible_for_strategy_evaluation=0", rendered)
        self.assertIn("candidates_excluded_due_to_account_only_source=3", rendered)
        self.assertIn("strategy_batch_index=-", rendered)
        self.assertIn("eligible_rank=-", rendered)
        self.assertIn("exclusion_reason=market_data_source_account_only_positions_api", rendered)
        self.assertIn("proposal_data_integrity_failure_reasons=none", rendered)
        self.assertIn("queue_health_affects_proposal_data_integrity=no", rendered)

    def test_proposal_data_integrity_fails_when_excluded_candidate_has_strategy_batch_slot(self) -> None:
        report = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger({"state_snapshot_json": {"market_scan": {}}}),
        )

        integrity = report._proposal_data_integrity(
            snapshot={"market_scan": {"selected_candidates": []}},
            candidate_details=[
                {
                    "source": "trading212_market_data",
                    "symbol": "VOD",
                    "selected": False,
                    "eligible_for_strategy_evaluation": "no",
                    "strategy_batch_index": 4,
                }
            ],
            strategies=[],
            queue_diagnostics={"queue_health": "pass"},
        )

        self.assertEqual(integrity["status"], "fail")
        self.assertEqual(
            integrity["failure_reasons"],
            ["stale_or_account_only_with_strategy_batch_index"],
        )
        self.assertEqual(integrity["violations"], ["trading212_market_data:VOD"])

    def test_proposal_data_integrity_ignores_raw_selected_leak_when_strategy_boundary_is_clean(self) -> None:
        report = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger({"state_snapshot_json": {"market_scan": {}}}),
        )

        integrity = report._proposal_data_integrity(
            snapshot={
                "market_scan": {
                    "selected_candidates": [
                        {
                            "source": "trading212_market_data",
                            "symbol": "VOD",
                            "market_data_eligible": False,
                            "market_data_status": "account_only",
                        }
                    ]
                }
            },
            candidate_details=[
                {
                    "source": "trading212_market_data",
                    "symbol": "VOD",
                    "selected": False,
                    "eligible_for_strategy_evaluation": "no",
                    "strategy_batch_index": "-",
                }
            ],
            strategies=[],
            queue_diagnostics={"queue_health": "warn"},
        )

        self.assertEqual(integrity["status"], "pass")
        self.assertEqual(integrity["failure_reasons"], [])
        self.assertEqual(integrity["stale_or_account_only_selected_count"], 0)
        self.assertFalse(integrity["queue_health_affects_proposal_data_integrity"])

    def test_proposal_data_integrity_fails_when_excluded_candidate_has_eligible_rank(self) -> None:
        report = ProposalPipelineDiagnosticsReport(
            config=self._config(),
            usage_ledger=_FakeUsageLedger({"state_snapshot_json": {"market_scan": {}}}),
        )

        integrity = report._proposal_data_integrity(
            snapshot={"market_scan": {"selected_candidates": []}},
            candidate_details=[
                {
                    "source": "trading212_market_data",
                    "symbol": "VOD",
                    "selected": False,
                    "eligible_for_strategy_evaluation": "no",
                    "eligible_rank": 2,
                    "strategy_batch_index": "-",
                }
            ],
            strategies=[],
            queue_diagnostics={"queue_health": "pass"},
        )

        self.assertEqual(integrity["status"], "fail")
        self.assertEqual(
            integrity["failure_reasons"],
            ["stale_or_account_only_with_eligible_rank"],
        )
        self.assertEqual(integrity["violations"], ["trading212_market_data:VOD"])

    def test_build_report_adds_crypto_momentum_gate_details(self) -> None:
        latest_tick = {
            "tick_id": "20260605-120300",
            "started_at": datetime.fromisoformat("2026-06-05T12:03:00+00:00"),
            "ended_at": datetime.fromisoformat("2026-06-05T12:03:05+00:00"),
            "state_snapshot_json": {
                "market_gate": {"account_trade_ready": True, "crypto_scan_ready": True},
                "alpaca_account": {"summary": {"equity": 100.0}},
                "market_scan": {
                    "ranked_candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "close_price_gbp": 80.0,
                            "movement_pct": 0.150167,
                            "discovery_score": 2.066,
                            "trade_count": 10,
                            "volume": 100,
                        }
                    ],
                    "selected_candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "close_price_gbp": 80.0,
                            "movement_pct": 0.150167,
                            "discovery_score": 2.066,
                            "trade_count": 10,
                            "volume": 100,
                        }
                    ],
                },
                "context_enrichment": {
                    "candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "close_price": 100.0,
                            "close_price_gbp": 80.0,
                            "movement_pct": 0.150167,
                            "discovery_score": 2.066,
                            "trade_count": 10,
                            "volume": 100,
                        }
                    ]
                },
                "strategy_fitness": {"summaries": []},
                "strategy_signals": {"threshold_adaptive": {"effective_threshold": -6.5}},
            },
        }
        config = self._config()
        config.paper_execution_allowed_strategies = ("crypto_momentum.trend",)
        report = ProposalPipelineDiagnosticsReport(
            config=config,
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).build_report()

        crypto_strategy = next(
            item for item in report["strategies"] if item["strategy_id"] == "crypto_momentum.trend"
        )
        detail = crypto_strategy["crypto_gate_details"][0]
        self.assertEqual(detail["symbol"], "AVAX/USD")
        self.assertEqual(detail["final_blocker"], "discovery_below_min")
        self.assertEqual(detail["first_failed_gate"], "discovery_min")
        checks = {item["name"]: item for item in detail["checks"]}
        self.assertTrue(checks["movement_min"]["passed"])
        self.assertFalse(checks["discovery_min"]["passed"])

    def test_build_report_adds_crypto_pullback_gate_details_and_never_live_approves(self) -> None:
        latest_tick = {
            "tick_id": "20260605-120400",
            "started_at": datetime.fromisoformat("2026-06-05T12:04:00+00:00"),
            "ended_at": datetime.fromisoformat("2026-06-05T12:04:05+00:00"),
            "state_snapshot_json": {
                "market_gate": {"account_trade_ready": True, "crypto_scan_ready": True},
                "alpaca_account": {"summary": {"equity": 100.0}},
                "market_scan": {
                    "result": {
                        "source_freshness_status": {
                            "alpaca_crypto_data": {"status": "fresh"},
                        },
                        "stale_sources_excluded": [],
                        "candidates_excluded_due_to_stale_source": 0,
                        "market_data_source_used_for_strategy": {"crypto": "alpaca_crypto_data"},
                    },
                    "ranked_candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "close_price_gbp": 79.0,
                            "movement_pct": -0.417,
                            "discovery_score": 2.8,
                            "trade_count": 3,
                            "volume": 100,
                            "spread_pct": 0.12,
                        }
                    ],
                    "selected_candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "rank": 1,
                            "selected": True,
                            "close_price": 100.0,
                            "close_price_gbp": 79.0,
                            "movement_pct": -0.417,
                            "discovery_score": 2.8,
                            "trade_count": 3,
                            "volume": 100,
                            "spread_pct": 0.12,
                        }
                    ],
                },
                "context_enrichment": {
                    "candidates": [
                        {
                            "source": "alpaca_crypto_data",
                            "symbol": "AVAX/USD",
                            "asset_class": "crypto",
                            "canonical_instrument_id": "AVAX-USD-SPOT",
                            "close_price": 100.0,
                            "close_price_gbp": 79.0,
                            "movement_pct": -0.417,
                            "discovery_score": 2.8,
                            "trade_count": 3,
                            "volume": 100,
                            "spread_pct": 0.12,
                        }
                    ]
                },
                "strategy_fitness": {"summaries": []},
                "strategy_signals": {"threshold_adaptive": {"effective_threshold": -6.5}},
            },
        }
        config = self._config()
        config.paper_execution_allowed_strategies = ("crypto_momentum.trend",)
        config.live_execution_allowed_strategies = ("crypto_momentum.trend",)
        report = ProposalPipelineDiagnosticsReport(
            config=config,
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).build_report()

        pullback_strategy = next(
            item
            for item in report["strategies"]
            if item["strategy_id"] == "crypto_pullback.downside_reversal_watch"
        )
        pullback_coverage = next(
            item
            for item in report["strategy_coverage"]
            if item["strategy_id"] == "crypto_pullback.downside_reversal_watch"
        )
        self.assertEqual(pullback_coverage["selected_matching_candidates"], 1)
        self.assertEqual(pullback_strategy["symbols_scanned"], 1)
        self.assertEqual(pullback_strategy["raw_signals"], 1)
        self.assertEqual(pullback_strategy["paper_approved"], 0)
        self.assertEqual(pullback_strategy["live_approved"], 0)
        self.assertFalse(pullback_strategy["paper_execution_allowed"])
        self.assertTrue(pullback_strategy["paper_research_allowed"])
        self.assertFalse(pullback_strategy["live_execution_allowed"])
        self.assertTrue(pullback_strategy["research_only"])
        detail = pullback_strategy["pullback_gate_details"][0]
        self.assertEqual(detail["symbol"], "AVAX/USD")
        self.assertEqual(detail["final_blocker"], "passed_all_strategy_gates")
        self.assertTrue(detail["paper_research_eligible"])
        self.assertFalse(detail["paper_execution_allowed"])
        self.assertTrue(detail["paper_research_allowed"])
        self.assertFalse(detail["live_execution_allowed"])
        checks = {item["name"]: item for item in detail["checks"]}
        self.assertTrue(checks["pullback_min"]["passed"])
        self.assertTrue(checks["discovery_min"]["passed"])
        self.assertFalse(checks["volume_gbp_preferred"]["passed"])
        self.assertFalse(checks["volume_gbp_preferred"]["blocking"])

        rendered = ProposalPipelineDiagnosticsReport(
            config=config,
            usage_ledger=_FakeUsageLedger(latest_tick),
        ).render(report=report)
        self.assertIn("strategy: crypto_pullback.downside_reversal_watch", rendered)
        self.assertIn("paper_execution_allowed: no", rendered)
        self.assertIn("paper_research_allowed: yes", rendered)
        self.assertIn("live_execution_allowed: no", rendered)
        self.assertIn("pullback_gate_details:", rendered)
        self.assertIn("paper_research_eligible=yes", rendered)
        self.assertIn("live_approved: 0", rendered)

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            paper_execution_allowed_strategies=("mean_reversion.snapback",),
            live_execution_allowed_strategies=(),
            paper_execution_kill_switch=False,
            paper_execution_enabled=True,
            live_execution_enabled=False,
            live_execution_kill_switch=True,
            alpaca_live_api_configured=False,
            live_execution_activation_ack="",
            shadow_proposal_cooldown_minutes=30,
            shadow_proposal_limit=5,
            shadow_min_opportunity_score=55.0,
            strategy_allocation_suppress_threshold=-6.5,
            strategy_allocation_crypto_suppress_threshold=-6.5,
            strategy_allocation_min_checkpoints=3,
            strategy_allocation_favor_threshold=0.0,
            centaur_environment="paper",
            paper_min_signal_score_to_trade=96.0,
            paper_execution_high_score_override_fitness_margin=0.0,
            live_min_signal_score_to_trade=96.0,
            live_execution_high_score_override_fitness_margin=0.0,
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=60.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=2.5,
            crypto_momentum_min_trade_count=2,
            crypto_momentum_min_volume_gbp=50000.0,
            crypto_momentum_max_spread_pct=0.25,
        )


if __name__ == "__main__":
    unittest.main()
