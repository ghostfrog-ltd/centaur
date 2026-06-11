from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

import app.framework.engine.research_cycle as research_cycle_module
import app.framework.storage.usage as usage_module
from app.framework.engine.research_cycle import ResearchCycleRunner
from app.framework.runtime.control import ControlPipelineRunner
from app.framework.storage.usage import UsageLedger


@dataclass(frozen=True)
class _FakeProfile:
    strategy_id: str
    profile_id: str
    asset_classes: tuple[str, ...] = ("crypto",)
    parameters: dict[str, object] = field(default_factory=lambda: {"research_only": True})


class _FakeStrategy:
    def build_profiles(self, _config) -> list[_FakeProfile]:
        return [_FakeProfile("crypto_pullback.downside_continuation_watch", "downside_continuation_watch")]


class _FakeLedger:
    def __init__(self) -> None:
        self.tick_runs: list[object] = []
        self.decisions: list[dict[str, object]] = []
        self.promotion_updates: list[dict[str, object]] = []
        self.attention_alerts: dict[str, dict[str, object]] = {}
        self.resolved_alerts: list[dict[str, object]] = []
        self.paper_trade_orders_recorded = 0
        self.live_trade_orders_recorded = 0
        self.paper_approvals_recorded = 0
        self.live_approvals_recorded = 0
        self.backend = "sqlite"
        self.backend_detail = "test"
        self.replay_progress_cursors: dict[str, dict[str, object]] = {}

    def record_tick_run(self, report: object) -> bool:
        self.tick_runs.append(report)
        return True

    def record_research_cycle_decisions(self, *, decisions: list[dict[str, object]]) -> int:
        self.decisions.extend(decisions)
        return len(decisions)

    def record_strategy_promotion_evaluation(self, **kwargs) -> None:
        self.promotion_updates.append(kwargs)

    def list_shadow_trade_proposals_by_note_prefix(self, *, note_prefix: str) -> list[dict[str, object]]:
        if "15Min-run-1" not in note_prefix:
            return []
        return [
            {
                "proposal_id": "p1",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "AVAX/USD",
            },
            {
                "proposal_id": "p2",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "SOL/USD",
            },
        ]

    def list_shadow_trade_outcomes_by_note_prefix(self, *, note_prefix: str) -> list[dict[str, object]]:
        if "15Min-run-1" not in note_prefix:
            return []
        return [
            {
                "proposal_id": "p1",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "AVAX/USD",
                "realized_return_pct": 0.44,
                "max_adverse_excursion_pct": -0.18,
            },
            {
                "proposal_id": "p2",
                "strategy_id": "crypto_pullback.downside_continuation_watch",
                "profile_id": "downside_continuation_watch",
                "symbol": "SOL/USD",
                "realized_return_pct": 0.24,
                "max_adverse_excursion_pct": -0.11,
            },
        ]

    def record_paper_trade_orders(self, **_kwargs) -> int:
        self.paper_trade_orders_recorded += 1
        raise AssertionError("research cycle must not record broker paper trades")

    def record_live_trade_orders(self, **_kwargs) -> int:
        self.live_trade_orders_recorded += 1
        raise AssertionError("research cycle must not record live trades")

    def approve_strategy_for_paper(self, **_kwargs) -> None:
        self.paper_approvals_recorded += 1
        raise AssertionError("research cycle must not auto-approve paper")

    def approve_strategy_for_live(self, **_kwargs) -> None:
        self.live_approvals_recorded += 1
        raise AssertionError("research cycle must not auto-approve live")

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str):
        return None

    def get_attention_alert(self, *, event_id: str):
        return self.attention_alerts.get(event_id)

    def upsert_attention_alert(self, *, alert: dict[str, object]) -> None:
        self.attention_alerts[str(alert.get("event_id", ""))] = dict(alert)

    def resolve_attention_alert(
        self,
        *,
        event_id: str,
        status: str,
        reason: str,
        resolved_at: datetime | None = None,
    ) -> None:
        self.resolved_alerts.append(
            {
                "event_id": event_id,
                "status": status,
                "reason": reason,
                "resolved_at": resolved_at,
            }
        )

    def list_due_attention_alerts(self, *, due_at: datetime):
        _ = due_at
        return []

    def mark_attention_alert_sent(self, **_kwargs) -> None:
        return None

    def list_replay_progress_cursors(self) -> list[dict[str, object]]:
        return [dict(value) for _, value in sorted(self.replay_progress_cursors.items())]

    def upsert_replay_progress_cursor(
        self,
        *,
        bucket: str,
        last_replayed_until: datetime,
        last_selected_window_hash: str,
        last_research_cycle_id: str,
        last_updated_at: datetime,
    ) -> None:
        self.replay_progress_cursors[bucket] = {
            "bucket": bucket,
            "last_replayed_until": last_replayed_until,
            "last_selected_window_hash": last_selected_window_hash,
            "last_research_cycle_id": last_research_cycle_id,
            "last_updated_at": last_updated_at,
        }


class ResearchCycleRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._lock_temp_dir = TemporaryDirectory()
        self._research_cycle_lock_dir = (
            Path(self._lock_temp_dir.name) / "ghostfrog-centaur-research-cycle.lock"
        )

    def tearDown(self) -> None:
        self._lock_temp_dir.cleanup()

    def test_default_config_keeps_old_behavior_without_refresh_runner(self) -> None:
        original_backfill_runner = research_cycle_module.HistoricalBackfillRunner

        class _ForbiddenBackfillRunner:
            def __init__(self, *args, **kwargs) -> None:
                raise AssertionError("pre-replay refresh should remain disabled by default")

        research_cycle_module.HistoricalBackfillRunner = _ForbiddenBackfillRunner
        try:
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=_FakeLedger(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-default",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            diagnostics = runner.build_historical_replay_diagnostics()
        finally:
            research_cycle_module.HistoricalBackfillRunner = original_backfill_runner

        self.assertEqual(diagnostics["pre_replay_refresh_enabled"], "no")
        self.assertEqual(diagnostics["pre_replay_refresh_ran"], "no")
        self.assertEqual(diagnostics["pre_replay_refresh_mode"], "disabled")
        self.assertEqual(diagnostics["bars_inserted_by_refresh"], 0)
        self.assertEqual(diagnostics["bars_updated_by_refresh"], 0)

    def test_build_historical_replay_diagnostics_anchors_windows_to_latest_historical_bar(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 5, 9, 45, tzinfo=tz)
        earliest_bar = latest_bar - timedelta(days=20)
        rows = []
        current = earliest_bar
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _CoverageLedger(_FakeLedger):
            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                _ = (sources, symbols)
                selected = [dict(row) for row in rows if str(row.get("timeframe")) == timeframe]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        runner = ResearchCycleRunner(
            config=self._config(),
            usage_ledger=_CoverageLedger(),
            source="real_heartbeat",
            parent_tick_id="heartbeat-1",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)

        diagnostics = runner.build_historical_replay_diagnostics(end_at=datetime(2026, 6, 6, 11, 2, tzinfo=tz))

        self.assertEqual(
            diagnostics["latest_valid_replay_window_end"].isoformat(),
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(diagnostics["window_anchor_mode"], "latest_historical_bar_minus_future_horizon")
        self.assertEqual(diagnostics["ingestion_ran_this_cycle"], "no")
        self.assertEqual(diagnostics["bars_inserted_this_cycle"], 0)
        self.assertEqual(diagnostics["bars_updated_this_cycle"], 0)
        self.assertEqual(
            diagnostics["latest_bar_before_ingestion"].isoformat(),
            "2026-06-05T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["latest_bar_after_ingestion"].isoformat(),
            "2026-06-05T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["replay_windows_selected_from_latest_available_data"],
            "no",
        )
        self.assertEqual(
            diagnostics["reason_latest_bars_not_used_for_replay"],
            "latest_available_bar_not_used_because_future_checkpoint_completeness_requires_older_anchor",
        )
        self.assertEqual(
            diagnostics["max_allowed_replay_window_end"],
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["latest_raw_bar_at"],
            "2026-06-05T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["latest_replay_eligible_bar_at"],
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["max_future_outcome_horizon"],
            "7d0h0m0s",
        )
        self.assertEqual(
            diagnostics["freshness_lost_to_future_outcome_horizon"],
            "7d0h0m0s",
        )
        self.assertEqual(
            diagnostics["latest_available_bar_per_asset_class"]["crypto"],
            "2026-06-05T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["latest_available_bar_per_symbol"]["AVAX/USD"],
            "2026-06-05T09:45:00+00:00",
        )
        freshness = diagnostics["asset_class_freshness_status"]
        self.assertEqual(freshness["crypto"]["fresh"], "no")
        self.assertEqual(freshness["equity"]["reason"], "no_historical_bars_for_asset_class")
        self.assertGreater(diagnostics["replay_windows_accepted_count"], 0)
        accepted = diagnostics["replay_window_acceptances"]
        self.assertTrue(all(item["timeframe"] == "15Min" for item in accepted))
        self.assertTrue(
            all(item["end_at"] <= "2026-05-29T09:45:00+00:00" for item in accepted)
        )
        self.assertEqual(
            diagnostics["selected_replay_window_reason"],
            "ok",
        )
        self.assertEqual(
            diagnostics["selected_replay_window_end_by_timeframe"]["15Min"],
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["selected_replay_window_end_by_asset_class"]["crypto"],
            "2026-05-29T09:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["asset_class_window_policy"],
            "single_global_anchor_across_requested_symbol_universe",
        )

    def test_dry_run_reports_intended_refresh_without_writing_bars(self) -> None:
        original_backfill_runner = research_cycle_module.HistoricalBackfillRunner
        calls: list[dict[str, object]] = []

        class _DryRunBackfillRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self, **kwargs):
                calls.append(dict(kwargs))
                return SimpleNamespace(
                    state_snapshot={
                        "historical_equity_backfill": {
                            "bars_inserted": 0,
                            "bars_updated": 0,
                        },
                        "historical_crypto_backfill": {
                            "bars_inserted": 0,
                            "bars_updated": 0,
                        },
                    },
                    persistence_error="",
                )

        research_cycle_module.HistoricalBackfillRunner = _DryRunBackfillRunner
        try:
            config = self._config(
                pre_replay_historical_refresh_enabled=True,
                pre_replay_historical_refresh_dry_run=True,
            )
            runner = ResearchCycleRunner(
                config=config,
                usage_ledger=_CoverageLedgerForRefresh(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-dry-run",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            diagnostics = runner.build_historical_replay_diagnostics(
                pre_replay_refresh=runner._run_pre_replay_historical_refresh(
                    as_of=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC"))
                ),
                end_at=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC")),
            )
        finally:
            research_cycle_module.HistoricalBackfillRunner = original_backfill_runner

        self.assertEqual(len(calls), 1)
        self.assertTrue(bool(calls[0]["dry_run"]))
        self.assertEqual(diagnostics["pre_replay_refresh_enabled"], "yes")
        self.assertEqual(diagnostics["pre_replay_refresh_dry_run"], "yes")
        self.assertEqual(diagnostics["pre_replay_refresh_ran"], "yes")
        self.assertEqual(diagnostics["pre_replay_refresh_mode"], "dry_run")
        self.assertEqual(diagnostics["bars_inserted_by_refresh"], 0)
        self.assertEqual(diagnostics["bars_updated_by_refresh"], 0)
        self.assertEqual(diagnostics["ingestion_ran_this_cycle"], "no")

    def test_global_anchor_reports_asset_class_coupling_when_equity_is_staler(self) -> None:
        tz = ZoneInfo("UTC")
        crypto_latest = datetime(2026, 6, 6, 16, 15, tzinfo=tz)
        equity_latest = datetime(2026, 5, 29, 9, 0, tzinfo=tz)
        earliest_bar = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
        rows: list[dict[str, object]] = []
        current = earliest_bar
        while current <= crypto_latest:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)
        current = earliest_bar
        while current <= equity_latest:
            rows.append(
                {
                    "source": "alpaca_market_data",
                    "asset_class": "equity",
                    "symbol": "AAPL",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _MixedCoverageLedger(_FakeLedger):
            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                selected = [
                    dict(row)
                    for row in rows
                    if str(row.get("timeframe")) == timeframe
                    and str(row.get("source")) in sources
                ]
                if symbols is not None:
                    selected = [row for row in selected if row["symbol"] in symbols]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        runner = ResearchCycleRunner(
            config=self._config(
                research_replay_timeframe="15Min",
                historical_replay_default_timeframe="15Min",
                discovery_equity_symbols=("AAPL",),
                discovery_crypto_symbols=("AVAX/USD",),
            ),
            usage_ledger=_MixedCoverageLedger(),
            source="real_heartbeat",
            parent_tick_id="heartbeat-mixed",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)

        diagnostics = runner.build_historical_replay_diagnostics(
            end_at=datetime(2026, 6, 6, 17, 0, tzinfo=tz)
        )

        self.assertEqual(
            diagnostics["latest_available_bar_per_asset_class"]["crypto"],
            "2026-06-06T16:15:00+00:00",
        )
        self.assertEqual(
            diagnostics["latest_available_bar_per_asset_class"]["equity"],
            "2026-05-29T09:00:00+00:00",
        )
        self.assertEqual(
            diagnostics["reason_latest_bars_not_used_for_replay"],
            "latest_available_bar_not_used_because_selector_uses_global_oldest_valid_anchor_across_asset_classes",
        )
        self.assertEqual(diagnostics["global_anchor_enabled"], "yes")
        self.assertEqual(
            diagnostics["global_anchor_constrained_by_asset_class"],
            "crypto",
        )
        self.assertEqual(
            diagnostics["global_anchor_constrained_by_timeframe"],
            "15Min",
        )
        self.assertEqual(
            diagnostics["selected_replay_window_end_by_timeframe"]["15Min"],
            "2026-05-30T16:15:00+00:00",
        )
        self.assertEqual(
            diagnostics["freshness_lost_to_global_anchor"],
            "0s",
        )
        self.assertEqual(diagnostics["replay_selection_mode"], "global")
        self.assertEqual(
            diagnostics["alternative_replay_selection_modes_available"],
            "yes",
        )
        self.assertEqual(
            diagnostics["simulated_asset_class_anchor_time"]["crypto"],
            "2026-05-30T16:15:00+00:00",
        )
        self.assertEqual(
            diagnostics["simulated_asset_class_and_timeframe_anchor_time"][
                "crypto/15Min"
            ],
            "2026-05-30T16:15:00+00:00",
        )
        self.assertEqual(
            diagnostics["simulated_freshness_gain_by_asset_class"]["crypto"],
            "0s",
        )
        self.assertEqual(diagnostics["strategies_helped_by_isolated_replay"], [])

    def test_write_mode_calls_existing_historical_backfill_path(self) -> None:
        original_backfill_runner = research_cycle_module.HistoricalBackfillRunner
        calls: list[dict[str, object]] = []

        class _WriteBackfillRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self, **kwargs):
                calls.append(dict(kwargs))
                return SimpleNamespace(
                    state_snapshot={
                        "historical_equity_backfill": {
                            "bars_inserted": 3,
                            "bars_updated": 1,
                            "attempted_symbols": [],
                            "success_symbols": [],
                            "failed_symbols": [],
                            "skipped_symbols": [],
                            "skip_reasons": [],
                            "provider_error_count": 0,
                            "provider_errors": [],
                        },
                        "historical_crypto_backfill": {
                            "bars_inserted": 5,
                            "bars_updated": 2,
                            "attempted_symbols": ["AVAX/USD", "SOL/USD"],
                            "success_symbols": ["AVAX/USD", "SOL/USD"],
                            "failed_symbols": [],
                            "skipped_symbols": [],
                            "skip_reasons": [],
                            "provider_error_count": 0,
                            "provider_errors": [],
                        },
                    },
                    persistence_error="",
                )

        research_cycle_module.HistoricalBackfillRunner = _WriteBackfillRunner
        try:
            runner = ResearchCycleRunner(
                config=self._config(
                    pre_replay_historical_refresh_enabled=True,
                    pre_replay_historical_refresh_dry_run=False,
                ),
                usage_ledger=_CoverageLedgerForRefresh(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-write",
            )
            refresh = runner._run_pre_replay_historical_refresh(
                as_of=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC"))
            )
        finally:
            research_cycle_module.HistoricalBackfillRunner = original_backfill_runner

        self.assertEqual(len(calls), 1)
        self.assertFalse(bool(calls[0]["dry_run"]))
        self.assertEqual(refresh["pre_replay_refresh_mode"], "write")
        self.assertEqual(refresh["bars_inserted_by_refresh"], 8)
        self.assertEqual(refresh["bars_updated_by_refresh"], 3)
        self.assertEqual(refresh["provider_error_count"], 0)
        self.assertEqual(refresh["refresh_success_symbols"]["crypto"], ["AVAX/USD", "SOL/USD"])
        self.assertEqual(
            refresh["pre_replay_refresh_safety_guard"],
            "historical_backfill_only_no_orders_no_auto_approvals",
        )

    def test_simulated_asset_class_and_timeframe_mode_can_show_fresher_crypto_15min(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        tz = ZoneInfo("UTC")
        latest_15min = datetime(2026, 6, 6, 17, 0, tzinfo=tz)
        latest_1hour = datetime(2026, 6, 5, 9, 0, tzinfo=tz)
        earliest = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
        rows: list[dict[str, object]] = []

        current = earliest
        while current <= latest_15min:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        current = earliest
        while current <= latest_1hour:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "1Hour",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(hours=1)

        class _TimeframeSplitLedger(_FakeLedger):
            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                selected = [
                    dict(row)
                    for row in rows
                    if str(row.get("timeframe")) == timeframe
                    and str(row.get("source")) in sources
                ]
                if symbols is not None:
                    selected = [row for row in selected if row["symbol"] in symbols]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        try:
            runner = ResearchCycleRunner(
                config=self._config(
                    research_replay_timeframe="15Min",
                    historical_replay_default_timeframe="1Hour",
                    discovery_crypto_symbols=("AVAX/USD",),
                ),
                usage_ledger=_TimeframeSplitLedger(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-timeframe-split",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)

            diagnostics = runner.build_historical_replay_diagnostics(
                end_at=datetime(2026, 6, 6, 17, 5, tzinfo=tz)
            )

            self.assertEqual(diagnostics["replay_selection_mode"], "global")
            self.assertEqual(
                diagnostics["selected_replay_window_end_by_timeframe"]["15Min"],
                "2026-05-30T17:00:00+00:00",
            )
            self.assertEqual(
                diagnostics["max_allowed_replay_window_end"],
                "2026-05-29T09:00:00+00:00",
            )
            self.assertEqual(
                diagnostics["simulated_asset_class_and_timeframe_anchor_time"][
                    "crypto/1Hour"
                ],
                "2026-05-29T09:00:00+00:00",
            )
            self.assertEqual(
                diagnostics["simulated_asset_class_and_timeframe_anchor_time"][
                    "crypto/15Min"
                ],
                "2026-05-30T17:00:00+00:00",
            )
            self.assertEqual(
                diagnostics["simulated_freshness_gain_by_asset_class_and_timeframe"][
                    "crypto/15Min"
                ],
                "1d8h0m0s",
            )
            self.assertIn(
                "crypto_pullback.downside_continuation_watch/downside_continuation_watch",
                diagnostics["strategies_helped_by_isolated_replay"],
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_asset_class_and_timeframe_mode_selects_buckets_and_rejects_incomplete_ones(self) -> None:
        tz = ZoneInfo("UTC")
        latest_15min = datetime(2026, 6, 6, 17, 45, tzinfo=tz)
        latest_1hour = datetime(2026, 6, 5, 9, 0, tzinfo=tz)
        latest_equity_15min = datetime(2026, 6, 3, 16, 0, tzinfo=tz)
        earliest = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
        rows: list[dict[str, object]] = []

        current = earliest
        while current <= latest_15min:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        current = earliest
        while current <= latest_1hour:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "1Hour",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(hours=1)

        current = earliest
        while current <= latest_equity_15min:
            rows.append(
                {
                    "source": "alpaca_market_data",
                    "asset_class": "equity",
                    "symbol": "AAPL",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _BucketLedger(_FakeLedger):
            def summarize_historical_bars(self, *, as_of=None):
                _ = as_of
                return {
                    "backend": self.backend,
                    "backend_detail": self.backend_detail,
                    "historical": {
                        "rows_by_source": [
                            {"source": "alpaca_crypto_data", "rows": 1},
                            {"source": "alpaca_market_data", "rows": 1},
                        ],
                        "rows_by_timeframe": [
                            {"timeframe": "15Min", "rows": 1},
                            {"timeframe": "1Hour", "rows": 1},
                        ],
                        "symbol_rows": [
                            {"symbol": "AVAX/USD"},
                            {"symbol": "AAPL"},
                        ],
                        "distinct_symbols": 2,
                    },
                    "latest": {},
                    "replay_readiness": {},
                }

            def list_historical_bars(
                self,
                *,
                timeframe: str,
                sources: list[str],
                start_at: datetime | None = None,
                end_at: datetime | None = None,
                symbols: list[str] | None = None,
            ) -> list[dict[str, object]]:
                selected = [
                    dict(row)
                    for row in rows
                    if str(row.get("timeframe")) == timeframe
                    and str(row.get("source")) in sources
                ]
                if symbols is not None:
                    selected = [row for row in selected if row["symbol"] in symbols]
                if start_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] >= start_at]
                if end_at is not None:
                    selected = [row for row in selected if row["bar_timestamp"] <= end_at]
                return selected

        ledger = _BucketLedger()
        runner = ResearchCycleRunner(
            config=self._config(
                replay_window_selection_mode="asset_class_and_timeframe",
                research_replay_timeframe="15Min",
                historical_replay_default_timeframe="1Hour",
                discovery_equity_symbols=("AAPL",),
                discovery_crypto_symbols=("AVAX/USD",),
            ),
            usage_ledger=ledger,
            source="real_heartbeat",
            parent_tick_id="heartbeat-bucketed",
        )
        runner.bars_report = research_cycle_module.HistoricalBarsStatusReport(
            config=runner.config,
            usage_ledger=ledger,
        )

        diagnostics = runner.build_historical_replay_diagnostics(
            end_at=datetime(2026, 6, 6, 18, 0, tzinfo=tz)
        )

        self.assertEqual(diagnostics["replay_selection_mode"], "asset_class_and_timeframe")
        self.assertEqual(
            diagnostics["selected_replay_window_end_by_bucket"]["crypto/15Min"],
            "2026-05-30T17:45:00+00:00",
        )
        self.assertEqual(
            diagnostics["selected_anchor_time_by_bucket"]["crypto/15Min"],
            "2026-05-30T17:45:00+00:00",
        )
        self.assertNotIn("equity/1Hour", diagnostics["selected_anchor_time_by_bucket"])
        self.assertEqual(
            diagnostics["selected_replay_window_end_by_bucket"]["crypto/1Hour"],
            "2026-05-29T09:00:00+00:00",
        )
        self.assertEqual(
            diagnostics["candidate_anchor_time_by_bucket"]["equity/15Min"],
            "2026-05-27T16:00:00+00:00",
        )
        self.assertNotIn(
            "equity/1Hour",
            diagnostics["rejected_bucket_anchor_time_by_bucket"],
        )
        self.assertEqual(
            diagnostics["freshness_gain_vs_global_by_bucket"]["crypto/15Min"],
            "3d1h45m0s",
        )
        self.assertEqual(
            diagnostics["bucket_rejection_reasons"]["equity/1Hour"],
            "no_matching_historical_rows_for_requested_symbols",
        )
        self.assertEqual(
            diagnostics["windows_rejected_by_bucket"]["equity/1Hour"],
            4,
        )
        self.assertIn(
            "crypto/15Min is using its own replay anchor",
            diagnostics["plain_english_replay_anchor_explanation"],
        )
        self.assertEqual(ledger.paper_trade_orders_recorded, 0)
        self.assertEqual(ledger.live_trade_orders_recorded, 0)
        self.assertEqual(ledger.paper_approvals_recorded, 0)
        self.assertEqual(ledger.live_approvals_recorded, 0)

    def test_write_mode_zero_bars_reports_provider_reason(self) -> None:
        original_backfill_runner = research_cycle_module.HistoricalBackfillRunner

        class _NoBarsBackfillRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self, **kwargs):
                _ = kwargs
                return SimpleNamespace(
                    state_snapshot={
                        "historical_equity_backfill": {
                            "bars_inserted": 0,
                            "bars_updated": 0,
                            "attempted_symbols": [],
                            "success_symbols": [],
                            "failed_symbols": [],
                            "skipped_symbols": [],
                            "skip_reasons": ["symbol_universe_empty"],
                            "provider_error_count": 0,
                            "provider_errors": [],
                        },
                        "historical_crypto_backfill": {
                            "bars_inserted": 0,
                            "bars_updated": 0,
                            "attempted_symbols": ["AVAX/USD", "SOL/USD"],
                            "success_symbols": [],
                            "failed_symbols": [],
                            "skipped_symbols": ["AVAX/USD", "SOL/USD"],
                            "skip_reasons": ["provider_returned_no_bars"],
                            "provider_error_count": 0,
                            "provider_errors": [],
                        },
                    },
                    persistence_error="",
                )

        research_cycle_module.HistoricalBackfillRunner = _NoBarsBackfillRunner
        try:
            runner = ResearchCycleRunner(
                config=self._config(
                    pre_replay_historical_refresh_enabled=True,
                    pre_replay_historical_refresh_dry_run=False,
                ),
                usage_ledger=_CoverageLedgerForRefresh(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-no-bars",
            )
            refresh = runner._run_pre_replay_historical_refresh(
                as_of=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC"))
            )
        finally:
            research_cycle_module.HistoricalBackfillRunner = original_backfill_runner

        self.assertEqual(refresh["bars_inserted_by_refresh"], 0)
        self.assertEqual(refresh["bars_updated_by_refresh"], 0)
        self.assertEqual(
            refresh["refresh_skip_reasons"]["crypto"],
            ["provider_returned_no_bars"],
        )
        self.assertEqual(refresh["refresh_skipped_symbols"]["crypto"], ["AVAX/USD", "SOL/USD"])

    def test_refresh_errors_do_not_crash_research_cycle_diagnostics(self) -> None:
        original_backfill_runner = research_cycle_module.HistoricalBackfillRunner

        class _FailingBackfillRunner:
            def __init__(self, *, config=None, usage_ledger=None) -> None:
                _ = (config, usage_ledger)

            def run(self, **kwargs):
                _ = kwargs
                raise RuntimeError("refresh failed")

        research_cycle_module.HistoricalBackfillRunner = _FailingBackfillRunner
        try:
            runner = ResearchCycleRunner(
                config=self._config(
                    pre_replay_historical_refresh_enabled=True,
                    pre_replay_historical_refresh_dry_run=True,
                ),
                usage_ledger=_CoverageLedgerForRefresh(),
                source="real_heartbeat",
                parent_tick_id="heartbeat-error",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            diagnostics = runner.build_historical_replay_diagnostics(
                pre_replay_refresh=runner._run_pre_replay_historical_refresh(
                    as_of=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC"))
                ),
                end_at=datetime(2026, 6, 6, 11, 2, tzinfo=ZoneInfo("UTC")),
            )
        finally:
            research_cycle_module.HistoricalBackfillRunner = original_backfill_runner

        self.assertEqual(diagnostics["pre_replay_refresh_ran"], "yes")
        self.assertEqual(diagnostics["refresh_error_count"], 1)
        self.assertIn("RuntimeError: refresh failed", diagnostics["refresh_errors"][0])
        self.assertGreaterEqual(diagnostics["replay_windows_accepted_count"], 0)

    def test_research_cycle_skips_unsupported_timeframes_and_only_records_evidence(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="real_heartbeat",
                parent_tick_id="heartbeat-1",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            run_calls: list[tuple[str, str]] = []
            runner.replay_runner = SimpleNamespace(
                run=lambda **kwargs: self._replay_run(run_calls, **kwargs)
            )
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            report = runner.run()

            self.assertEqual(report.status, "ok")
            self.assertEqual(ledger.paper_trade_orders_recorded, 0)
            self.assertEqual(ledger.live_trade_orders_recorded, 0)
            self.assertEqual(ledger.paper_approvals_recorded, 0)
            self.assertEqual(ledger.live_approvals_recorded, 0)
            self.assertEqual(len(run_calls), 4)
            self.assertTrue(all(call[0] == "15Min" for call in run_calls))
            self.assertEqual(len(ledger.decisions), 1)
            decision = ledger.decisions[0]
            self.assertEqual(decision["timeframe"], "15Min")
            self.assertEqual(decision["recommendation"], "research_only")
            self.assertIn(
                "timeframe:1Min/timeframe_not_present_in_historical_store",
                decision["blocker_reasons"],
            )
            self.assertFalse(self._any_paper_approved(ledger.promotion_updates))
            self.assertEqual(len(ledger.tick_runs), 1)
            snapshot = ledger.tick_runs[0].state_snapshot["research_cycle"]
            self.assertEqual(snapshot["timeframes_used"], ["15Min"])
            self.assertEqual(
                snapshot["timeframes_skipped"],
                [
                    {"timeframe": "1Min", "reason": "timeframe_not_present_in_historical_store"},
                    {
                        "timeframe": "1Hour",
                        "reason": "not_enough_future_data_for_checkpoint_windows",
                    },
                ],
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_research_cycle_resolves_previous_no_usable_decisions_alert_when_later_cycle_succeeds(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            ledger.attention_alerts["research_cycle_failure"] = {
                "event_id": "research_cycle_failure",
                "attention_status": "open",
            }
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="real_heartbeat",
                parent_tick_id="heartbeat-1",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            runner.replay_runner = SimpleNamespace(run=lambda **kwargs: self._replay_run([], **kwargs))
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            runner.run()

            self.assertTrue(
                any(
                    item["event_id"] == "research_cycle_failure"
                    and item["status"] == "resolved"
                    and item["reason"] == "later_real_heartbeat_cycle_recorded_usable_decisions"
                    for item in ledger.resolved_alerts
                )
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_autopilot_proof_cycle_does_not_resolve_real_heartbeat_failure_alert(self) -> None:
        original_registry_builder = research_cycle_module.build_strategy_registry
        research_cycle_module.build_strategy_registry = lambda: [_FakeStrategy()]
        try:
            ledger = _FakeLedger()
            ledger.attention_alerts["research_cycle_failure"] = {
                "event_id": "research_cycle_failure",
                "attention_status": "open",
            }
            runner = ResearchCycleRunner(
                config=self._config(),
                usage_ledger=ledger,
                source="autopilot_proof",
                parent_tick_id="autopilot-proof",
            )
            runner.bars_report = SimpleNamespace(build_report=self._bars_report)
            runner.replay_runner = SimpleNamespace(run=lambda **kwargs: self._replay_run([], **kwargs))
            runner.summary_report = SimpleNamespace(
                build_report=lambda replay_run_id: {
                    "status": "ok",
                    "replay_run_id": replay_run_id,
                    "candidates_evaluated": 12,
                }
            )
            runner.comparison_report = SimpleNamespace(
                build_report=lambda replay_limit: {"status": "ok", "replay_limit": replay_limit}
            )

            runner.run()

            self.assertEqual(ledger.resolved_alerts, [])
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder

    def test_default_behavior_unchanged_when_rolling_cursor_disabled(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 7, 9, 45, tzinfo=tz)
        earliest_bar = latest_bar - timedelta(days=20)
        rows = []
        current = earliest_bar
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _Ledger(_FakeLedger):
            def list_historical_bars(self, *, timeframe, sources, start_at=None, end_at=None, symbols=None):
                _ = (sources, start_at, end_at, symbols)
                return [dict(row) for row in rows if row["timeframe"] == timeframe]

        runner = ResearchCycleRunner(
            config=self._config(
                research_replay_timeframe="15Min",
                historical_replay_default_timeframe="15Min",
            ),
            usage_ledger=_Ledger(),
            source="real_heartbeat",
            parent_tick_id="heartbeat-default-rolling-off",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)
        diagnostics = runner.build_historical_replay_diagnostics(
            end_at=datetime(2026, 6, 7, 10, 0, tzinfo=tz)
        )

        self.assertEqual(diagnostics["rolling_replay_cursor_enabled"], "no")
        self.assertEqual(diagnostics["replay_mode"], "global_latest_window")
        self.assertEqual(diagnostics["learning_progress_this_cycle"], "yes")

    def test_rolling_mode_selects_next_unseen_replay_safe_slice_and_updates_cursor(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 7, 10, 0, tzinfo=tz)
        earliest_bar = latest_bar - timedelta(days=20)
        rows = []
        current = earliest_bar
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _Ledger(_FakeLedger):
            def __init__(self) -> None:
                super().__init__()
                self.replay_progress_cursors["crypto/15Min"] = {
                    "bucket": "crypto/15Min",
                    "last_replayed_until": datetime(2026, 5, 31, 9, 0, tzinfo=tz),
                    "last_selected_window_hash": "oldhash",
                    "last_research_cycle_id": "older-cycle",
                    "last_updated_at": datetime(2026, 6, 7, 9, 0, tzinfo=tz),
                }

            def list_historical_bars(self, *, timeframe, sources, start_at=None, end_at=None, symbols=None):
                _ = (sources, start_at, end_at, symbols)
                return [dict(row) for row in rows if row["timeframe"] == timeframe]

        ledger = _Ledger()
        runner = ResearchCycleRunner(
            config=self._config(
                research_replay_timeframe="15Min",
                historical_replay_default_timeframe="15Min",
                replay_window_selection_mode="asset_class_and_timeframe",
                rolling_replay_cursor_enabled=True,
            ),
            usage_ledger=ledger,
            source="real_heartbeat",
            parent_tick_id="heartbeat-rolling",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)
        runner.replay_runner = SimpleNamespace(
            run=lambda **kwargs: SimpleNamespace(
                tick_id="replay-1",
                state_snapshot={
                    "historical_replay_training": {"outcomes_recorded": 2},
                    "historical_replay_fitness": {"summaries_saved": 1},
                },
            )
        )
        runner.summary_report = SimpleNamespace(
            build_report=lambda replay_run_id: {"replay_run_id": replay_run_id}
        )
        runner.comparison_report = SimpleNamespace(
            build_report=lambda replay_limit: {"status": "ok", "limit": replay_limit}
        )

        report = runner.run()
        state = dict((report.state_snapshot or {}).get("research_cycle", {}) or {})

        self.assertEqual(state["rolling_replay_cursor_enabled"], "yes")
        self.assertEqual(state["replay_mode"], "rolling")
        self.assertEqual(state["unseen_replay_range_available_by_bucket"]["crypto/15Min"], "yes")
        self.assertEqual(state["learning_progress_this_cycle"], "yes")
        self.assertEqual(state["new_replay_windows_selected_count"], 1)
        self.assertGreater(state["replay_evidence_new_rows_inserted"], 0)
        self.assertIn("crypto/15Min", ledger.replay_progress_cursors)

    def test_rolling_mode_reports_no_progress_when_latest_eligible_time_has_not_moved(self) -> None:
        tz = ZoneInfo("UTC")
        latest_bar = datetime(2026, 6, 7, 9, 0, tzinfo=tz)
        earliest_bar = latest_bar - timedelta(days=20)
        rows = []
        current = earliest_bar
        while current <= latest_bar:
            rows.append(
                {
                    "source": "alpaca_crypto_data",
                    "asset_class": "crypto",
                    "symbol": "AVAX/USD",
                    "timeframe": "15Min",
                    "bar_timestamp": current,
                }
            )
            current += timedelta(minutes=15)

        class _Ledger(_FakeLedger):
            def __init__(self) -> None:
                super().__init__()
                self.replay_progress_cursors["crypto/15Min"] = {
                    "bucket": "crypto/15Min",
                    "last_replayed_until": datetime(2026, 5, 31, 9, 0, tzinfo=tz),
                    "last_selected_window_hash": "samehash",
                    "last_research_cycle_id": "older-cycle",
                    "last_updated_at": datetime(2026, 6, 7, 9, 0, tzinfo=tz),
                }

            def list_historical_bars(self, *, timeframe, sources, start_at=None, end_at=None, symbols=None):
                _ = (sources, start_at, end_at, symbols)
                return [dict(row) for row in rows if row["timeframe"] == timeframe]

        runner = ResearchCycleRunner(
            config=self._config(
                research_replay_timeframe="15Min",
                historical_replay_default_timeframe="15Min",
                replay_window_selection_mode="asset_class_and_timeframe",
                rolling_replay_cursor_enabled=True,
            ),
            usage_ledger=_Ledger(),
            source="real_heartbeat",
            parent_tick_id="heartbeat-rolling-no-progress",
        )
        runner.bars_report = SimpleNamespace(build_report=self._bars_report)
        diagnostics = runner.build_historical_replay_diagnostics(
            end_at=datetime(2026, 6, 7, 9, 0, tzinfo=tz)
        )

        self.assertEqual(diagnostics["learning_progress_this_cycle"], "no")
        self.assertEqual(
            diagnostics["reason_no_learning_progress"],
            "no_new_replay_eligible_slice",
        )

    def _replay_run(self, run_calls: list[tuple[str, str]], **kwargs):
        timeframe = kwargs["timeframe"]
        run_calls.append((timeframe, kwargs["start_at"].isoformat()))
        return SimpleNamespace(tick_id=f"{timeframe}-run-1")

    def _bars_report(self, *, timeframe: str, **_kwargs):
        if timeframe == "1Min":
            return {
                "historical": {
                    "rows_by_timeframe": [{"timeframe": "15Min"}, {"timeframe": "1Hour"}],
                    "symbol_rows": [{"symbol": "AVAX/USD"}, {"symbol": "SOL/USD"}],
                    "distinct_symbols": 2,
                },
                "replay_readiness": {
                    "requested_timeframe": "1Min",
                    "eligible_timestamps": 0,
                    "can_replay_requested_range": False,
                    "reason": "timeframe_not_present_in_historical_store",
                },
            }
        return {
            "historical": {
                "rows_by_timeframe": [{"timeframe": "15Min"}, {"timeframe": "1Hour"}],
                "symbol_rows": [{"symbol": "AVAX/USD"}, {"symbol": "SOL/USD"}],
                "distinct_symbols": 2,
            },
            "replay_readiness": {
                "requested_timeframe": timeframe,
                "eligible_timestamps": 120,
                "can_replay_requested_range": timeframe == "15Min",
                "reason": "ok" if timeframe == "15Min" else "not_enough_future_data_for_checkpoint_windows",
            },
        }

    def _config(self, **overrides):
        config = SimpleNamespace(
            research_cycle_enabled=False,
            research_cycle_singleton_dir=str(self._research_cycle_lock_dir),
            research_replay_days=5,
            research_replay_timeframe="1Min",
            historical_replay_default_timeframe="1Min",
            research_max_replay_timestamps=500,
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            pre_replay_historical_refresh_enabled=False,
            pre_replay_historical_refresh_dry_run=True,
            rolling_replay_cursor_enabled=False,
            replay_window_selection_mode="global",
            shadow_checkpoint_windows=("15m", "1h", "1d", "7d"),
            research_allowed_strategies=("crypto_pullback.downside_continuation_watch",),
            discovery_equity_symbols=(),
            discovery_crypto_symbols=("AVAX/USD", "SOL/USD"),
            include_backtest_evidence_in_paper_fitness=False,
            include_backtest_evidence_in_live_fitness=False,
            simulated_crypto_fee_bps=10.0,
            simulated_crypto_slippage_bps=8.0,
            simulated_crypto_spread_bps=12.0,
        )
        for key, value in overrides.items():
            setattr(config, key, value)
        return config

    def _any_paper_approved(self, updates: list[dict[str, object]]) -> bool:
        return any(str(item.get("stage", "")) == "paper_approved" for item in updates)


class _CoverageLedgerForRefresh(_FakeLedger):
    def list_historical_bars(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, object]]:
        _ = (start_at, end_at)
        rows = [
            {
                "source": "alpaca_crypto_data",
                "asset_class": "crypto",
                "symbol": "AVAX/USD",
                "timeframe": timeframe,
                "bar_timestamp": datetime(2026, 6, 5, 9, 45, tzinfo=ZoneInfo("UTC")),
            },
            {
                "source": "alpaca_crypto_data",
                "asset_class": "crypto",
                "symbol": "SOL/USD",
                "timeframe": timeframe,
                "bar_timestamp": datetime(2026, 6, 5, 9, 45, tzinfo=ZoneInfo("UTC")),
            },
        ]
        filtered = [row for row in rows if row["source"] in sources]
        if symbols is not None:
            filtered = [row for row in filtered if row["symbol"] in symbols]
        return filtered


class StartupDeadlockHardeningTests(unittest.TestCase):
    def test_deadlock_during_safe_startup_persistence_is_retried(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []
        diagnostics: list[dict[str, object]] = []

        class _Deadlock(Exception):
            pass

        def _attempt() -> None:
            attempts.append("attempt")
            if len(attempts) < 3:
                raise _Deadlock("deadlock detected")

        ledger._ensure_postgres_schema_once = _attempt  # type: ignore[method-assign]
        ledger._is_postgres_deadlock_error = lambda exc: isinstance(exc, _Deadlock)  # type: ignore[method-assign]
        ledger._log_startup_db_diagnostic = lambda **kwargs: diagnostics.append(kwargs)  # type: ignore[method-assign]
        original_sleep = usage_module.sleep
        usage_module.sleep = lambda _seconds: None
        try:
            ledger._ensure_postgres_schema()
        finally:
            usage_module.sleep = original_sleep

        self.assertEqual(len(attempts), 3)
        self.assertTrue(
            any(
                item.get("transaction_boundary") == "deadlock_retry_scheduled"
                and item.get("retry_count") == 1
                for item in diagnostics
            )
        )
        self.assertTrue(
            any(item.get("transaction_boundary") == "attempt_commit" for item in diagnostics)
        )

    def test_retry_stops_after_max_attempts(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []

        class _Deadlock(Exception):
            pass

        def _attempt() -> None:
            attempts.append("attempt")
            raise _Deadlock("deadlock detected")

        ledger._ensure_postgres_schema_once = _attempt  # type: ignore[method-assign]
        ledger._is_postgres_deadlock_error = lambda exc: isinstance(exc, _Deadlock)  # type: ignore[method-assign]
        ledger._log_startup_db_diagnostic = lambda **_kwargs: None  # type: ignore[method-assign]
        original_sleep = usage_module.sleep
        usage_module.sleep = lambda _seconds: None
        try:
            with self.assertRaises(_Deadlock):
                ledger._ensure_postgres_schema()
        finally:
            usage_module.sleep = original_sleep

        self.assertEqual(len(attempts), 3)

    def test_non_deadlock_database_errors_are_not_swallowed(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []

        def _attempt() -> None:
            attempts.append("attempt")
            raise ValueError("boom")

        ledger._ensure_postgres_schema_once = _attempt  # type: ignore[method-assign]
        ledger._is_postgres_deadlock_error = lambda exc: False  # type: ignore[method-assign]
        ledger._log_startup_db_diagnostic = lambda **_kwargs: None  # type: ignore[method-assign]

        with self.assertRaises(ValueError):
            ledger._ensure_postgres_schema()

        self.assertEqual(len(attempts), 1)

    def test_deadlock_during_latest_bars_read_is_retried(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []
        diagnostics: list[dict[str, object]] = []

        class _Deadlock(Exception):
            pass

        def _attempt():
            attempts.append("attempt")
            if len(attempts) < 3:
                raise _Deadlock("deadlock detected")
            return {"ok": True}

        ledger._is_postgres_deadlock_error = lambda exc: isinstance(exc, _Deadlock)  # type: ignore[method-assign]
        ledger._log_runtime_db_diagnostic = lambda **kwargs: diagnostics.append(kwargs)  # type: ignore[method-assign]
        original_sleep = usage_module.sleep
        usage_module.sleep = lambda _seconds: None
        try:
            result = ledger._run_postgres_read_with_deadlock_retry(
                startup_phase="runtime_historical_bar_read",
                runtime_phase="historical_bars_status",
                db_operation="summarize_historical_bars",
                db_table="market_data_latest_bars",
                query_purpose="historical_and_latest_bar_coverage_summary",
                transaction_boundary="transaction_open",
                operation=_attempt,
            )
        finally:
            usage_module.sleep = original_sleep

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(attempts), 3)
        self.assertTrue(
            any(
                item.get("transaction_boundary") == "deadlock_retry_scheduled"
                and item.get("db_table") == "market_data_latest_bars"
                for item in diagnostics
            )
        )

    def test_read_retry_stops_after_max_attempts(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []

        class _Deadlock(Exception):
            pass

        def _attempt():
            attempts.append("attempt")
            raise _Deadlock("deadlock detected")

        ledger._is_postgres_deadlock_error = lambda exc: isinstance(exc, _Deadlock)  # type: ignore[method-assign]
        ledger._log_runtime_db_diagnostic = lambda **_kwargs: None  # type: ignore[method-assign]
        original_sleep = usage_module.sleep
        usage_module.sleep = lambda _seconds: None
        try:
            with self.assertRaises(_Deadlock):
                ledger._run_postgres_read_with_deadlock_retry(
                    startup_phase="runtime_historical_bar_read",
                    runtime_phase="historical_bars_status",
                    db_operation="summarize_historical_bars",
                    db_table="market_data_latest_bars",
                    query_purpose="historical_and_latest_bar_coverage_summary",
                    transaction_boundary="transaction_open",
                    operation=_attempt,
                )
        finally:
            usage_module.sleep = original_sleep

        self.assertEqual(len(attempts), 3)

    def test_non_deadlock_read_errors_are_not_swallowed(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        attempts: list[str] = []

        def _attempt():
            attempts.append("attempt")
            raise ValueError("boom")

        ledger._is_postgres_deadlock_error = lambda exc: False  # type: ignore[method-assign]
        ledger._log_runtime_db_diagnostic = lambda **_kwargs: None  # type: ignore[method-assign]

        with self.assertRaises(ValueError):
            ledger._run_postgres_read_with_deadlock_retry(
                startup_phase="runtime_historical_bar_read",
                runtime_phase="historical_bars_status",
                db_operation="summarize_historical_bars",
                db_table="market_data_latest_bars",
                query_purpose="historical_and_latest_bar_coverage_summary",
                transaction_boundary="transaction_open",
                operation=_attempt,
            )

        self.assertEqual(len(attempts), 1)

    def test_broker_order_write_paths_do_not_use_read_retry_wrapper(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        ledger.backend = "postgres"
        calls: list[object] = []
        ledger._run_postgres_read_with_deadlock_retry = lambda **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
            AssertionError("read retry wrapper must not be used for broker order writes")
        )
        ledger._paper_order_row = lambda **_kwargs: {"order_id": "order-1"}  # type: ignore[method-assign]
        ledger._record_paper_trade_orders_postgres = lambda *, rows: calls.append(rows)  # type: ignore[method-assign]

        recorded = ledger.record_paper_trade_orders(
            tick_id="tick-1",
            captured_at=datetime.now().astimezone(),
            orders=[{"order_id": "order-1"}],
            broker_id="alpaca_paper",
        )

        self.assertEqual(recorded, 1)
        self.assertEqual(len(calls), 1)

    def test_overlapping_heartbeat_startup_is_detected(self) -> None:
        logger_messages: list[str] = []

        class _Logger:
            def line(self, message: str) -> None:
                logger_messages.append(message)

        runner = ControlPipelineRunner(
            steps=[],
            logger=_Logger(),
            config=SimpleNamespace(api_daily_cost_warning_usd=1.0, api_daily_cost_limit_usd=2.0),
            usage_ledger=_FakeLedger(),
        )
        with TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir) / "heartbeat.lock"
            lock_dir.mkdir()
            (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")
            runner._heartbeat_service_singleton_dir = lambda: lock_dir  # type: ignore[method-assign]
            state = runner._acquire_heartbeat_service_singleton()
            try:
                self.assertTrue(state["skip_run"])
                self.assertEqual(
                    os.environ.get("CENTAUR_EXISTING_HEARTBEAT_PROCESS_DETECTED"),
                    "yes",
                )
                self.assertTrue(
                    any(
                        "existing_heartbeat_process_detected=yes" in message
                        for message in logger_messages
                    )
                )
            finally:
                runner._release_heartbeat_service_singleton(state)

    def test_forced_one_shot_does_not_overlap_running_research_cycle(self) -> None:
        runner = ResearchCycleRunner(
            config=SimpleNamespace(),
            usage_ledger=_FakeLedger(),
            source="real_heartbeat",
            cycle_origin="forced_one_shot",
            command_source="main.py --heartbeat-autonomous-learning-once",
        )
        with TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir) / "research-cycle.lock"
            lock_dir.mkdir()
            (lock_dir / "pid").write_text(
                json.dumps(
                    {
                        "pid": "424242",
                        "process_started_at": "Wed Jun 11 12:00:00 2026",
                    }
                ),
                encoding="utf-8",
            )
            runner._research_cycle_singleton_dir = lambda: lock_dir  # type: ignore[method-assign]
            runner._pid_is_running = lambda pid_text: pid_text == "424242"  # type: ignore[method-assign]
            runner._process_started_at_signature = (  # type: ignore[method-assign]
                lambda pid: "Wed Jun 11 12:00:00 2026" if int(pid) == 424242 else ""
            )
            with self.assertRaises(research_cycle_module.ResearchCycleAlreadyRunningError):
                runner._acquire_research_cycle_singleton()
            self.assertEqual(
                os.environ.get("CENTAUR_EXISTING_RESEARCH_CYCLE_PROCESS_DETECTED"),
                "yes",
            )

    def test_research_cycle_reclaims_stale_same_pid_lock_without_metadata(self) -> None:
        runner = ResearchCycleRunner(
            config=SimpleNamespace(),
            usage_ledger=_FakeLedger(),
            source="real_heartbeat",
            cycle_origin="forced_one_shot",
            command_source="main.py --heartbeat-autonomous-learning-once",
        )
        with TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir) / "research-cycle.lock"
            lock_dir.mkdir()
            (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")
            runner._research_cycle_singleton_dir = lambda: lock_dir  # type: ignore[method-assign]
            state = runner._acquire_research_cycle_singleton()
            try:
                self.assertTrue(state["owned"])
                metadata = runner._read_lock_metadata(lock_dir / "pid")
                self.assertEqual(metadata["pid"], str(os.getpid()))
                self.assertTrue(metadata["process_started_at"])
            finally:
                runner._release_research_cycle_singleton(state)

    def test_research_cycle_reclaims_stale_same_pid_lock_with_metadata(self) -> None:
        runner = ResearchCycleRunner(
            config=SimpleNamespace(),
            usage_ledger=_FakeLedger(),
            source="real_heartbeat",
            cycle_origin="forced_one_shot",
            command_source="main.py --heartbeat-autonomous-learning-once",
        )
        with TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir) / "research-cycle.lock"
            lock_dir.mkdir()
            runner._write_lock_metadata(lock_dir / "pid")
            runner._research_cycle_singleton_dir = lambda: lock_dir  # type: ignore[method-assign]
            state = runner._acquire_research_cycle_singleton()
            try:
                self.assertTrue(state["owned"])
                metadata = runner._read_lock_metadata(lock_dir / "pid")
                self.assertEqual(metadata["pid"], str(os.getpid()))
                self.assertTrue(metadata["process_started_at"])
            finally:
                runner._release_research_cycle_singleton(state)

if __name__ == "__main__":
    unittest.main()
