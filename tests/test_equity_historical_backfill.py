from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
import contextlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sys

import main as main_module
from app.framework.engine import backfill as backfill_module


class _Logger:
    def tick_start(self, **kwargs):
        _ = kwargs

    def runtime_summary(self, **kwargs):
        _ = kwargs

    def line(self, *args, **kwargs):
        _ = (args, kwargs)

    def profiling_summary(self, report):
        _ = report

    def api_usage_summary(self, report):
        _ = report

    def tick_end(self, report):
        _ = report


class _Ledger:
    backend = "sqlite"
    backend_detail = "test"

    def __init__(self, coverage_rows=None) -> None:
        self.coverage_rows = list(coverage_rows or [])
        self.saved_calls: list[dict[str, object]] = []
        self.tick_runs: list[object] = []
        self.api_usage: list[object] = []
        self.recorded_evaluations: list[dict[str, object]] = []

    def summarize_historical_bar_coverage(self, *, asset_class=None, symbols=None, timeframes=None):
        _ = asset_class
        requested_symbols = {str(item).replace("/", "").upper() for item in list(symbols or [])}
        requested_timeframes = set(timeframes or [])
        summary = [dict(row) for row in self.coverage_rows]
        for call in self.saved_calls:
            timeframe = str(call.get("timeframe", ""))
            if requested_timeframes and timeframe not in requested_timeframes:
                continue
            for symbol, bars in call.get("bars_by_symbol", {}).items():
                normalized_symbol = str(symbol).replace("/", "").upper()
                if requested_symbols and normalized_symbol not in requested_symbols:
                    continue
                timestamps = [bar.get("t") for bar in list(bars or []) if bar.get("t") is not None]
                summary.append(
                    {
                        "symbol": normalized_symbol,
                        "timeframe": timeframe,
                        "row_count": len(timestamps),
                        "distinct_bar_days": len({ts.date() for ts in timestamps}),
                        "latest_bar_timestamp": max(timestamps) if timestamps else None,
                        "earliest_bar_timestamp": min(timestamps) if timestamps else None,
                    }
                )
        merged: dict[tuple[str, str], dict[str, object]] = {}
        for row in summary:
            key = (str(row.get("symbol", "")), str(row.get("timeframe", "")))
            current = merged.get(key)
            if current is None or int(row.get("row_count", 0) or 0) >= int(current.get("row_count", 0) or 0):
                merged[key] = row
        return list(merged.values())

    def record_historical_bars(self, **kwargs):
        self.saved_calls.append(kwargs)
        return sum(len(list(v or [])) for v in kwargs["bars_by_symbol"].values())

    def list_historical_bars(self, *, timeframe, sources, symbols=None, start_at=None, end_at=None):
        _ = (sources, start_at, end_at)
        matched_symbols = {str(item).upper() for item in list(symbols or [])}
        rows = []
        for call in self.saved_calls:
            if str(call.get("timeframe", "")) != timeframe:
                continue
            for symbol, bars in call.get("bars_by_symbol", {}).items():
                if matched_symbols and str(symbol).upper() not in matched_symbols:
                    continue
                for bar in bars:
                    rows.append(
                        {
                            "source": call["source"],
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "bar_timestamp": bar["t"],
                            "open_price": bar.get("o"),
                            "high_price": bar.get("h"),
                            "low_price": bar.get("l"),
                            "close_price": bar.get("c"),
                            "volume": bar.get("v"),
                            "trade_count": bar.get("n"),
                        }
                    )
        return rows

    def list_tick_usage(self, *, tick_id, usage_date):
        _ = (tick_id, usage_date)
        return []

    def list_daily_usage(self, *, usage_date):
        _ = usage_date
        return []

    def total_estimated_cost_usd(self, summaries):
        _ = summaries
        return 0.0

    def total_requests(self, summaries):
        _ = summaries
        return 0

    def budget_status(self, *, daily_estimated_cost_usd):
        _ = daily_estimated_cost_usd
        return "within_limit"

    def record_tick_run(self, report):
        self.tick_runs.append(report)
        return True

    def record_api_call(self, **kwargs):
        self.api_usage.append(kwargs)
        return kwargs

    def record_strategy_variant_evaluation(self, **kwargs):
        self.recorded_evaluations.append(dict(kwargs))
        return kwargs


class _MarketData:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get_historical_equity_bars(self, context, *, symbols, timeframe, start, end, feed=""):
        _ = context
        self.calls.append(
            {
                "symbols": list(symbols),
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "feed": feed,
            }
        )
        return {
            symbol: [{"t": start, "c": 100.0, "symbol": symbol}]
            for symbol in symbols
        }

    def get_historical_crypto_bars(self, context, *, location, symbols, timeframe, start, end):
        _ = (context, location, start, end)
        self.calls.append(
            {
                "symbols": list(symbols),
                "timeframe": timeframe,
            }
        )
        if timeframe == "15Min":
            return {
                symbol.replace("/", "").upper(): [
                    {
                        "t": start + timedelta(minutes=15 * index),
                        "o": 100.0 + index,
                        "h": 101.0 + index,
                        "l": 99.0 + index,
                        "c": 100.5 + index,
                        "v": 10.0,
                        "n": 2,
                    }
                    for index in range(96 * 90)
                ]
                for symbol in symbols
            }
        return {}


class EquityHistoricalBackfillTests(unittest.TestCase):
    def test_runner_resolves_symbols_and_multiple_timeframes(self) -> None:
        ledger = _Ledger()
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            report = runner.run_equity_timeframe_backfill(
                years=6,
                timeframes=("15Min", "1Hour", "1Day"),
                symbols_from_strategies=True,
            )
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        self.assertEqual(report.status, "ok")
        self.assertEqual(
            [call["timeframe"] for call in market_data.calls],
            ["15Min", "1Hour", "1Day"],
        )
        self.assertEqual(
            sorted(market_data.calls[0]["symbols"]),
            ["AAPL", "TSLA"],
        )
        self.assertTrue(report.state_snapshot["historical_equity_backfill_multi"]["symbols_from_strategies"])
        self.assertEqual(report.state_snapshot["promotion_mutation_count"], 0)
        self.assertTrue(report.state_snapshot["live_execution_enabled"] is False)

    def test_runner_uses_latest_timestamp_resume_logic(self) -> None:
        now = datetime.now().astimezone()
        latest = now - timedelta(hours=3)
        ledger = _Ledger(
            coverage_rows=[
                {
                    "symbol": "AAPL",
                    "timeframe": "1Hour",
                    "latest_bar_timestamp": latest,
                }
            ]
        )
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            runner.run_equity_timeframe_backfill(
                years=6,
                timeframes=("1Hour",),
                symbols_from_strategies=True,
            )
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        self.assertEqual(len(market_data.calls), 2)
        aapl_call = next(call for call in market_data.calls if call["symbols"] == ["AAPL"])
        self.assertEqual(aapl_call["start"], latest + timedelta(hours=1))

    def test_backfill_from_start_ignores_resume_latest_timestamp(self) -> None:
        now = datetime.now().astimezone()
        latest = now - timedelta(hours=3)
        ledger = _Ledger(
            coverage_rows=[
                {
                    "symbol": "AAPL",
                    "timeframe": "1Hour",
                    "latest_bar_timestamp": latest,
                }
            ]
        )
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            runner.run_equity_timeframe_backfill(
                years=1,
                timeframes=("1Hour",),
                symbols_from_strategies=True,
                backfill_from_start=True,
            )
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        covering_call = next(call for call in market_data.calls if "AAPL" in call["symbols"])
        self.assertLess(covering_call["start"], latest)

    def test_runner_does_not_use_per_batch_historical_read_for_progress(self) -> None:
        class _NoListHistoricalLedger(_Ledger):
            def list_historical_bars(self, **kwargs):
                raise AssertionError("dedicated equity backfill should not read historical bars per batch")

        ledger = _NoListHistoricalLedger()
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            report = runner.run_equity_timeframe_backfill(
                years=1,
                timeframes=("15Min",),
                symbols_from_strategies=True,
            )
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        batch_progress = report.state_snapshot["historical_equity_backfill_multi"]["timeframe_results"][0]["batch_progress"][0]
        self.assertTrue(str(batch_progress["latest_timestamp_stored"]).strip())

    def test_cli_dispatches_dedicated_backfill_command(self) -> None:
        original_runner = main_module.HistoricalBackfillRunner
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--backfill-alpaca-equity-bars",
            "--years",
            "6",
            "--timeframes",
            "15Min,1Hour,1Day",
            "--symbols-from-strategies",
            "--backfill-from-start",
        ]
        calls: list[dict[str, object]] = []

        class _Runner:
            def run_equity_timeframe_backfill(self, **kwargs):
                calls.append(kwargs)

        main_module.HistoricalBackfillRunner = _Runner
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalBackfillRunner = original_runner
            sys.argv = original_argv

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["years"], 6)
        self.assertEqual(calls[0]["timeframes"], ("15Min", "1Hour", "1Day"))
        self.assertTrue(calls[0]["symbols_from_strategies"])
        self.assertTrue(calls[0]["backfill_from_start"])

    def test_crypto_1day_resample_prefers_1hour_and_persists_readiness(self) -> None:
        ledger = _Ledger()
        day_start = datetime(2026, 6, 1, tzinfo=backfill_module.UTC)
        ledger.saved_calls.append(
            {
                "source": "alpaca_crypto_data",
                "timeframe": "1Hour",
                "bars_by_symbol": {
                    "BTCUSD": [
                        {
                            "t": day_start + timedelta(hours=hour),
                            "o": 100.0 + hour,
                            "h": 101.0 + hour,
                            "l": 99.0 + hour,
                            "c": 100.5 + hour,
                            "v": 10.0,
                            "n": 2,
                        }
                        for hour in range(24)
                    ]
                },
            }
        )
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(crypto_symbols=("BTCUSD", "ETHUSD")),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            report = runner.run_crypto_1day_backfill_or_resample()
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        summary = report.state_snapshot["historical_crypto_1day_backfill_or_resample"]
        self.assertEqual(summary["source_timeframe"], "1Hour")
        self.assertEqual(summary["bars_generated"], 1)
        self.assertEqual(summary["skipped_incomplete_days"], 0)
        saved_1day = next(call for call in ledger.saved_calls if call["timeframe"] == "1Day")
        bar = saved_1day["bars_by_symbol"]["BTCUSD"][0]
        self.assertEqual(bar["o"], 100.0)
        self.assertEqual(bar["h"], 124.0)
        self.assertEqual(bar["l"], 99.0)
        self.assertEqual(bar["c"], 123.5)
        self.assertEqual(bar["v"], 240.0)
        self.assertEqual(bar["source_timeframe"], "1Hour")
        self.assertEqual(bar["provenance"], "resampled_from_1Hour")
        self.assertEqual(len(ledger.recorded_evaluations), 1)
        self.assertEqual(ledger.recorded_evaluations[0]["dataset_id"], "historical_crypto_bars:1Day")
        self.assertEqual(ledger.recorded_evaluations[0]["raw"]["readiness_status"], "ready")

    def test_crypto_1day_resample_skips_incomplete_days(self) -> None:
        ledger = _Ledger()
        day_start = datetime(2026, 6, 1, tzinfo=backfill_module.UTC)
        ledger.saved_calls.append(
            {
                "source": "alpaca_crypto_data",
                "timeframe": "1Hour",
                "bars_by_symbol": {
                    "BTCUSD": [
                        {
                            "t": day_start + timedelta(hours=hour),
                            "o": 100.0 + hour,
                            "h": 101.0 + hour,
                            "l": 99.0 + hour,
                            "c": 100.5 + hour,
                            "v": 10.0,
                            "n": 2,
                        }
                        for hour in range(12)
                    ]
                },
            }
        )
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(crypto_symbols=("BTCUSD",)),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            report = runner.run_crypto_1day_backfill_or_resample()
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        summary = report.state_snapshot["historical_crypto_1day_backfill_or_resample"]
        self.assertEqual(summary["bars_generated"], 0)
        self.assertEqual(summary["skipped_incomplete_days"], 1)
        self.assertEqual(summary["data_gap_resolved"], "no")
        self.assertEqual(ledger.recorded_evaluations[0]["raw"]["data_gap_resolved"], "no")

    def test_cli_dispatches_crypto_1day_backfill_or_resample_command(self) -> None:
        original_runner = main_module.HistoricalBackfillRunner
        original_argv = sys.argv
        sys.argv = ["main.py", "--backfill-or-resample-crypto-1day-bars"]
        calls: list[str] = []

        class _Runner:
            def run_crypto_1day_backfill_or_resample(self):
                calls.append("called")

        main_module.HistoricalBackfillRunner = _Runner
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalBackfillRunner = original_runner
            sys.argv = original_argv

        self.assertEqual(calls, ["called"])

    def test_crypto_15min_backfill_persists_readiness_without_touching_paper_or_live(self) -> None:
        ledger = _Ledger(
            coverage_rows=[
                {
                    "symbol": "BTCUSD",
                    "timeframe": "15Min",
                    "row_count": 96 * 4,
                    "distinct_bar_days": 4,
                },
                {
                    "symbol": "ETHUSD",
                    "timeframe": "15Min",
                    "row_count": 96 * 2,
                    "distinct_bar_days": 2,
                },
            ]
        )
        market_data = _MarketData()
        original_get_market_data_adapter = backfill_module.get_market_data_adapter
        original_fx_gbp_reference = backfill_module.fx_gbp_reference
        backfill_module.get_market_data_adapter = lambda context, provider: market_data
        backfill_module.fx_gbp_reference = lambda context: {"usd_to_gbp": 0.79}
        try:
            runner = backfill_module.HistoricalBackfillRunner(
                config=self._config(crypto_symbols=("BTC/USD", "ETH/USD")),
                usage_ledger=ledger,
                logger=_Logger(),
                sleep_fn=lambda seconds: None,
            )
            report = runner.run_crypto_15min_backfill_or_resample()
        finally:
            backfill_module.get_market_data_adapter = original_get_market_data_adapter
            backfill_module.fx_gbp_reference = original_fx_gbp_reference

        summary = report.state_snapshot["historical_crypto_15min_backfill_or_resample"]
        self.assertEqual(summary["dataset_id"], "historical_crypto_bars:15Min")
        self.assertEqual(summary["readiness_status"], "ready")
        self.assertEqual(summary["data_gap_resolved"], "yes")
        self.assertEqual(summary["minimum_days_required"], 30)
        self.assertEqual(summary["preferred_days"], 90)
        self.assertEqual(summary["symbols_covered"], 2)
        self.assertEqual(summary["paper_trades_created"], "no")
        self.assertEqual(summary["live_changed"], "no")
        self.assertEqual(summary["thresholds_changed"], "no")
        self.assertEqual(summary["promotion_policy_changed"], "no")
        self.assertTrue(all(item["days_after"] >= 30 for item in summary["symbol_results"]))
        self.assertEqual(len(ledger.recorded_evaluations), 1)
        self.assertEqual(ledger.recorded_evaluations[0]["dataset_id"], "historical_crypto_bars:15Min")
        self.assertEqual(ledger.recorded_evaluations[0]["raw"]["readiness_status"], "ready")

    def test_cli_dispatches_crypto_15min_backfill_or_resample_command(self) -> None:
        original_runner = main_module.HistoricalBackfillRunner
        original_argv = sys.argv
        sys.argv = ["main.py", "--backfill-or-resample-crypto-15min-bars"]
        calls: list[str] = []

        class _Runner:
            def run_crypto_15min_backfill_or_resample(self, *, days=None, crypto_symbols=None):
                calls.append(f"days={days}|symbols={crypto_symbols}")

        main_module.HistoricalBackfillRunner = _Runner
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalBackfillRunner = original_runner
            sys.argv = original_argv

        self.assertEqual(calls, ["days=None|symbols=None"])

    def test_cli_dispatches_crypto_15min_backfill_or_resample_with_symbol_and_days(self) -> None:
        original_runner = main_module.HistoricalBackfillRunner
        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "--backfill-or-resample-crypto-15min-bars",
            "--symbols",
            "BTC/USD",
            "--days",
            "1",
        ]
        calls: list[tuple[object, object]] = []

        class _Runner:
            def run_crypto_15min_backfill_or_resample(self, *, days=None, crypto_symbols=None):
                calls.append((days, crypto_symbols))

        main_module.HistoricalBackfillRunner = _Runner
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalBackfillRunner = original_runner
            sys.argv = original_argv

        self.assertEqual(calls, [(1, ("BTC/USD",))])

    def test_crypto_15min_bulk_import_from_csv_folder_is_idempotent_and_persists_readiness(self) -> None:
        ledger = _Ledger()
        runner = backfill_module.HistoricalBackfillRunner(
            config=self._config(crypto_symbols=("BTC/USD", "ETH/USD")),
            usage_ledger=ledger,
            logger=_Logger(),
            sleep_fn=lambda seconds: None,
        )
        with tempfile.TemporaryDirectory(dir="/Volumes/Bob/www/ghostfrog-centaur") as temp_dir:
            folder = Path(temp_dir)
            self._write_csv(
                folder / "btc.csv",
                [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "symbol": "BTC/USD", "open": "100", "high": "105", "low": "99", "close": "104", "volume": "10"},
                    {"timestamp": "2025-01-01T00:15:00+00:00", "symbol": "BTC/USD", "open": "104", "high": "106", "low": "103", "close": "105", "volume": "11"},
                    {"timestamp": "2025-01-01T00:15:00+00:00", "symbol": "BTC/USD", "open": "104", "high": "106", "low": "103", "close": "105", "volume": "11"},
                ],
            )
            self._write_csv(
                folder / "eth.csv",
                [
                    {"timestamp": "2025-01-02T00:00:00+00:00", "symbol": "ETH/USD", "open": "200", "high": "205", "low": "199", "close": "204", "volume": "8"},
                    {"timestamp": "2025-01-02T00:15:00+00:00", "symbol": "DOGE/USD", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "12"},
                ],
            )

            report = runner.run_crypto_15min_bulk_import(path=str(folder))
            summary = report.state_snapshot["historical_crypto_15min_bulk_import"]
            self.assertEqual(summary["rows_inserted"], 3)
            self.assertEqual(summary["rows_updated"], 0)
            self.assertEqual(summary["rows_skipped"], 2)
            self.assertEqual(summary["symbols_imported"], ["BTCUSD", "ETHUSD"])
            self.assertEqual(summary["paper_trades_created"], "no")
            self.assertEqual(summary["live_changed"], "no")
            self.assertEqual(summary["thresholds_changed"], "no")
            self.assertEqual(summary["promotion_policy_changed"], "no")
            self.assertEqual(len(ledger.recorded_evaluations), 1)
            self.assertEqual(ledger.recorded_evaluations[0]["dataset_id"], "historical_crypto_bars:15Min")

            second_report = runner.run_crypto_15min_bulk_import(path=str(folder))
            second = second_report.state_snapshot["historical_crypto_15min_bulk_import"]
            self.assertEqual(second["rows_inserted"], 0)
            self.assertEqual(second["rows_updated"], 3)
            self.assertEqual(second["rows_skipped"], 2)

    def test_cli_dispatches_crypto_15min_bulk_import_command(self) -> None:
        original_runner = main_module.HistoricalBackfillRunner
        original_argv = sys.argv
        sys.argv = ["main.py", "--import-crypto-15min-bars", "--path", "/tmp/crypto-data"]
        calls: list[str] = []

        class _Runner:
            def run_crypto_15min_bulk_import(self, *, path):
                calls.append(path)

        main_module.HistoricalBackfillRunner = _Runner
        stdout = StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                main_module.main()
        finally:
            main_module.HistoricalBackfillRunner = original_runner
            sys.argv = original_argv

        self.assertEqual(calls, ["/tmp/crypto-data"])

    def test_crypto_15min_bulk_import_rejects_path_outside_project(self) -> None:
        runner = backfill_module.HistoricalBackfillRunner(
            config=self._config(crypto_symbols=("BTC/USD",)),
            usage_ledger=_Ledger(),
            logger=_Logger(),
            sleep_fn=lambda seconds: None,
        )
        with self.assertRaisesRegex(ValueError, "inside the current project workspace"):
            runner.run_crypto_15min_bulk_import(path="/Volumes/Bob/data/crypto_15min_2025_2026")

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        fieldnames = list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _config(self, *, crypto_symbols=("BTC/USD",)):
        return SimpleNamespace(
            discovery_equity_symbols=("AAPL", "TSLA"),
            discovery_crypto_symbols=crypto_symbols,
            historical_backfill_default_days=30,
            historical_backfill_default_timeframe="1Min",
            api_daily_cost_warning_usd=1.0,
            api_daily_cost_limit_usd=2.0,
            alpaca_stock_feed="iex",
            alpaca_crypto_location="us",
            live_execution_enabled=False,
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            shadow_min_opportunity_score=55.0,
            crypto_momentum_stop_loss_pct=0.02,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=55.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=3.0,
            crypto_momentum_min_trade_count=1,
            crypto_momentum_min_volume_gbp=50_000.0,
            crypto_momentum_max_spread_pct=0.25,
        )


if __name__ == "__main__":
    unittest.main()
