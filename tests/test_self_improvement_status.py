from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from app.framework.reporting.self_improvement_status import (
    SelfImprovementStatusReport,
    VALID_FINAL_STATUSES,
)
from app.framework.reporting import self_improvement_status as self_improvement_status_module


def _decision(
    strategy_id: str,
    profile_id: str,
    *,
    net_return: float,
    win_rate: float,
    proposals_created: int,
    recommendation: str = "research_only",
    blockers: list[str] | None = None,
    timeframe: str = "1h",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "profile_id": profile_id,
        "recommendation": recommendation,
        "proposals_created": proposals_created,
        "signals_generated": proposals_created + 2,
        "outcomes_recorded": max(0, proposals_created - 1),
        "blocker_reasons": blockers or [],
        "net_return_summary": {"avg_pct": net_return},
        "win_rate_summary": {"avg": win_rate},
        "timeframe": timeframe,
    }


def _cycle(
    *,
    started_at: datetime,
    cycle_origin: str,
    decisions: list[dict[str, object]],
    source: str = "real_heartbeat",
    command_source: str = "unknown",
    historical_windows_selected: int = 4,
    latest_valid_replay_window_end: str = "2026-06-06T08:00:00+00:00",
    latest_available_historical_bar_at: str = "2026-06-06T08:05:00+00:00",
    pre_replay_refresh_enabled: str = "no",
    pre_replay_refresh_dry_run: str = "yes",
    pre_replay_refresh_ran: str = "no",
    pre_replay_refresh_mode: str = "disabled",
    ingestion_ran_this_cycle: str = "no",
    bars_inserted_this_cycle: int = 0,
    bars_updated_this_cycle: int = 0,
    latest_bar_before_ingestion: str = "2026-06-06T08:05:00+00:00",
    latest_bar_after_ingestion: str = "2026-06-06T08:05:00+00:00",
    replay_windows_selected_from_latest_available_data: str = "yes",
    reason_if_not: str = "",
    latest_available_bar_per_asset_class: dict[str, str] | None = None,
    latest_available_bar_per_symbol: dict[str, str] | None = None,
    latest_replay_eligible_bar_per_timeframe: dict[str, str] | None = None,
    latest_replay_eligible_bar_per_asset_class: dict[str, str] | None = None,
    candidate_replay_windows_considered: list[dict[str, object]] | None = None,
    candidate_replay_windows_rejected: list[dict[str, object]] | None = None,
    selected_replay_windows: list[dict[str, object]] | None = None,
    selected_replay_window_reason: str = "latest_available_bar_timestamp_used_directly",
    max_allowed_replay_window_end: str = "2026-06-06T08:00:00+00:00",
    global_anchor_enabled: str = "yes",
    global_anchor_time: str = "2026-06-06T08:00:00+00:00",
    global_anchor_constrained_by_asset_class: str = "crypto",
    global_anchor_constrained_by_timeframe: str = "15Min",
    global_anchor_constrained_by_symbol: str = "AVAX/USD",
    freshness_lost_to_future_outcome_horizon: str = "7d0h0m0s",
    freshness_lost_to_global_anchor: str = "0s",
    selected_replay_window_end_by_timeframe: dict[str, str] | None = None,
    selected_replay_window_end_by_asset_class: dict[str, str] | None = None,
    selected_replay_window_end_by_bucket: dict[str, str] | None = None,
    accepted_replay_window_count_by_timeframe: dict[str, int] | None = None,
    accepted_replay_window_count_by_asset_class: dict[str, int] | None = None,
    selected_anchor_time_by_bucket: dict[str, str] | None = None,
    candidate_anchor_time_by_bucket: dict[str, str] | None = None,
    rejected_bucket_anchor_time_by_bucket: dict[str, str] | None = None,
    freshness_gain_vs_global_by_bucket: dict[str, str] | None = None,
    windows_selected_by_bucket: dict[str, int] | None = None,
    windows_rejected_by_bucket: dict[str, int] | None = None,
    bucket_rejection_reasons: dict[str, str] | None = None,
    replay_selection_mode: str = "global",
    alternative_replay_selection_modes_available: str = "no",
    simulated_asset_class_anchor_time: dict[str, str] | None = None,
    simulated_asset_class_and_timeframe_anchor_time: dict[str, str] | None = None,
    simulated_freshness_gain_by_asset_class: dict[str, str] | None = None,
    simulated_freshness_gain_by_asset_class_and_timeframe: dict[str, str] | None = None,
    strategies_helped_by_isolated_replay: list[str] | None = None,
    strategies_unaffected_by_isolated_replay: list[str] | None = None,
    strategies_blocked_by_mixed_global_anchor: list[str] | None = None,
    minimum_required_window_completeness: str = "full_replay_window_plus_all_supported_checkpoint_outcomes",
    lookback_window_policy: str = "4_windows_spanning_5_days",
    warmup_buffer_policy: str = "no_extra_selector_warmup_buffer_beyond_requested_window_start",
    market_hours_policy: str = "uses_persisted_bars_only_no_synthetic_market_hours_padding",
    weekend_policy: str = "weekend_bars_allowed_if_present_no_weekend_backfill_padding",
    asset_class_window_policy: str = "single_global_anchor_across_requested_symbol_universe",
    reason_latest_bars_not_used_for_replay: str = "latest_available_bar_timestamp_is_itself_replay_eligible",
    plain_english_replay_anchor_explanation: str = "Newest raw bars are not immediately replay-eligible because replay needs 7d0h0m0s of future outcome data.",
    refresh_attempted_symbols: dict[str, list[str]] | None = None,
    refresh_success_symbols: dict[str, list[str]] | None = None,
    refresh_failed_symbols: dict[str, list[str]] | None = None,
    refresh_skipped_symbols: dict[str, list[str]] | None = None,
    refresh_skip_reasons: dict[str, list[str]] | None = None,
    provider_error_count: int = 0,
    provider_errors: list[str] | None = None,
) -> dict[str, object]:
    return {
        "tick_id": f"researchcycle-{started_at.strftime('%H%M%S')}",
        "started_at": started_at,
        "state_snapshot_json": {
            "run": {
                "pipeline": "research_cycle",
                "source": source,
                "cycle_origin": cycle_origin,
                "command_source": command_source,
            },
            "research_cycle": {
                "historical_windows_selected": historical_windows_selected,
                "usable_decisions_count": len(decisions),
                "paper_candidates_created": sum(
                    1
                    for item in decisions
                    if str(item.get("recommendation")) == "paper_sim_candidate"
                ),
                "paper_removal_candidates_created": 0,
                "latest_valid_replay_window_end": latest_valid_replay_window_end,
                "latest_available_historical_bar_at": latest_available_historical_bar_at,
                "selection_anchor_end_at": latest_valid_replay_window_end,
                "pre_replay_refresh_enabled": pre_replay_refresh_enabled,
                "pre_replay_refresh_dry_run": pre_replay_refresh_dry_run,
                "pre_replay_refresh_ran": pre_replay_refresh_ran,
                "pre_replay_refresh_mode": pre_replay_refresh_mode,
                "pre_replay_refresh_asset_classes": ["crypto"],
                "pre_replay_refresh_symbols": {"equity": [], "crypto": ["AVAX/USD"]},
                "pre_replay_refresh_safety_guard": "historical_backfill_only_no_orders_no_auto_approvals",
                "latest_bar_before_refresh": latest_bar_before_ingestion,
                "latest_bar_after_refresh": latest_bar_after_ingestion,
                "bars_inserted_by_refresh": bars_inserted_this_cycle,
                "bars_updated_by_refresh": bars_updated_this_cycle,
                "refresh_attempted_symbols": refresh_attempted_symbols
                or {"equity": [], "crypto": ["AVAX/USD"]},
                "refresh_success_symbols": refresh_success_symbols
                or {"equity": [], "crypto": []},
                "refresh_failed_symbols": refresh_failed_symbols
                or {"equity": [], "crypto": []},
                "refresh_skipped_symbols": refresh_skipped_symbols
                or {"equity": [], "crypto": []},
                "refresh_skip_reasons": refresh_skip_reasons
                or {"equity": [], "crypto": []},
                "provider_error_count": provider_error_count,
                "provider_errors": provider_errors or [],
                "refresh_error_count": 0,
                "refresh_errors": [],
                "refresh_duration_ms": 15,
                "ingestion_ran_this_cycle": ingestion_ran_this_cycle,
                "bars_inserted_this_cycle": bars_inserted_this_cycle,
                "bars_updated_this_cycle": bars_updated_this_cycle,
                "latest_bar_before_ingestion": latest_bar_before_ingestion,
                "latest_bar_after_ingestion": latest_bar_after_ingestion,
                "replay_windows_selected_from_latest_available_data": replay_windows_selected_from_latest_available_data,
                "latest_raw_bar_at": latest_available_historical_bar_at,
                "max_future_outcome_horizon": "7d0h0m0s",
                "latest_replay_eligible_bar_at": latest_valid_replay_window_end,
                "latest_available_bar_per_asset_class": latest_available_bar_per_asset_class
                or {"crypto": latest_available_historical_bar_at},
                "latest_available_bar_per_symbol": latest_available_bar_per_symbol
                or {"AVAX/USD": latest_available_historical_bar_at},
                "latest_replay_eligible_bar_per_timeframe": latest_replay_eligible_bar_per_timeframe
                or {"15Min": latest_valid_replay_window_end},
                "latest_replay_eligible_bar_per_asset_class": latest_replay_eligible_bar_per_asset_class
                or {"crypto": latest_valid_replay_window_end},
                "candidate_replay_windows_considered": candidate_replay_windows_considered
                or [],
                "candidate_replay_windows_rejected": candidate_replay_windows_rejected
                or [],
                "selected_replay_windows": selected_replay_windows or [],
                "selected_replay_window_reason": selected_replay_window_reason,
                "max_allowed_replay_window_end": max_allowed_replay_window_end,
                "global_anchor_enabled": global_anchor_enabled,
                "global_anchor_time": global_anchor_time,
                "global_anchor_constrained_by_asset_class": global_anchor_constrained_by_asset_class,
                "global_anchor_constrained_by_timeframe": global_anchor_constrained_by_timeframe,
                "global_anchor_constrained_by_symbol": global_anchor_constrained_by_symbol,
                "freshness_lost_to_future_outcome_horizon": freshness_lost_to_future_outcome_horizon,
                "freshness_lost_to_global_anchor": freshness_lost_to_global_anchor,
                "selected_replay_window_end_by_timeframe": selected_replay_window_end_by_timeframe
                or {"15Min": latest_valid_replay_window_end},
                "selected_replay_window_end_by_asset_class": selected_replay_window_end_by_asset_class
                or {"crypto": latest_valid_replay_window_end},
                "selected_replay_window_end_by_bucket": selected_replay_window_end_by_bucket
                or {"crypto/15Min": latest_valid_replay_window_end},
                "accepted_replay_window_count_by_timeframe": accepted_replay_window_count_by_timeframe
                or {"15Min": historical_windows_selected},
                "accepted_replay_window_count_by_asset_class": accepted_replay_window_count_by_asset_class
                or {"crypto": historical_windows_selected},
                "selected_anchor_time_by_bucket": selected_anchor_time_by_bucket
                or {"crypto/15Min": latest_valid_replay_window_end},
                "candidate_anchor_time_by_bucket": candidate_anchor_time_by_bucket
                or {"crypto/15Min": latest_valid_replay_window_end},
                "rejected_bucket_anchor_time_by_bucket": rejected_bucket_anchor_time_by_bucket
                or {},
                "freshness_gain_vs_global_by_bucket": freshness_gain_vs_global_by_bucket
                or {"crypto/15Min": "0s"},
                "windows_selected_by_bucket": windows_selected_by_bucket
                or {"crypto/15Min": historical_windows_selected},
                "windows_rejected_by_bucket": windows_rejected_by_bucket or {},
                "bucket_rejection_reasons": bucket_rejection_reasons or {},
                "replay_selection_mode": replay_selection_mode,
                "alternative_replay_selection_modes_available": alternative_replay_selection_modes_available,
                "simulated_asset_class_anchor_time": simulated_asset_class_anchor_time or {},
                "simulated_asset_class_and_timeframe_anchor_time": simulated_asset_class_and_timeframe_anchor_time
                or {},
                "simulated_freshness_gain_by_asset_class": simulated_freshness_gain_by_asset_class
                or {},
                "simulated_freshness_gain_by_asset_class_and_timeframe": simulated_freshness_gain_by_asset_class_and_timeframe
                or {},
                "strategies_helped_by_isolated_replay": strategies_helped_by_isolated_replay or [],
                "strategies_unaffected_by_isolated_replay": strategies_unaffected_by_isolated_replay
                or [],
                "strategies_blocked_by_mixed_global_anchor": strategies_blocked_by_mixed_global_anchor
                or [],
                "minimum_required_window_completeness": minimum_required_window_completeness,
                "lookback_window_policy": lookback_window_policy,
                "warmup_buffer_policy": warmup_buffer_policy,
                "market_hours_policy": market_hours_policy,
                "weekend_policy": weekend_policy,
                "asset_class_window_policy": asset_class_window_policy,
                "reason_latest_bars_not_used_for_replay": reason_latest_bars_not_used_for_replay,
                "plain_english_replay_anchor_explanation": plain_english_replay_anchor_explanation,
                "reason_if_not": reason_if_not,
                "decisions": decisions,
            },
        },
    }


class _Ledger:
    backend = "postgres"

    def __init__(
        self,
        rows: list[dict[str, object]],
        promotions: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = rows
        self.promotions = promotions or []

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
        return self.rows[:limit]

    def list_strategy_promotions(self) -> list[dict[str, object]]:
        return list(self.promotions)


class SelfImprovementStatusReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(
            research_min_proposals=100,
            research_min_net_return_pct=0.001,
            research_min_net_win_rate=0.55,
        )
        self.now = datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)

    def test_default_report_uses_read_only_skip_bootstrap_ledger(self) -> None:
        calls: list[dict[str, object]] = []
        original_usage_ledger = self_improvement_status_module.UsageLedger

        class _StubLedger:
            backend = "postgres"

            def __init__(self, **kwargs: object) -> None:
                calls.append(dict(kwargs))

            def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, object]]:
                _ = limit
                return []

            def list_strategy_promotions(self) -> list[dict[str, object]]:
                return []

        self_improvement_status_module.UsageLedger = _StubLedger
        try:
            report = SelfImprovementStatusReport(config=self.config).build_report()
        finally:
            self_improvement_status_module.UsageLedger = original_usage_ledger

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["read_only"])
        self.assertTrue(calls[0]["skip_schema_bootstrap"])
        self.assertEqual(calls[0]["query_timeout_ms"], 15000)
        self.assertEqual(calls[0]["lock_timeout_ms"], 5000)

    def test_insufficient_history_reported_clearly(self) -> None:
        report = SelfImprovementStatusReport(
            config=self.config,
            usage_ledger=_Ledger(
                [
                    _cycle(
                        started_at=self.now,
                        cycle_origin="launchd_scheduled",
                        decisions=[
                            _decision(
                                strategy_id="s1",
                                profile_id="p1",
                                net_return=0.0015,
                                win_rate=0.56,
                                proposals_created=20,
                            )
                        ],
                    )
                ]
            ),
        ).build_report()

        self.assertEqual(report["self_improvement_status"], "insufficient_history")
        self.assertEqual(
            report["evidence_quality"]["evidence_quality_status"], "insufficient_history"
        )

    def test_improving_trend_detected(self) -> None:
        latest_bar = datetime.now(timezone.utc)
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision("s1", "p1", net_return=0.003, win_rate=0.62, proposals_created=140),
                ],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=15)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=10)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="real_heartbeat",
                decisions=[
                    _decision("s1", "p1", net_return=0.002, win_rate=0.58, proposals_created=120),
                ],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=35)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=30)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=2),
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision("s1", "p1", net_return=0.0005, win_rate=0.52, proposals_created=80),
                ],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=55)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=50)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=3),
                cycle_origin="real_heartbeat",
                decisions=[
                    _decision("s1", "p1", net_return=0.0004, win_rate=0.51, proposals_created=70),
                ],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=75)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=70)).isoformat(),
            ),
        ]

        report = SelfImprovementStatusReport(
            config=self.config,
            usage_ledger=_Ledger(rows),
        ).build_report()

        self.assertEqual(report["self_improvement_status"], "improving")
        self.assertEqual(report["evidence_quality"]["net_return_trend"], "improving")
        self.assertEqual(report["evidence_quality"]["win_rate_trend"], "improving")

    def test_degrading_trend_detected(self) -> None:
        latest_bar = datetime.now(timezone.utc)
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=-0.001, win_rate=0.48, proposals_created=80)],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=15)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=10)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="real_heartbeat",
                decisions=[_decision("s1", "p1", net_return=0.0, win_rate=0.50, proposals_created=90)],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=35)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=30)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=2),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=0.003, win_rate=0.62, proposals_created=130)],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=55)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=50)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=3),
                cycle_origin="real_heartbeat",
                decisions=[_decision("s1", "p1", net_return=0.002, win_rate=0.60, proposals_created=120)],
                latest_valid_replay_window_end=(latest_bar - timedelta(minutes=75)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=70)).isoformat(),
            ),
        ]

        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["self_improvement_status"], "degrading")
        self.assertEqual(report["evidence_quality"]["evidence_quality_status"], "degrading")

    def test_stuck_condition_detected(self) -> None:
        rows = [
            _cycle(
                started_at=self.now - timedelta(hours=index),
                cycle_origin="launchd_scheduled" if index % 2 == 0 else "real_heartbeat",
                decisions=[
                    _decision(
                        "s1",
                        "p1",
                        net_return=-0.002,
                        win_rate=0.49,
                        proposals_created=50,
                        blockers=["net_return_below_threshold"],
                    )
                ],
                latest_valid_replay_window_end="2026-06-06T08:00:00+00:00",
                latest_available_historical_bar_at="2026-06-06T08:05:00+00:00",
            )
            for index in range(4)
        ]

        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["self_improvement_status"], "stuck")
        self.assertTrue(report["stuck_analysis"]["stuck_detected"])
        self.assertIn("same_top_blocker_dominates", report["stuck_analysis"]["stuck_reason"])

    def test_healthy_infrastructure_but_bad_strategies_reports_strategy_evidence_stuck(self) -> None:
        latest_bar = datetime.now(timezone.utc)
        rows = [
            _cycle(
                started_at=self.now - timedelta(hours=index),
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision(
                        "s1",
                        "p1",
                        net_return=-0.002,
                        win_rate=0.49,
                        proposals_created=50,
                        blockers=["net_return_below_threshold"],
                    )
                ],
                replay_windows_selected_from_latest_available_data="no",
                latest_valid_replay_window_end=(self.now - timedelta(days=8)).isoformat(),
                latest_available_historical_bar_at=(latest_bar - timedelta(minutes=10)).isoformat(),
            )
            for index in range(4)
        ]

        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertTrue(report["stuck_analysis"]["strategy_evidence_stuck"])
        self.assertFalse(report["stuck_analysis"]["system_stuck"])
        self.assertEqual(report["stuck_analysis"]["dominant_blocker"], "net_return_below_threshold")
        self.assertIn("operating correctly and collecting fresh replay evidence", report["explanation"])

    def test_stale_bars_report_system_stuck(self) -> None:
        rows = [
            _cycle(
                started_at=self.now - timedelta(hours=index),
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision(
                        "s1",
                        "p1",
                        net_return=-0.002,
                        win_rate=0.49,
                        proposals_created=50,
                        blockers=["net_return_below_threshold"],
                    )
                ],
                latest_valid_replay_window_end=(self.now - timedelta(days=9)).isoformat(),
                latest_available_historical_bar_at=(self.now - timedelta(days=2)).isoformat(),
            )
            for index in range(4)
        ]

        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertTrue(report["stuck_analysis"]["system_stuck"])
        self.assertIn("historical_bars_not_fresh", report["stuck_analysis"]["stuck_reason"])

    def test_repeated_net_return_blocker_reports_dominant_blocker_clearly(self) -> None:
        rows = [
            _cycle(
                started_at=self.now - timedelta(hours=index),
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision(
                        "s1",
                        "p1",
                        net_return=-0.004,
                        win_rate=0.52,
                        proposals_created=70,
                        blockers=["net_return_below_threshold", "win_rate_below_threshold"],
                    )
                ],
            )
            for index in range(4)
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["stuck_analysis"]["dominant_blocker"], "net_return_below_threshold")
        self.assertEqual(report["stuck_analysis"]["dominant_blocker_cycles"], 4)
        self.assertIn("net_return_below_threshold", report["stuck_analysis"]["blocker_counts_recent"])

    def test_improving_strategy_distance_reduces_stuck_severity(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=0.009, win_rate=0.54, proposals_created=95, blockers=["net_return_below_threshold"])],
                latest_available_historical_bar_at=(self.now - timedelta(minutes=5)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=0.007, win_rate=0.53, proposals_created=90, blockers=["net_return_below_threshold"])],
                latest_available_historical_bar_at=(self.now - timedelta(minutes=6)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=2),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=0.005, win_rate=0.52, proposals_created=80, blockers=["net_return_below_threshold"])],
                latest_available_historical_bar_at=(self.now - timedelta(minutes=7)).isoformat(),
            ),
            _cycle(
                started_at=self.now - timedelta(hours=3),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=0.003, win_rate=0.51, proposals_created=70, blockers=["net_return_below_threshold"])],
                latest_available_historical_bar_at=(self.now - timedelta(minutes=8)).isoformat(),
            ),
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["strategy_trends"][0]["trend"], "improving")
        self.assertLess(report["stuck_analysis"]["cycles_without_strategy_improvement"], 3)

    def test_no_approvals_or_orders_are_created_in_stuck_reporting(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("s1", "p1", net_return=-0.01, win_rate=0.4, proposals_created=25)],
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["learning"]["broker_orders_created"], 0)
        self.assertEqual(report["learning"]["live_orders_created"], 0)
        self.assertEqual(report["learning"]["auto_paper_approved"], 0)
        self.assertEqual(report["learning"]["auto_live_approved"], 0)

    def test_closest_to_promotion_ranking_works(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision("s-best", "p-best", net_return=0.0009, win_rate=0.54, proposals_created=95),
                    _decision("s-mid", "p-mid", net_return=0.0004, win_rate=0.52, proposals_created=80),
                ],
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        ranked = report["closest_to_promotion"]
        self.assertEqual(ranked[0]["strategy_id"], "s-best")
        self.assertEqual(ranked[0]["rank"], 1)

    def test_evidence_backed_profiles_rank_above_zero_evidence_profiles(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[
                    _decision("s-live", "p-live", net_return=-0.20, win_rate=0.03, proposals_created=258),
                    _decision(
                        "s-empty",
                        "p-empty",
                        net_return=0.0,
                        win_rate=0.0,
                        proposals_created=0,
                        blockers=["insufficient_sample_size"],
                    ),
                ],
                latest_valid_replay_window_end=(self.now - timedelta(minutes=15)).isoformat(),
                latest_available_historical_bar_at=(self.now - timedelta(minutes=10)).isoformat(),
            )
        ]

        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        ranked = report["closest_to_promotion"]
        self.assertEqual(ranked[0]["strategy_id"], "s-live")
        self.assertEqual(ranked[0]["profile_id"], "p-live")
        self.assertEqual(ranked[0]["current_sample_size"], 258)
        self.assertEqual(ranked[0]["current_net_return"], "-20.00%")
        self.assertEqual(ranked[0]["current_win_rate"], "+3.00%")
        self.assertEqual(ranked[0]["action"], "keep_collecting_evidence")
        self.assertEqual(ranked[1]["strategy_id"], "s-empty")
        self.assertIn("no_real_evidence_yet", ranked[1]["failed_gates"])
        self.assertEqual(ranked[1]["action"], "collect_real_replay_evidence")

    def test_report_uses_only_real_allowed_origins_and_excludes_synthetic(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="manual_cli",
                decisions=[_decision("synthetic", "proof", net_return=0.9, win_rate=0.99, proposals_created=999, recommendation="paper_sim_candidate")],
            ),
            {
                "tick_id": "proof-run",
                "started_at": self.now - timedelta(minutes=30),
                "state_snapshot_json": {
                    "run": {"pipeline": "research_cycle", "source": "manual_cli", "cycle_origin": "manual_cli"},
                    "research_cycle": {"decisions": []},
                },
            },
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
            ),
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["lookback_cycles"], 1)
        self.assertEqual(report["closest_to_promotion"][0]["strategy_id"], "real")

    def test_forced_one_shot_real_cycle_is_included(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="forced_one_shot",
                command_source="main.py --heartbeat-autonomous-learning-once",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                pre_replay_refresh_enabled="yes",
                pre_replay_refresh_dry_run="yes",
                pre_replay_refresh_ran="yes",
                pre_replay_refresh_mode="dry_run",
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["lookback_cycles"], 1)
        self.assertEqual(report["freshness_diagnostics"]["pre_replay_refresh_enabled"], "yes")
        self.assertEqual(report["freshness_diagnostics"]["pre_replay_refresh_mode"], "dry_run")
        self.assertEqual(
            report["learning"]["latest_persisted_cycle_included_in_self_improvement"],
            "yes",
        )
        self.assertEqual(
            report["learning"]["latest_persisted_command_source"],
            "main.py --heartbeat-autonomous-learning-once",
        )

    def test_newer_excluded_persisted_cycle_reports_exact_reason(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="manual_cli",
                source="manual_cli",
                command_source="main.py --research-cycle",
                decisions=[_decision("synthetic", "proof", net_return=0.9, win_rate=0.99, proposals_created=999)],
            ),
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
            ),
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["lookback_cycles"], 1)
        self.assertEqual(
            report["learning"]["latest_persisted_cycle_included_in_self_improvement"],
            "no",
        )
        self.assertEqual(
            report["learning"]["latest_persisted_cycle_exclusion_reason"],
            "source_not_real_heartbeat",
        )
        self.assertEqual(
            report["learning"]["latest_qualifying_self_improvement_cycle_time"],
            (self.now - timedelta(hours=1)).isoformat(),
        )

    def test_latest_qualifying_cycle_is_shown_clearly(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="forced_one_shot",
                command_source="main.py --heartbeat-autonomous-learning-once",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                replay_selection_mode="asset_class_and_timeframe",
            ),
            _cycle(
                started_at=self.now - timedelta(hours=1),
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p2", net_return=0.001, win_rate=0.56, proposals_created=30)],
            ),
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(
            report["learning"]["latest_persisted_cycle_id"],
            f"researchcycle-{self.now.strftime('%H%M%S')}",
        )
        self.assertEqual(
            report["learning"]["latest_qualifying_self_improvement_cycle_id"],
            f"researchcycle-{self.now.strftime('%H%M%S')}",
        )
        self.assertEqual(
            report["freshness_diagnostics"]["replay_selection_mode"],
            "asset_class_and_timeframe",
        )

    def test_broker_live_safety_unchanged(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["learning"]["broker_orders_created"], 0)
        self.assertEqual(report["learning"]["live_orders_created"], 0)
        self.assertEqual(report["learning"]["auto_paper_approved"], 0)
        self.assertEqual(report["learning"]["auto_live_approved"], 0)

    def test_freshness_diagnostics_use_bar_and_window_age(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                latest_valid_replay_window_end=(datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(),
                latest_available_historical_bar_at=(datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat(),
                latest_available_bar_per_asset_class={"crypto": (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()},
                latest_available_bar_per_symbol={"AVAX/USD": (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()},
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        self.assertEqual(report["freshness_diagnostics"]["fresh_historical_bars_detected"], "yes")
        self.assertEqual(
            report["freshness_diagnostics"]["replay_window_set_changed_from_previous_real_cycle"],
            "unknown",
        )
        self.assertIn("current_system_time", report["freshness_diagnostics"])
        self.assertIn("freshness_threshold_used", report["freshness_diagnostics"])

    def test_refresh_diagnostics_appear_in_json_report(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                latest_valid_replay_window_end=(datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(),
                latest_available_historical_bar_at=(datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat(),
                pre_replay_refresh_enabled="yes",
                pre_replay_refresh_dry_run="yes",
                pre_replay_refresh_ran="yes",
                pre_replay_refresh_mode="dry_run",
                ingestion_ran_this_cycle="no",
                bars_inserted_this_cycle=0,
                bars_updated_this_cycle=0,
                latest_bar_before_ingestion=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                latest_bar_after_ingestion=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        freshness = report["freshness_diagnostics"]
        self.assertEqual(freshness["pre_replay_refresh_enabled"], "yes")
        self.assertEqual(freshness["pre_replay_refresh_dry_run"], "yes")
        self.assertEqual(freshness["pre_replay_refresh_ran"], "yes")
        self.assertEqual(freshness["pre_replay_refresh_mode"], "dry_run")
        self.assertEqual(
            freshness["pre_replay_refresh_safety_guard"],
            "historical_backfill_only_no_orders_no_auto_approvals",
        )
        self.assertEqual(freshness["ingestion_ran_this_cycle"], "no")
        self.assertEqual(freshness["bars_inserted_this_cycle"], 0)
        self.assertEqual(freshness["bars_updated_this_cycle"], 0)
        self.assertEqual(freshness["replay_windows_selected_from_latest_available_data"], "yes")
        self.assertIn("crypto:", freshness["latest_available_bar_per_asset_class"])
        self.assertIn("15Min:", freshness["latest_replay_eligible_bar_per_timeframe"])

    def test_fresh_data_reports_fresh_after_write_mode_refresh(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                latest_valid_replay_window_end=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
                latest_available_historical_bar_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                pre_replay_refresh_enabled="yes",
                pre_replay_refresh_dry_run="no",
                pre_replay_refresh_ran="yes",
                pre_replay_refresh_mode="write",
                ingestion_ran_this_cycle="yes",
                bars_inserted_this_cycle=3,
                bars_updated_this_cycle=7,
                latest_bar_before_ingestion=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                latest_bar_after_ingestion=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        freshness = report["freshness_diagnostics"]
        self.assertEqual(freshness["pre_replay_refresh_mode"], "write")
        self.assertEqual(freshness["ingestion_ran_this_cycle"], "yes")
        self.assertEqual(freshness["bars_updated_this_cycle"], 7)
        self.assertEqual(freshness["fresh_historical_bars_detected"], "yes")

    def test_stale_window_explains_latest_bars_not_used(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                latest_valid_replay_window_end="2026-05-29T09:00:00+00:00",
                latest_available_historical_bar_at="2026-06-06T16:15:00+00:00",
                replay_windows_selected_from_latest_available_data="no",
                latest_replay_eligible_bar_per_timeframe={
                    "15Min": "2026-05-30T16:30:00+00:00",
                    "1Hour": "2026-05-29T09:00:00+00:00",
                },
                latest_replay_eligible_bar_per_asset_class={
                    "crypto": "2026-05-30T16:30:00+00:00",
                    "mixed": "2026-05-29T09:00:00+00:00",
                },
                latest_available_bar_per_asset_class={
                    "crypto": "2026-06-06T16:15:00+00:00",
                    "equity": "2026-05-29T09:00:00+00:00",
                },
                latest_available_bar_per_symbol={
                    "AVAX/USD": "2026-06-06T16:15:00+00:00",
                    "AAPL": "2026-05-29T09:00:00+00:00",
                },
                candidate_replay_windows_considered=[
                    {
                        "asset_class": "mixed",
                        "timeframe": "1Min",
                        "window_index": 1,
                        "start_at": "2026-05-24T09:00:00+00:00",
                        "end_at": "2026-05-25T15:00:00+00:00",
                        "reason": "ok",
                    }
                ],
                selected_replay_windows=[
                    {
                        "asset_class": "mixed",
                        "timeframe": "1Min",
                        "window_index": 1,
                        "start_at": "2026-05-24T09:00:00+00:00",
                        "end_at": "2026-05-25T15:00:00+00:00",
                        "reason": "ok",
                    }
                ],
                max_allowed_replay_window_end="2026-05-29T09:00:00+00:00",
                global_anchor_enabled="yes",
                global_anchor_time="2026-05-29T09:00:00+00:00",
                global_anchor_constrained_by_asset_class="mixed",
                global_anchor_constrained_by_timeframe="1Hour",
                global_anchor_constrained_by_symbol="AAPL",
                freshness_lost_to_future_outcome_horizon="7d0h0m0s",
                freshness_lost_to_global_anchor="1d7h30m0s",
                selected_replay_window_end_by_timeframe={
                    "15Min": "2026-05-30T16:30:00+00:00",
                    "1Hour": "2026-05-29T09:00:00+00:00",
                },
                selected_replay_window_end_by_asset_class={
                    "crypto": "2026-05-30T16:30:00+00:00",
                    "mixed": "2026-05-29T09:00:00+00:00",
                },
                selected_replay_window_end_by_bucket={
                    "crypto/15Min": "2026-05-30T16:30:00+00:00",
                    "crypto/1Hour": "2026-05-29T09:00:00+00:00",
                },
                selected_anchor_time_by_bucket={
                    "crypto/15Min": "2026-05-30T16:30:00+00:00",
                    "crypto/1Hour": "2026-05-29T09:00:00+00:00",
                },
                candidate_anchor_time_by_bucket={
                    "crypto/15Min": "2026-05-30T16:30:00+00:00",
                    "crypto/1Hour": "2026-05-29T09:00:00+00:00",
                    "equity/1Hour": "2026-05-29T09:00:00+00:00",
                },
                rejected_bucket_anchor_time_by_bucket={
                    "equity/1Hour": "2026-05-29T09:00:00+00:00",
                },
                freshness_gain_vs_global_by_bucket={
                    "crypto/15Min": "1d7h30m0s",
                    "crypto/1Hour": "0s",
                },
                windows_selected_by_bucket={
                    "crypto/15Min": 4,
                    "crypto/1Hour": 4,
                },
                windows_rejected_by_bucket={
                    "equity/1Hour": 4,
                },
                bucket_rejection_reasons={
                    "equity/1Hour": "no_matching_historical_rows_for_requested_symbols",
                },
                replay_selection_mode="global",
                alternative_replay_selection_modes_available="yes",
                simulated_asset_class_anchor_time={
                    "crypto": "2026-05-30T16:30:00+00:00",
                    "equity": "2026-05-29T09:00:00+00:00",
                },
                simulated_asset_class_and_timeframe_anchor_time={
                    "crypto/15Min": "2026-05-30T16:30:00+00:00",
                    "equity/15Min": "2026-05-29T09:00:00+00:00",
                },
                simulated_freshness_gain_by_asset_class={
                    "crypto": "1d7h30m0s",
                    "equity": "0s",
                },
                simulated_freshness_gain_by_asset_class_and_timeframe={
                    "crypto/15Min": "1d7h30m0s",
                    "equity/15Min": "0s",
                },
                strategies_helped_by_isolated_replay=[
                    "crypto_pullback.downside_continuation_watch/downside_continuation_watch"
                ],
                strategies_unaffected_by_isolated_replay=[],
                strategies_blocked_by_mixed_global_anchor=[
                    "crypto_pullback.downside_continuation_watch/downside_continuation_watch"
                ],
                reason_latest_bars_not_used_for_replay="latest_available_bar_not_used_because_selector_uses_global_oldest_valid_anchor_across_asset_classes",
                plain_english_replay_anchor_explanation="Newest raw bars are not immediately replay-eligible because replay needs 7d0h0m0s of future outcome data. The current global selector is additionally constrained by mixed/1Hour/AAPL, so fresher crypto 15Min data is being held back by older coverage. Additional freshness lost to the global anchor: 1d7h30m0s. In asset_class_and_timeframe mode, crypto 15Min could replay up to 2026-05-30T16:30:00+00:00 while 1Hour/mixed remains anchored at 2026-05-29T09:00:00+00:00. Potential freshness gain for crypto 15Min: 1d7h30m0s.",
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        freshness = report["freshness_diagnostics"]
        self.assertEqual(freshness["replay_windows_selected_from_latest_available_data"], "no")
        self.assertIn(
            "global_oldest_valid_anchor_across_asset_classes",
            freshness["reason_latest_bars_not_used_for_replay"],
        )
        self.assertIn("AAPL:", freshness["latest_available_bar_per_symbol"])
        self.assertIn("asset_class=mixed", freshness["selected_replay_windows"])
        self.assertIn("1Hour:2026-05-29T09:00:00+00:00", freshness["selected_replay_window_end_by_timeframe"])
        self.assertIn("mixed:2026-05-29T09:00:00+00:00", freshness["selected_replay_window_end_by_asset_class"])
        self.assertIn("crypto/15Min:2026-05-30T16:30:00+00:00", freshness["selected_replay_window_end_by_bucket"])
        self.assertIn("crypto/15Min:2026-05-30T16:30:00+00:00", freshness["selected_anchor_time_by_bucket"])
        self.assertNotIn("equity/1Hour", freshness["selected_anchor_time_by_bucket"])
        self.assertIn("equity/1Hour:2026-05-29T09:00:00+00:00", freshness["candidate_anchor_time_by_bucket"])
        self.assertIn("equity/1Hour:2026-05-29T09:00:00+00:00", freshness["rejected_bucket_anchor_time_by_bucket"])
        self.assertEqual(freshness["global_anchor_constrained_by_timeframe"], "1Hour")
        self.assertIn("future outcome data", freshness["plain_english_replay_anchor_explanation"])
        self.assertEqual(freshness["replay_selection_mode"], "global")
        self.assertEqual(freshness["alternative_replay_selection_modes_available"], "yes")
        self.assertIn("crypto/15Min:1d7h30m0s", freshness["freshness_gain_vs_global_by_bucket"])
        self.assertIn("equity/1Hour:4", freshness["windows_rejected_by_bucket"])
        self.assertIn(
            "crypto/15Min:2026-05-30T16:30:00+00:00",
            freshness["simulated_asset_class_and_timeframe_anchor_time"],
        )
        self.assertIn(
            "crypto:1d7h30m0s",
            freshness["simulated_freshness_gain_by_asset_class"],
        )
        self.assertIn(
            "crypto_pullback.downside_continuation_watch/downside_continuation_watch",
            freshness["strategies_helped_by_isolated_replay"],
        )

    def test_write_mode_zero_bars_surfaces_reason_in_status_report(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
                pre_replay_refresh_enabled="yes",
                pre_replay_refresh_dry_run="no",
                pre_replay_refresh_ran="yes",
                pre_replay_refresh_mode="write",
                ingestion_ran_this_cycle="yes",
                bars_inserted_this_cycle=0,
                bars_updated_this_cycle=0,
                refresh_attempted_symbols={"equity": [], "crypto": ["AVAX/USD"]},
                refresh_success_symbols={"equity": [], "crypto": []},
                refresh_skipped_symbols={"equity": [], "crypto": ["AVAX/USD"]},
                refresh_skip_reasons={"equity": [], "crypto": ["provider_returned_no_bars"]},
            )
        ]
        report = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).build_report()

        freshness = report["freshness_diagnostics"]
        self.assertEqual(freshness["bars_inserted_by_refresh"], 0)
        self.assertEqual(freshness["bars_updated_by_refresh"], 0)
        self.assertEqual(
            freshness["refresh_skip_reasons"]["crypto"],
            ["provider_returned_no_bars"],
        )

    def test_plain_text_output_ends_with_valid_status(self) -> None:
        rows = [
            _cycle(
                started_at=self.now,
                cycle_origin="launchd_scheduled",
                decisions=[_decision("real", "p1", net_return=0.001, win_rate=0.56, proposals_created=40)],
            )
        ]
        rendered = SelfImprovementStatusReport(config=self.config, usage_ledger=_Ledger(rows)).render()
        last_status_line = [line for line in rendered.splitlines() if line.startswith("self_improvement_status=")][-1]
        self.assertIn(last_status_line.split("=", 1)[1], VALID_FINAL_STATUSES)


if __name__ == "__main__":
    unittest.main()
