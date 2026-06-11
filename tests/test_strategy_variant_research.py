from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import contextlib
import sys
import unittest

import main as main_module
from app.framework.reporting.strategy_variant_research import (
    StrategyVariantDiagnosticsReport,
    StrategyVariantResearchReport,
    StrategyVariantResearchService,
)
from app.framework.runtime.settings import load_runtime_config
from app.framework.storage.usage import UsageLedger


class _FakeVariantLedger:
    backend = "sqlite"

    def __init__(self) -> None:
        self.definitions: list[dict[str, object]] = []
        self.evaluations: list[dict[str, object]] = []

    def ensure_strategy_variant_definition(self, **kwargs):
        for row in self.definitions:
            if row["variant_id"] == kwargs["variant_id"]:
                return row
            if (
                row["base_strategy_id"] == kwargs["base_strategy_id"]
                and row["profile_id"] == kwargs["profile_id"]
                and row["timeframe"] == kwargs["timeframe"]
                and row["params_json"] == kwargs["params"]
            ):
                return row
        row = {
            "variant_id": kwargs["variant_id"],
            "base_strategy_id": kwargs["base_strategy_id"],
            "profile_id": kwargs["profile_id"],
            "timeframe": kwargs["timeframe"],
            "params_json": dict(kwargs["params"]),
            "created_at": kwargs["created_at"],
            "created_by": kwargs["created_by"],
            "generation_reason": kwargs["generation_reason"],
            "parent_variant_id": kwargs.get("parent_variant_id", ""),
            "evaluation_status": kwargs.get("evaluation_status", "pending"),
            "latest_evaluation_at": kwargs.get("latest_evaluation_at"),
            "notes": kwargs.get("notes", ""),
        }
        self.definitions.append(row)
        return row

    def update_strategy_variant_definition_status(self, **kwargs):
        for row in self.definitions:
            if row["variant_id"] == kwargs["variant_id"]:
                row["evaluation_status"] = kwargs["evaluation_status"]
                row["latest_evaluation_at"] = kwargs.get("latest_evaluation_at")
                if "notes" in kwargs:
                    row["notes"] = kwargs.get("notes")

    def record_strategy_variant_evaluation(self, **kwargs):
        row = dict(kwargs)
        self.evaluations.append(row)
        self.update_strategy_variant_definition_status(
            variant_id=row["variant_id"],
            evaluation_status=row["recommended_status"],
            latest_evaluation_at=row["evaluated_at"],
        )
        return row

    def list_strategy_variant_definitions(self, **_kwargs):
        return list(self.definitions)

    def list_strategy_variant_evaluations(self, **_kwargs):
        return list(reversed(self.evaluations))

    def list_historical_bars(self, **_kwargs):
        return []

    def summarize_historical_bar_coverage(self, **_kwargs):
        return []


class StrategyVariantResearchTests(unittest.TestCase):
    def test_cli_run_command_executes_research_only_service(self) -> None:
        original_service = main_module.StrategyVariantResearchService
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--run-strategy-variant-research",
            "--base-strategy",
            "mean_reversion.snapback",
            "--profile-id",
            "snapback",
            "--timeframe",
            "1Hour",
        ]
        captured: list[dict[str, object]] = []

        class _Service:
            def run_research(self, **kwargs):
                captured.append(dict(kwargs))
                return {
                    "base_strategy_id": "mean_reversion.snapback",
                    "profile_id": "snapback",
                    "timeframe": "15Min",
                    "baseline_variant_id": "baseline",
                    "variants_generated": 15,
                    "variants_total_including_baseline": 16,
                    "evaluations": [{"variant_id": "baseline"}],
                }

        main_module.StrategyVariantResearchService = _Service
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.StrategyVariantResearchService = original_service
            sys.argv = original_argv

        self.assertEqual(
            captured,
            [{"base_strategy_id": "mean_reversion.snapback", "profile_id": "snapback", "timeframe": "1Hour"}],
        )
        self.assertIn("Strategy Variant Research Run", stdout.getvalue())
        self.assertIn("Research-only. No paper or live approval has been changed.", stdout.getvalue())

    def test_variant_definition_persistence_and_params_immutability(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            created_at = datetime.now().astimezone()

            stored = ledger.ensure_strategy_variant_definition(
                variant_id="v1",
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="15Min",
                params={"max_movement_pct": -0.2},
                created_at=created_at,
                created_by="test",
                generation_reason="baseline",
                evaluation_status="pending",
            )
            duplicate = ledger.ensure_strategy_variant_definition(
                variant_id="v2",
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="15Min",
                params={"max_movement_pct": -0.2},
                created_at=created_at,
                created_by="test",
                generation_reason="duplicate",
                evaluation_status="pending",
            )
            ledger.update_strategy_variant_definition_status(
                variant_id="v1",
                evaluation_status="evaluated",
                latest_evaluation_at=created_at,
            )

            self.assertEqual(stored["variant_id"], "v1")
            self.assertEqual(stored["base_strategy_id"], "mean_reversion.snapback")
            self.assertEqual(stored["profile_id"], "snapback")
            self.assertEqual(stored["timeframe"], "15Min")
            self.assertEqual(stored["params_json"], {"max_movement_pct": -0.2})
            self.assertEqual(stored["evaluation_status"], "pending")
            self.assertEqual(duplicate["variant_id"], "v1")
            rows = ledger.list_strategy_variant_definitions(base_strategy_id="mean_reversion.snapback")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["params_json"], {"max_movement_pct": -0.2})
            self.assertEqual(rows[0]["evaluation_status"], "evaluated")

    def test_runtime_summary_explains_zero_symbols_with_bars_present(self) -> None:
        report = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        report.config = load_runtime_config()
        summary = report._research_runtime_summary(
            evaluations=[
                {
                    "sample_size": 0,
                    "net_return_after_costs": 0.0,
                    "win_rate": 0.0,
                    "symbols_tested": [],
                    "raw_json": {
                        "diagnostics": {
                            "bars_loaded": 4400,
                            "bars_symbols_seen": 8,
                            "eligible_symbols_after_filters": 3,
                            "data_adequacy": {"zero_decision_reason": "insufficient_crypto_history"},
                        }
                    },
                }
            ],
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="15Min",
        )
        self.assertEqual(summary["symbols_processed"], 0)
        self.assertEqual(summary["bars_read"], 4400)
        self.assertEqual(summary["coverage_symbols_seen"], 8)
        self.assertEqual(summary["eligible_symbols_after_filters"], 3)
        self.assertEqual(summary["symbols_processed_for_strategy"], 0)
        self.assertEqual(
            summary["zero_sample_reason"],
            "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay",
        )
        self.assertEqual(
            summary["history_coverage_reason"],
            "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient",
        )
        self.assertEqual(summary["no_progress_classification"], "insufficient_history")
        self.assertEqual(summary["next_required_action"], "backfill_or_resample_crypto_15Min_bars")

    def test_runtime_summary_missing_features_requests_feature_action(self) -> None:
        report = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        report.config = load_runtime_config()
        summary = report._research_runtime_summary(
            evaluations=[
                {
                    "sample_size": 0,
                    "net_return_after_costs": 0.0,
                    "win_rate": 0.0,
                    "symbols_tested": [],
                    "raw_json": {
                        "diagnostics": {
                            "bars_loaded": 4400,
                            "eligible_replay_timestamps_count": 12,
                            "observed_candidate_count": 36,
                            "feature_availability": {
                                "vwap": False,
                                "movement_pct": True,
                                "volume_ratio_20": False,
                                "atr_pct_20": False,
                            },
                            "missing_required_fields": ["vwap", "volume_ratio_20", "atr_pct_20"],
                            "data_adequacy": {"zero_decision_reason": "strategy_filters_too_strict"},
                        }
                    },
                }
            ],
            base_strategy_id="crypto_research.liquidation_wick_reclaim",
            profile_id="liquidation_wick_reclaim_confirmed",
            timeframe="15Min",
        )

        self.assertEqual(summary["no_progress_classification"], "missing_required_features")
        self.assertEqual(summary["next_required_action"], "compute_crypto_15Min_vwap_features")
        self.assertEqual(summary["missing_required_fields"], ["atr_pct_20", "volume_ratio_20", "vwap"])

    def test_runtime_summary_nonzero_samples_route_to_diagnosis(self) -> None:
        report = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        report.config = load_runtime_config()
        summary = report._research_runtime_summary(
            evaluations=[
                {
                    "variant_id": "baseline",
                    "sample_size": 4,
                    "net_return_after_costs": 0.2,
                    "win_rate": 0.5,
                    "drawdown": 0.4,
                    "symbols_tested": ["BTC/USD"],
                    "raw_json": {"diagnostics": {"bars_loaded": 4400, "data_adequacy": {"zero_decision_reason": ""}}},
                },
                {
                    "variant_id": "best",
                    "sample_size": 7,
                    "net_return_after_costs": 0.3,
                    "win_rate": 0.57,
                    "drawdown": 0.35,
                },
            ],
            base_strategy_id="crypto_research.liquidation_wick_reclaim",
            profile_id="liquidation_wick_reclaim_confirmed",
            timeframe="15Min",
        )

        self.assertEqual(summary["no_progress_classification"], "variant_research_not_consumed")
        self.assertEqual(summary["next_required_action"], "send_to_diagnosis")
        self.assertIn("--diagnose-next-best-strategy", summary["next_recommended_command"])

    def test_crypto_research_dip_rebound_safe_variable_params_are_supported(self) -> None:
        service = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        service.config = load_runtime_config()
        service.usage_ledger = _FakeVariantLedger()
        service.logger = object()

        params = service.safe_variable_params(
            base_strategy_id="crypto_research.dip_rebound",
            profile_id="dip_rebound",
            timeframe="15Min",
        )

        names = {item["name"] for item in params}
        self.assertIn("min_pullback_pct", names)
        self.assertIn("max_pullback_pct", names)
        self.assertIn("holding_window_minutes", names)
        self.assertNotIn("min_expected_net_move_pct", names)

    def test_generated_research_candidate_profile_inherits_supported_baseline(self) -> None:
        service = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        service.config = load_runtime_config()
        service.logger = object()
        ledger = _FakeVariantLedger()
        service.usage_ledger = ledger
        ledger.ensure_strategy_variant_definition(
            variant_id="generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout_wide_signal",
            timeframe="15Min",
            params={
                "min_movement_pct": 0.08,
                "min_discovery_score": 2.5,
                "min_volume_ratio": 1.1,
                "min_atr_pct": 0.18,
                "holding_window_minutes": 90,
                "__research_candidate_metadata__": {
                    "source_profile_id": "range_breakout",
                    "label": "Crypto Research Range Breakout Wide Signal",
                },
            },
            created_at=datetime.now().astimezone(),
            created_by="test",
            generation_reason="research_expansion_candidate",
            evaluation_status="pending",
        )

        profile = service._resolve_profile(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout_wide_signal",
            timeframe="15Min",
        )

        self.assertEqual(profile.profile_id, "range_breakout_wide_signal")
        self.assertEqual(profile.label, "Crypto Research Range Breakout Wide Signal")
        self.assertEqual(profile.parameters["min_movement_pct"], 0.08)
        self.assertEqual(profile.parameters["min_volume_ratio"], 1.1)
        self.assertEqual(profile.holding_window_minutes, 90)

    def test_generated_candidate_id_is_recovered_from_persisted_definition(self) -> None:
        service = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        service.config = load_runtime_config()
        service.logger = object()
        ledger = _FakeVariantLedger()
        service.usage_ledger = ledger
        ledger.ensure_strategy_variant_definition(
            variant_id="generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout_wide_signal",
            timeframe="15Min",
            params={
                "__research_candidate_metadata__": {"source_profile_id": "range_breakout"},
            },
            created_at=datetime.now().astimezone(),
            created_by="test",
            generation_reason="research_expansion_candidate",
            evaluation_status="pending",
        )

        candidate_id = service._generated_candidate_id(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout_wide_signal",
            timeframe="15Min",
        )

        self.assertEqual(
            candidate_id,
            "generated.crypto_research.range_breakout.range_breakout_wide_signal.15Min.v1",
        )

    def test_generated_candidate_runtime_result_updates_definition_status(self) -> None:
        service = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        service.config = load_runtime_config()
        service.logger = object()
        ledger = _FakeVariantLedger()
        service.usage_ledger = ledger
        created_at = datetime.now().astimezone()
        ledger.ensure_strategy_variant_definition(
            variant_id="generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout_compression_release",
            timeframe="1Hour",
            params={
                "__research_candidate_metadata__": {"source_profile_id": "range_breakout"},
            },
            created_at=created_at,
            created_by="test",
            generation_reason="research_expansion_candidate",
            evaluation_status="pending",
        )

        update = service._persist_generated_candidate_execution_result(
            candidate_id="generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
            runtime_summary={
                "variants_evaluated": 16,
                "baseline_sample_size": 0,
                "best_variant_sample_size": 0,
                "runtime_status": "completed",
                "runtime_blocker": "insufficient_crypto_history",
                "zero_sample_reason": "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay",
            },
            variants_generated=15,
            evaluated_rows=[{"evaluated_at": created_at}],
            snapshot_before={"lifecycle_status": "generated_not_evaluated", "evaluation_status": "pending"},
        )

        stored = ledger.list_strategy_variant_definitions()[0]
        notes = json.loads(str(stored.get("notes", "") or "{}"))
        self.assertEqual(update["lifecycle_status_after"], "variant_research_completed")
        self.assertEqual(update["evaluation_status_after"], "evaluated_no_samples")
        self.assertEqual(update["research_status_after"], "insufficient_history_after_variant_research")
        self.assertEqual(stored["evaluation_status"], "evaluated_no_samples")
        self.assertEqual(notes["runtime_blocker"], "insufficient_crypto_history")
        self.assertEqual(notes["generated_candidate_evidence_at"], created_at.isoformat())

    def test_crypto_research_dip_rebound_variant_specs_are_supported(self) -> None:
        service = StrategyVariantResearchService.__new__(StrategyVariantResearchService)
        service.config = load_runtime_config()
        service.usage_ledger = _FakeVariantLedger()
        service.logger = object()
        profile = service._resolve_profile(
            base_strategy_id="crypto_research.dip_rebound",
            profile_id="dip_rebound",
            timeframe="15Min",
        )

        specs = service._variant_specs_for_profile(profile)
        spec_names = {name for name, _changes in specs}

        self.assertIn("shallower_entry_020", spec_names)
        self.assertIn("deeper_max_pullback_300", spec_names)
        self.assertIn("wider_stop_115_tp_220", spec_names)
        self.assertIn("tighter_stop_090_tp_180", spec_names)
        self.assertIn("holding_window_1440", spec_names)

    def test_evaluation_persistence_stores_separate_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            created_at = datetime.now().astimezone()
            ledger.ensure_strategy_variant_definition(
                variant_id="v1",
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="15Min",
                params={"max_movement_pct": -0.2},
                created_at=created_at,
                created_by="test",
                generation_reason="baseline",
            )

            for idx in range(2):
                ledger.record_strategy_variant_evaluation(
                    evaluation_id=f"e{idx}",
                    variant_id="v1",
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe="15Min",
                    replay_id=f"r{idx}",
                    dataset_id="bars",
                    asset_class="equity",
                    symbols_tested=["AAPL", "MSFT"],
                    sample_size=5 + idx,
                    gross_return=1.0,
                    net_return_after_costs=0.8,
                    fees_cost=0.1,
                    spread_cost=0.05,
                    slippage_cost=0.05,
                    win_rate=0.6,
                    drawdown=0.3,
                    baseline_variant_id="v1",
                    baseline_strategy_key="mean_reversion.snapback/snapback/15Min",
                    baseline_net_return_after_costs=0.8,
                    baseline_win_rate=0.6,
                    beats_baseline=False,
                    beats_thresholds=False,
                    recommended_status="evaluated",
                    evaluated_at=created_at,
                )
            rows = ledger.list_strategy_variant_evaluations(variant_id="v1")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["variant_id"], "v1")
            self.assertEqual(rows[0]["symbols_tested"], ["AAPL", "MSFT"])
            self.assertIn("net_return_after_costs", rows[0])
            self.assertIn("win_rate", rows[0])
            self.assertIn("sample_size", rows[0])
            self.assertIn("fees_cost", rows[0])

    def test_evaluations_are_stored_separately_by_timeframe(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            created_at = datetime.now().astimezone()
            for timeframe in ("15Min", "1Hour"):
                ledger.ensure_strategy_variant_definition(
                    variant_id=f"baseline-{timeframe}",
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe=timeframe,
                    params={"max_movement_pct": -0.2},
                    created_at=created_at,
                    created_by="test",
                    generation_reason="baseline_profile",
                )
                ledger.record_strategy_variant_evaluation(
                    evaluation_id=f"eval-{timeframe}",
                    variant_id=f"baseline-{timeframe}",
                    base_strategy_id="mean_reversion.snapback",
                    profile_id="snapback",
                    timeframe=timeframe,
                    replay_id=f"replay-{timeframe}",
                    dataset_id=f"historical_equity_bars:{timeframe}:5d",
                    asset_class="equity",
                    symbols_tested=["AAPL"],
                    sample_size=5,
                    gross_return=1.0,
                    net_return_after_costs=0.8 if timeframe == "15Min" else 1.1,
                    fees_cost=0.1,
                    spread_cost=0.05,
                    slippage_cost=0.05,
                    win_rate=0.6,
                    drawdown=0.3,
                    baseline_variant_id=f"baseline-{timeframe}",
                    baseline_strategy_key=f"mean_reversion.snapback/snapback/{timeframe}",
                    baseline_net_return_after_costs=0.8,
                    baseline_win_rate=0.6,
                    beats_baseline=False,
                    beats_thresholds=False,
                    recommended_status="evaluated",
                    evaluated_at=created_at,
                )
            rows_15 = ledger.list_strategy_variant_evaluations(
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="15Min",
            )
            rows_1h = ledger.list_strategy_variant_evaluations(
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="1Hour",
            )
            self.assertEqual(len(rows_15), 1)
            self.assertEqual(len(rows_1h), 1)
            self.assertEqual(rows_15[0]["timeframe"], "15Min")
            self.assertEqual(rows_1h[0]["timeframe"], "1Hour")

    def test_crypto_momentum_safe_params_and_history_source_are_strategy_aware(self) -> None:
        captured = {}

        class _Ledger(_FakeVariantLedger):
            def list_historical_bars(self, **kwargs):
                captured.update(kwargs)
                return []

        config = _service_config()
        service = StrategyVariantResearchService(config=config, usage_ledger=_Ledger())
        params = service.safe_variable_params(
            base_strategy_id="crypto_momentum.trend",
            profile_id="trend",
            timeframe="15Min",
        )
        names = {item["name"] for item in params}
        self.assertIn("min_movement_pct", names)
        self.assertNotIn("min_expected_net_move_pct", names)
        profile = service._resolve_profile(
            base_strategy_id="crypto_momentum.trend",
            profile_id="trend",
            timeframe="15Min",
        )

    def test_bounded_diagnosis_limits_symbols_from_coverage(self) -> None:
        captured: dict[str, object] = {}
        coverage_calls: list[dict[str, object]] = []

        class _Ledger(_FakeVariantLedger):
            def summarize_historical_bar_coverage(self, **kwargs):
                coverage_calls.append(dict(kwargs))
                now = datetime.now().astimezone()
                return [
                    {
                        "symbol": "MSFT",
                        "row_count": 120,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now,
                    },
                    {
                        "symbol": "AAPL",
                        "row_count": 110,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now - timedelta(minutes=15),
                    },
                    {
                        "symbol": "TSLA",
                        "row_count": 90,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now - timedelta(minutes=30),
                    },
                ]

            def list_historical_bars(self, **kwargs):
                captured.update(kwargs)
                return []

        config = _service_config()
        config.diagnosis_replay_symbol_limit = 2
        service = StrategyVariantResearchService(config=config, usage_ledger=_Ledger())
        profile = service._resolve_profile(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )

        service._load_variant_history(
            profile=profile,
            timeframe="15Min",
            bounded_diagnosis=True,
        )

        self.assertEqual(captured["symbols"], ["MSFT", "AAPL"])
        self.assertEqual(coverage_calls[0]["asset_class"], "equity")

    def test_crypto_targeted_history_uses_crypto_coverage_and_bounded_bar_limits(self) -> None:
        captured: dict[str, object] = {}
        coverage_calls: list[dict[str, object]] = []

        class _Ledger(_FakeVariantLedger):
            def summarize_historical_bar_coverage(self, **kwargs):
                coverage_calls.append(dict(kwargs))
                now = datetime.now().astimezone()
                return [
                    {
                        "symbol": "SOL/USD",
                        "row_count": 800,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now,
                    },
                    {
                        "symbol": "BTC/USD",
                        "row_count": 900,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now - timedelta(minutes=15),
                    },
                ]

            def list_historical_bars(self, **kwargs):
                captured.update(kwargs)
                return []

        config = _service_config()
        config.strategy_variant_research_symbol_limit = 1
        config.strategy_variant_research_max_bars_per_symbol = 50
        service = StrategyVariantResearchService(config=config, usage_ledger=_Ledger())
        profile = service._resolve_profile(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="15Min",
        )

        service._load_variant_history(profile=profile, timeframe="15Min")

        self.assertEqual(coverage_calls[0]["asset_class"], "crypto")
        self.assertEqual(captured["symbols"], ["SOL/USD"])
        self.assertGreater(int(captured["per_symbol_limit"]), 50)
        self.assertEqual(captured["limit"], captured["per_symbol_limit"])

    def test_crypto_research_history_budget_expands_to_full_1hour_replay_window(self) -> None:
        captured: dict[str, object] = {}

        class _Ledger(_FakeVariantLedger):
            def summarize_historical_bar_coverage(self, **_kwargs):
                now = datetime.now().astimezone()
                return [
                    {
                        "symbol": "BTC/USD",
                        "row_count": 9000,
                        "earliest_bar_timestamp": now - timedelta(days=365),
                        "latest_bar_timestamp": now,
                    }
                ]

            def list_historical_bars(self, **kwargs):
                captured.update(kwargs)
                return []

        config = _service_config()
        config.historical_replay_default_days = 365
        config.strategy_variant_research_symbol_limit = 1
        config.strategy_variant_research_max_bars_per_symbol = 400
        service = StrategyVariantResearchService(config=config, usage_ledger=_Ledger())
        profile = service._resolve_profile(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="1Hour",
        )

        history = service._load_variant_history(profile=profile, timeframe="1Hour")

        self.assertGreater(int(captured["per_symbol_limit"]), 400)
        self.assertEqual(captured["limit"], captured["per_symbol_limit"])
        self.assertEqual(history["required_bars_per_symbol"], int(captured["per_symbol_limit"]))
        self.assertEqual(history["configured_max_bars_per_symbol"], 400)

    def test_run_research_reuses_one_history_load_across_variants(self) -> None:
        class _Ledger(_FakeVariantLedger):
            def __init__(self) -> None:
                super().__init__()
                self.list_calls = 0

            def summarize_historical_bar_coverage(self, **_kwargs):
                now = datetime.now().astimezone()
                return [
                    {
                        "symbol": "AAPL",
                        "row_count": 100,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now,
                    }
                ]

            def list_historical_bars(self, **_kwargs):
                self.list_calls += 1
                return []

        ledger = _Ledger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        result = service.run_research(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            timeframe="15Min",
        )

        self.assertEqual(ledger.list_calls, 1)
        self.assertEqual(result["runtime_status"], "completed")

    def test_runtime_blocked_history_returns_safe_data_adequacy(self) -> None:
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=_FakeVariantLedger())
        profile = service._resolve_profile(
            base_strategy_id="liquidity_probe.steady_flow",
            profile_id="steady_flow",
            timeframe="15Min",
        )

        history = service._runtime_blocked_history(
            profile=profile,
            timeframe="15Min",
            requested_start_at=datetime.now().astimezone() - timedelta(days=1),
            requested_end_at=datetime.now().astimezone(),
            requested_symbols=["AAPL"],
            runtime_blocker="historical_bar_read_timeout",
        )
        adequacy = service._build_data_adequacy(
            profile=profile,
            timeframe="15Min",
            history=history,
            generated_signal_count=0,
            generated_proposal_count=0,
            usable_decision_count=0,
        )

        self.assertEqual(adequacy["zero_decision_reason"], "historical_bar_read_timeout")

    def test_runtime_blocked_run_returns_specific_next_action_for_range_breakout(self) -> None:
        class _Ledger(_FakeVariantLedger):
            def summarize_historical_bar_coverage(self, **_kwargs):
                now = datetime.now().astimezone()
                return [
                    {
                        "symbol": "BTC/USD",
                        "row_count": 500,
                        "earliest_bar_timestamp": now - timedelta(days=5),
                        "latest_bar_timestamp": now,
                    }
                ]

            def list_historical_bars(self, **_kwargs):
                raise TimeoutError("canceling statement due to lock timeout")

        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=_Ledger())
        result = service.run_research(
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="15Min",
        )

        self.assertEqual(result["runtime_status"], "runtime_blocked")
        self.assertEqual(result["runtime_blocker"], "historical_bar_read_timeout")
        self.assertEqual(result["next_required_action"], "precompute_specific_range_breakout_15Min_replay_cache")

    def test_resolve_profile_accepts_1hour_for_research_only_replay(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        profile = service._resolve_profile(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            timeframe="1Hour",
        )
        self.assertEqual(profile.strategy_id, "mean_reversion.snapback")
        self.assertEqual(profile.profile_id, "snapback")

    def test_resolve_profile_accepts_crypto_pullback_family_alias(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        profile = service._resolve_profile(
            base_strategy_id="crypto_pullback",
            profile_id="downside_reversal_watch",
            timeframe="1Day",
        )
        self.assertEqual(profile.family, "crypto_pullback")
        self.assertEqual(profile.strategy_id, "crypto_pullback.downside_reversal_watch")
        self.assertEqual(profile.profile_id, "downside_reversal_watch")

    def test_variant_generation_is_bounded_and_deduplicated(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        variants = service._ensure_variants(
            profile=service._resolve_profile(
                base_strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                timeframe="15Min",
            ),
            persisted_base_strategy_id="mean_reversion.snapback",
            timeframe="15Min",
            created_at=datetime.now().astimezone(),
            created_by="test",
        )
        self.assertEqual(len(variants), 16)
        self.assertTrue(all(item["base_strategy_id"] == "mean_reversion.snapback" for item in variants))
        params = [str(item["params_json"]) for item in variants]
        self.assertEqual(len(params), len(set(params)))
        self.assertNotIn("min_expected_net_move_pct", variants[0]["params_json"])
        self.assertEqual(
            len(
                [
                    item
                    for item in variants
                    if float(item["params_json"].get("min_expected_net_move_pct", 0.0) or 0.0) > 0.0
                ]
            ),
            6,
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in variants
                    if int(item["params_json"].get("holding_window_minutes", 0) or 0) > 0
                ]
            ),
            3,
        )

    def test_run_research_persists_baseline_variants_and_evaluations(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)

        def _fake_evaluate_variant(*, profile, variant, persisted_base_strategy_id=None, timeframe, replay_id, **_kwargs):
            _ = (profile, timeframe, replay_id)
            score = 12.5 if variant["generation_reason"] == "deeper_pullback_020" else 3.0
            win_rate = 0.58 if variant["generation_reason"] == "deeper_pullback_020" else 0.5
            sample_size = 60 if variant["generation_reason"] == "deeper_pullback_020" else 55
            return {
                "variant_id": variant["variant_id"],
                "base_strategy_id": persisted_base_strategy_id or variant["base_strategy_id"],
                "profile_id": variant["profile_id"],
                "timeframe": variant["timeframe"],
                "replay_id": replay_id,
                "dataset_id": "bars",
                "asset_class": "equity",
                "symbols_tested": ["AAPL", "MSFT"],
                "sample_size": sample_size,
                "gross_return": score + 0.2,
                "net_return_after_costs": score,
                "gross_positive_net_negative_count": 4,
                "average_winner": 1.2,
                "average_loser": -0.8,
                "fees_cost": 0.1,
                "spread_cost": 0.05,
                "slippage_cost": 0.05,
                "win_rate": win_rate,
                "drawdown": 2.0,
                "evaluated_at": datetime.now().astimezone(),
                "raw": {
                    "variant_id": variant["variant_id"],
                    "diagnostics": {
                        "params_hash": service._params_hash(dict(variant["params_json"])),
                        "generated_signal_count": sample_size,
                        "generated_proposal_count": sample_size,
                        "usable_decision_count": sample_size,
                        "rejected_by_param_filter_count": 0,
                        "decision_set_hash": f"hash-{variant['variant_id']}",
                        "symbols_with_decisions": ["AAPL", "MSFT"],
                        "first_decision_fingerprint": "first",
                    },
                    "target_hit_count": 10,
                    "stop_hit_count": 20,
                    "time_exit_count": 30,
                },
            }

        service._evaluate_variant = _fake_evaluate_variant
        result = service.run_research(base_strategy_id="mean_reversion.snapback", profile_id="snapback")

        self.assertEqual(result["baseline_variant_id"], ledger.definitions[0]["variant_id"])
        self.assertEqual(len(ledger.definitions), 16)
        self.assertEqual(len(ledger.evaluations), 16)
        self.assertEqual(ledger.definitions[0]["generation_reason"], "baseline_profile")
        self.assertIn(
            "paper_candidate_requires_manual_approval",
            {str(item["recommended_status"]) for item in ledger.evaluations},
        )
        self.assertIn("diagnostics", ledger.evaluations[0]["raw"])
        self.assertIn("params_hash", ledger.evaluations[0]["raw"]["diagnostics"])

    def test_crypto_pullback_1day_run_is_supported_and_persists_family_key(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)

        def _fake_evaluate_variant(*, profile, variant, persisted_base_strategy_id, timeframe, replay_id, **_kwargs):
            _ = (profile, timeframe, replay_id)
            return {
                "variant_id": variant["variant_id"],
                "base_strategy_id": persisted_base_strategy_id,
                "profile_id": variant["profile_id"],
                "timeframe": variant["timeframe"],
                "replay_id": replay_id,
                "dataset_id": "historical_crypto_bars:1Day:5d",
                "asset_class": "crypto",
                "symbols_tested": ["BTC/USD", "ETH/USD"],
                "sample_size": 0,
                "gross_return": 0.0,
                "net_return_after_costs": 0.0,
                "gross_positive_net_negative_count": 0,
                "average_winner": 0.0,
                "average_loser": 0.0,
                "fees_cost": 0.0,
                "spread_cost": 0.0,
                "slippage_cost": 0.0,
                "win_rate": 0.0,
                "drawdown": None,
                "evaluated_at": datetime.now().astimezone(),
                "raw": {
                    "variant_id": variant["variant_id"],
                    "diagnostics": {
                        "params_hash": service._params_hash(dict(variant["params_json"])),
                        "generated_signal_count": 0,
                        "generated_proposal_count": 0,
                        "usable_decision_count": 0,
                        "rejected_by_param_filter_count": 3,
                        "decision_set_hash": "",
                        "symbols_with_decisions": [],
                        "first_decision_fingerprint": "",
                        "data_adequacy": {
                            "dataset_id": "historical_crypto_bars:1Day:5d",
                            "timeframe": "1Day",
                            "days_covered": 2.0,
                            "symbols_covered": ["BTC/USD", "ETH/USD"],
                            "total_bars": 8,
                            "eligible_signal_count": 0,
                            "generated_proposal_count": 0,
                            "usable_decision_count": 0,
                            "zero_decision_reason": "insufficient_crypto_history",
                        },
                    },
                },
            }

        service._evaluate_variant = _fake_evaluate_variant
        result = service.run_research(
            base_strategy_id="crypto_pullback",
            profile_id="downside_reversal_watch",
            timeframe="1Day",
        )

        self.assertEqual(result["base_strategy_id"], "crypto_pullback")
        self.assertTrue(ledger.evaluations)
        self.assertTrue(all(row["base_strategy_id"] == "crypto_pullback" for row in ledger.evaluations))
        self.assertEqual(
            ledger.evaluations[0]["baseline_strategy_key"],
            "crypto_pullback/downside_reversal_watch/1Day",
        )

    def test_build_data_adequacy_populates_zero_decision_reason(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        profile = service._resolve_profile(
            base_strategy_id="crypto_pullback",
            profile_id="downside_reversal_watch",
            timeframe="1Day",
        )
        adequacy = service._build_data_adequacy(
            profile=profile,
            timeframe="1Day",
            history={
                "dataset_id": "historical_crypto_bars:1Day:5d",
                "requested_start_at": datetime(2026, 6, 1).astimezone(),
                "requested_end_at": datetime(2026, 6, 6).astimezone(),
                "earliest_bar_timestamp": datetime(2026, 6, 4).astimezone(),
                "latest_bar_timestamp": datetime(2026, 6, 5).astimezone(),
                "eligible_timestamps": [datetime(2026, 6, 5).astimezone()],
                "total_bars": 4,
                "symbols_covered": ["BTC/USD"],
                "requested_symbols": ["BTC/USD", "ETH/USD"],
            },
            generated_signal_count=0,
            generated_proposal_count=0,
            usable_decision_count=0,
        )
        self.assertEqual(adequacy["dataset_id"], "historical_crypto_bars:1Day:5d")
        self.assertEqual(adequacy["zero_decision_reason"], "insufficient_crypto_history")

    def test_rerun_appends_evaluations_without_overwriting_params(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)

        def _fake_evaluate_variant(*, profile, variant, persisted_base_strategy_id=None, timeframe, replay_id, **_kwargs):
            _ = (profile, timeframe, replay_id)
            return {
                "variant_id": variant["variant_id"],
                "base_strategy_id": persisted_base_strategy_id or variant["base_strategy_id"],
                "profile_id": variant["profile_id"],
                "timeframe": variant["timeframe"],
                "replay_id": replay_id,
                "dataset_id": "bars",
                "asset_class": "equity",
                "symbols_tested": ["AAPL"],
                "sample_size": 55,
                "gross_return": 3.2,
                "net_return_after_costs": 3.0,
                "gross_positive_net_negative_count": 4,
                "average_winner": 1.2,
                "average_loser": -0.8,
                "fees_cost": 0.1,
                "spread_cost": 0.05,
                "slippage_cost": 0.05,
                "win_rate": 0.5,
                "drawdown": 2.1,
                "evaluated_at": datetime.now().astimezone(),
                "raw": {"variant_id": variant["variant_id"]},
            }

        service._evaluate_variant = _fake_evaluate_variant
        service.run_research(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        first_params = {row["variant_id"]: dict(row["params_json"]) for row in ledger.definitions}
        service.run_research(base_strategy_id="mean_reversion.snapback", profile_id="snapback")

        self.assertEqual(len(ledger.definitions), 16)
        self.assertEqual(len(ledger.evaluations), 32)
        self.assertEqual(first_params, {row["variant_id"]: dict(row["params_json"]) for row in ledger.definitions})

    def test_baseline_comparison_and_safety_recommendations(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        baseline_variant = {
            "variant_id": "baseline",
            "base_strategy_id": "mean_reversion.snapback",
            "profile_id": "snapback",
            "timeframe": "15Min",
        }
        baseline = {
            "variant_id": "baseline",
            "net_return_after_costs": 3.2,
            "win_rate": 0.56,
        }
        worse = service._finalize_evaluation(
            evaluation={
                "variant_id": "worse",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "replay_id": "r1",
                "sample_size": 80,
                "net_return_after_costs": 1.0,
                "win_rate": 0.58,
                "evaluated_at": datetime.now().astimezone(),
            },
            variant=baseline_variant | {"generation_reason": "grid"},
            baseline=baseline,
        )
        beats_threshold_only = service._finalize_evaluation(
            evaluation={
                "variant_id": "threshold_only",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "replay_id": "r2",
                "sample_size": 80,
                "net_return_after_costs": 12.0,
                "win_rate": 0.60,
                "evaluated_at": datetime.now().astimezone(),
            },
            variant=baseline_variant | {"generation_reason": "grid"},
            baseline={**baseline, "net_return_after_costs": 13.0, "win_rate": 0.60},
        )
        winner = service._finalize_evaluation(
            evaluation={
                "variant_id": "winner",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "replay_id": "r3",
                "sample_size": 80,
                "net_return_after_costs": 14.0,
                "win_rate": 0.61,
                "evaluated_at": datetime.now().astimezone(),
            },
            variant=baseline_variant | {"generation_reason": "grid"},
            baseline=baseline,
        )
        self.assertEqual(worse["recommended_status"], "evaluated")
        self.assertEqual(beats_threshold_only["recommended_status"], "evaluated")
        self.assertEqual(winner["recommended_status"], "paper_candidate_requires_manual_approval")
        self.assertNotEqual(winner["recommended_status"], "live_candidate")
        self.assertNotEqual(winner["recommended_status"], "approved_for_paper")

    def test_report_renders_read_only_safety_statement(self) -> None:
        ledger = _FakeVariantLedger()
        now = datetime.now().astimezone()
        ledger.definitions = [
            {
                "variant_id": "baseline",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {"max_movement_pct": -0.18},
                "generation_reason": "baseline_profile",
            },
            {
                "variant_id": "winner",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {"max_movement_pct": -0.2, "min_expected_net_move_pct": 0.5, "holding_window_minutes": 1440},
                "generation_reason": "deeper_pullback_020",
            },
        ]
        ledger.evaluations = [
            {
                "variant_id": "winner",
                "sample_size": 90,
                "gross_return": 14.4,
                "net_return_after_costs": 14.0,
                "average_winner": 1.4,
                "average_loser": -0.7,
                "win_rate": 0.61,
                "drawdown": 2.5,
                "gross_positive_net_negative_count": 2,
                "symbols_tested": ["AAPL"],
                "raw_json": {"target_hit_count": 10, "stop_hit_count": 4, "time_exit_count": 2},
                "beats_baseline": True,
                "beats_thresholds": True,
                "recommended_status": "paper_candidate_requires_manual_approval",
                "evaluated_at": now,
            },
            {
                "variant_id": "baseline",
                "sample_size": 74,
                "gross_return": 3.5,
                "net_return_after_costs": 3.168,
                "average_winner": 1.1,
                "average_loser": -0.9,
                "win_rate": 0.4583,
                "drawdown": 3.2,
                "gross_positive_net_negative_count": 8,
                "symbols_tested": ["AAPL"],
                "raw_json": {"target_hit_count": 5, "stop_hit_count": 8, "time_exit_count": 9},
                "beats_baseline": False,
                "beats_thresholds": False,
                "recommended_status": "evaluated",
                "evaluated_at": now,
            },
        ]
        report = StrategyVariantResearchReport(config=_service_config(), usage_ledger=ledger)
        rendered = report.render(base_strategy_id="mean_reversion.snapback")
        self.assertIn("Strategy Variant Research Report", rendered)
        self.assertIn("baseline_metrics=", rendered)
        self.assertIn("recommended_status=paper_candidate_requires_manual_approval", rendered)
        self.assertIn("gross_positive_net_negative=", rendered)
        self.assertIn("min_expected_net_move_pct", rendered)
        self.assertIn("holding_window_minutes", rendered)
        self.assertIn("Research-only. No paper or live approval has been changed.", rendered)

    def test_profile_from_variant_loads_expected_move_param_without_mutating_baseline(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        baseline = service._resolve_profile(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            timeframe="15Min",
        )
        variant = {
            "params_json": {
                "max_movement_pct": -0.18,
                "min_discovery_score": 4.0,
                "min_trade_count": 40,
                "min_expected_net_move_pct": 0.5,
                "stop_loss_pct": baseline.stop_loss_pct,
                "target_multiple": baseline.target_multiple,
            }
        }

        loaded = service._profile_from_variant(profile=baseline, variant=variant)

        self.assertEqual(loaded.parameters["min_expected_net_move_pct"], 0.5)
        self.assertEqual(baseline.parameters["min_expected_net_move_pct"], 0.0)

    def test_profile_from_variant_loads_holding_window_override(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        baseline = service._resolve_profile(
            base_strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            timeframe="15Min",
        )
        variant = {
            "params_json": {
                "max_movement_pct": -0.18,
                "min_discovery_score": 4.0,
                "min_trade_count": 40,
                "holding_window_minutes": 1440,
                "stop_loss_pct": baseline.stop_loss_pct,
                "target_multiple": baseline.target_multiple,
            }
        }

        loaded = service._profile_from_variant(profile=baseline, variant=variant)

        self.assertEqual(loaded.holding_window_minutes, 1440)
        self.assertEqual(loaded.holding_window_code, "1d")
        self.assertEqual(baseline.holding_window_minutes, 60)

    def test_report_population_after_run_uses_persisted_rows(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)

        def _fake_evaluate_variant(*, profile, variant, persisted_base_strategy_id=None, timeframe, replay_id, **_kwargs):
            _ = (profile, timeframe, replay_id)
            return {
                "variant_id": variant["variant_id"],
                "base_strategy_id": persisted_base_strategy_id or variant["base_strategy_id"],
                "profile_id": variant["profile_id"],
                "timeframe": variant["timeframe"],
                "replay_id": replay_id,
                "dataset_id": "bars",
                "asset_class": "equity",
                "symbols_tested": ["AAPL", "MSFT"],
                "sample_size": 55,
                "gross_return": 3.2,
                "net_return_after_costs": 3.0,
                "gross_positive_net_negative_count": 4,
                "average_winner": 1.2,
                "average_loser": -0.8,
                "fees_cost": 0.1,
                "spread_cost": 0.05,
                "slippage_cost": 0.05,
                "win_rate": 0.5,
                "drawdown": 2.1,
                "evaluated_at": datetime.now().astimezone(),
                "raw": {
                    "variant_id": variant["variant_id"],
                    "target_hit_count": 10,
                    "stop_hit_count": 20,
                    "time_exit_count": 30,
                },
            }

        service._evaluate_variant = _fake_evaluate_variant
        service.run_research(base_strategy_id="mean_reversion.snapback", profile_id="snapback")

        report = StrategyVariantResearchReport(config=_service_config(), usage_ledger=ledger)
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        self.assertTrue(built["baseline"]["variant_id"])
        self.assertGreater(built["variants_generated"], 0)
        self.assertGreater(built["variants_evaluated"], 0)
        self.assertTrue(built["variants"])
        self.assertNotIn("min_expected_net_move_pct", built["baseline"]["params_json"])
        self.assertIn("gross_positive_net_negative_count", built["variants"][0])
        self.assertTrue(
            any(
                "min_expected_net_move_pct" in item["params_json"]
                for item in built["variants"]
            )
        )
        self.assertTrue(
            any(
                "holding_window_minutes" in item["params_json"]
                for item in built["variants"]
            )
        )

    def test_holding_window_can_change_variant_hashes_and_metrics(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        first = service._params_hash({"holding_window_minutes": 240})
        second = service._params_hash({"holding_window_minutes": 1440})
        self.assertNotEqual(first, second)

    def test_two_different_params_produce_different_params_hash_values(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        first = service._params_hash({"max_movement_pct": -0.18})
        second = service._params_hash({"max_movement_pct": -0.20})
        self.assertNotEqual(first, second)

    def test_diagnostic_report_flags_matching_decision_hash_with_different_params(self) -> None:
        ledger = _FakeVariantLedger()
        now = datetime.now().astimezone()
        ledger.definitions = [
            {
                "variant_id": "baseline",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {"max_movement_pct": -0.18},
                "generation_reason": "baseline_profile",
            },
            {
                "variant_id": "variant-a",
                "base_strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "timeframe": "15Min",
                "params_json": {"max_movement_pct": -0.20},
                "generation_reason": "deeper_pullback_020",
            },
        ]
        ledger.evaluations = [
            {
                "variant_id": "variant-a",
                "sample_size": 10,
                "net_return_after_costs": 1.0,
                "win_rate": 0.5,
                "drawdown": 0.4,
                "symbols_tested": ["AAPL"],
                "recommended_status": "evaluated",
                "evaluated_at": now,
                "raw_json": {
                    "diagnostics": {
                        "params_hash": "hash-variant",
                        "generated_signal_count": 5,
                        "generated_proposal_count": 4,
                        "usable_decision_count": 10,
                        "rejected_by_param_filter_count": 7,
                        "symbols_with_decisions": ["AAPL"],
                        "first_decision_fingerprint": "first",
                        "decision_set_hash": "same-decision-hash",
                    }
                },
            },
            {
                "variant_id": "baseline",
                "sample_size": 10,
                "net_return_after_costs": 1.0,
                "win_rate": 0.5,
                "drawdown": 0.4,
                "symbols_tested": ["AAPL"],
                "recommended_status": "evaluated",
                "evaluated_at": now,
                "raw_json": {
                    "diagnostics": {
                        "params_hash": "hash-baseline",
                        "generated_signal_count": 5,
                        "generated_proposal_count": 4,
                        "usable_decision_count": 10,
                        "rejected_by_param_filter_count": 7,
                        "symbols_with_decisions": ["AAPL"],
                        "first_decision_fingerprint": "first",
                        "decision_set_hash": "same-decision-hash",
                    }
                },
            },
        ]
        report = StrategyVariantDiagnosticsReport(config=_service_config(), usage_ledger=ledger)
        built = report.build_report(base_strategy_id="mean_reversion.snapback", profile_id="snapback")
        flagged = next(item for item in built["rows"] if item["variant_id"] == "variant-a")
        self.assertEqual(flagged["warning"], "params_differ_but_decisions_and_metrics_match")
        self.assertEqual(
            built["safety_statement"],
            "Research-only diagnostic. No paper or live approval has been changed.",
        )

    def test_controlled_fixture_can_change_decision_set_hash(self) -> None:
        ledger = _FakeVariantLedger()
        service = StrategyVariantResearchService(config=_service_config(), usage_ledger=ledger)
        baseline_hash = service._decision_set_hash(["aaa", "bbb"])
        changed_hash = service._decision_set_hash(["aaa", "ccc"])
        self.assertNotEqual(baseline_hash, changed_hash)

    def test_diagnostics_cli_renders_read_only_report(self) -> None:
        original_reporter = main_module.StrategyVariantDiagnosticsReport
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--strategy-variant-diagnostics",
            "--base-strategy",
            "mean_reversion.snapback",
        ]

        class _Report:
            def render(self, **_kwargs) -> str:
                return (
                    "Strategy Variant Diagnostics\n"
                    "Research-only diagnostic. No paper or live approval has been changed."
                )

        main_module.StrategyVariantDiagnosticsReport = _Report
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.StrategyVariantDiagnosticsReport = original_reporter
            sys.argv = original_argv

        self.assertIn("Strategy Variant Diagnostics", stdout.getvalue())
        self.assertIn(
            "Research-only diagnostic. No paper or live approval has been changed.",
            stdout.getvalue(),
        )


def _sqlite_config(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        usage_ledger_db_path=path,
        operations_db_backend_preference="sqlite",
        postgres_configured=False,
        database_url="",
        database_url_source="",
        provider_pricing={},
        paper_execution_enabled=False,
        live_execution_enabled=False,
    )


def _service_config() -> SimpleNamespace:
    return SimpleNamespace(
        usage_ledger_db_path=Path("/tmp/unused.sqlite3"),
        operations_db_backend_preference="sqlite",
        postgres_configured=False,
        database_url="",
        database_url_source="",
        provider_pricing={},
        paper_execution_enabled=False,
        live_execution_enabled=False,
        shadow_stop_loss_pct=0.02,
        shadow_target_multiple=1.75,
        shadow_min_opportunity_score=55.0,
        discovery_target_count=20,
        shadow_proposal_cooldown_minutes=60,
        shadow_proposal_limit=2,
        shadow_checkpoint_windows=("1h", "1d"),
        shadow_execution_spread_bps=5.0,
        shadow_entry_slippage_bps=2.0,
        shadow_exit_slippage_bps=2.0,
        shadow_fixed_round_trip_cost_usd=0.05,
        shadow_profit_target_ladder_pct=(1.25, 2.0, 3.0),
        paper_execution_default_notional_usd=10.0,
        historical_replay_default_days=5,
        historical_replay_max_timestamps=500,
        discovery_equity_symbols=("AAPL", "MSFT"),
        discovery_crypto_symbols=("BTC/USD", "ETH/USD"),
        crypto_momentum_stop_loss_pct=0.01,
        crypto_momentum_target_multiple=2.0,
        crypto_momentum_min_signal_score=60.0,
        crypto_momentum_min_movement_pct=0.15,
        crypto_momentum_max_movement_pct=2.5,
        crypto_momentum_min_discovery_score=2.5,
        crypto_momentum_min_trade_count=2,
        research_min_proposals=50,
        research_min_net_return_pct=10.0,
        research_min_net_win_rate=0.55,
    )


if __name__ == "__main__":
    unittest.main()
