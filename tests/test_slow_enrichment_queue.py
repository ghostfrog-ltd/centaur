from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.framework.engine.slow_enrichment_queue import (
    SlowEnrichmentQueuePaths,
    enqueue_slow_enrichment_candidates,
    process_slow_enrichment_queue,
    process_slow_enrichment_queue_until_idle,
    repair_slow_enrichment_queue,
)
from app.framework.storage.usage import UsageLedger


class SlowEnrichmentQueueTests(unittest.TestCase):
    def test_enqueue_only_non_selected_candidates_without_trade_authority(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            queued_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
            ranked = [
                _candidate("AAPL", rank=1, selected=True),
                _candidate("MSFT", rank=2, selected=False),
                _candidate("NVDA", rank=3, selected=False),
            ]
            result = enqueue_slow_enrichment_candidates(
                tick_id="tick-1",
                queued_at=queued_at,
                ranked_candidates=ranked,
                selected_candidates=[ranked[0]],
                usage_ledger=ledger,
                paths=SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker"),
                start_worker=False,
            )

            self.assertEqual(result["enqueued"], 2)
            self.assertEqual(result["worker_status"], "not_started")
            self.assertEqual(result["storage"], "operations_db")
            self.assertEqual(result["skipped_reasons"]["invalid_work_key"], 0)
            self.assertEqual(result["skipped_reasons"]["pending_cap_reached"], 0)
            rows = _sqlite_rows(config.usage_ledger_db_path, "slow_enrichment_jobs")
            self.assertEqual([row["symbol"] for row in rows], ["MSFT", "NVDA"])
            self.assertTrue(all(row["status"] == "pending" for row in rows))

    def test_worker_processes_bounded_batch_to_processed_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            queued_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
            enqueue_slow_enrichment_candidates(
                tick_id="tick-1",
                queued_at=queued_at,
                ranked_candidates=[
                    _candidate("MSFT", rank=1, selected=False),
                    _candidate("NVDA", rank=2, selected=False),
                ],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker"),
                start_worker=False,
            )

            with (
                patch(
                    "app.framework.engine.slow_enrichment_queue.load_runtime_config",
                    return_value=config,
                ),
                patch.object(UsageLedger, "get_market_bars_for_window", _fake_bars),
            ):
                result = process_slow_enrichment_queue(
                    paths=SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker"),
                    batch_size=1,
                    now=queued_at + timedelta(seconds=5),
                )

            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["remaining"], 1)
            jobs = _sqlite_rows(config.usage_ledger_db_path, "slow_enrichment_jobs")
            self.assertEqual(
                [row["status"] for row in jobs],
                ["processed", "pending"],
            )
            processed = _sqlite_rows(config.usage_ledger_db_path, "slow_enrichment_results")
            self.assertEqual(len(processed), 1)
            self.assertEqual(processed[0]["trade_authority"], "none")
            self.assertIn("technical_context_ready", processed[0]["technical_context_json"])

    def test_expired_full_queue_recovers_without_raising_cap(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            old_queued_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
            fresh_queued_at = old_queued_at + timedelta(minutes=10)
            worker_paths = SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker")

            enqueue_slow_enrichment_candidates(
                tick_id="tick-old",
                queued_at=old_queued_at,
                ranked_candidates=[
                    _candidate("MSFT", rank=1, selected=False),
                    _candidate("NVDA", rank=2, selected=False),
                ],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=worker_paths,
                start_worker=False,
                max_pending_items=2,
            )

            result = enqueue_slow_enrichment_candidates(
                tick_id="tick-new",
                queued_at=fresh_queued_at,
                ranked_candidates=[_candidate("AAPL", rank=1, selected=False)],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=worker_paths,
                start_worker=False,
                max_pending_items=2,
            )

            self.assertEqual(result["enqueued"], 1)
            self.assertEqual(result["pending_before"], 0)
            self.assertEqual(result["repaired_expired"], 2)
            rows = _sqlite_rows(config.usage_ledger_db_path, "slow_enrichment_jobs")
            statuses = {row["symbol"]: row["status"] for row in rows}
            self.assertEqual(statuses["MSFT"], "expired")
            self.assertEqual(statuses["NVDA"], "expired")
            self.assertEqual(statuses["AAPL"], "pending")

    def test_enqueue_is_idempotent_by_candidate_work_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            queued_at = datetime.now(timezone.utc)
            worker_paths = SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker")

            first = enqueue_slow_enrichment_candidates(
                tick_id="tick-1",
                queued_at=queued_at,
                ranked_candidates=[_candidate("MSFT", rank=1, selected=False)],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=worker_paths,
                start_worker=False,
                max_pending_items=5,
            )
            second = enqueue_slow_enrichment_candidates(
                tick_id="tick-2",
                queued_at=queued_at + timedelta(minutes=1),
                ranked_candidates=[_candidate("MSFT", rank=1, selected=False)],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=worker_paths,
                start_worker=False,
                max_pending_items=5,
            )

            self.assertEqual(first["enqueued"], 1)
            self.assertEqual(second["enqueued"], 0)
            self.assertEqual(second["refreshed"], 1)
            self.assertEqual(second["refreshed_pending"], 1)
            rows = _sqlite_rows(config.usage_ledger_db_path, "slow_enrichment_jobs")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tick_id"], "tick-2")

    def test_deferred_candidates_are_enqueued_or_skipped_with_visible_reason(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            queued_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
            ranked = [
                _candidate(f"SYM{index:02d}", rank=index, selected=index <= 6)
                for index in range(1, 32)
            ]
            result = enqueue_slow_enrichment_candidates(
                tick_id="tick-31",
                queued_at=queued_at,
                ranked_candidates=ranked,
                selected_candidates=ranked[:6],
                usage_ledger=ledger,
                paths=SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker"),
                start_worker=False,
                max_pending_items=10,
            )

            deferred = 25
            skipped_total = sum(int(count or 0) for count in result["skipped_reasons"].values())
            self.assertEqual(result["queue_candidates"], deferred)
            self.assertEqual(result["enqueued"] + result["refreshed"] + skipped_total, deferred)
            self.assertEqual(result["enqueued"], 10)
            self.assertEqual(result["skipped_reasons"]["pending_cap_reached"], 15)

            with (
                patch(
                    "app.framework.engine.slow_enrichment_queue.load_runtime_config",
                    return_value=config,
                ),
                patch.object(UsageLedger, "get_market_bars_for_window", _fake_bars),
            ):
                processed = process_slow_enrichment_queue(
                    paths=SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker"),
                    batch_size=5,
                    now=queued_at + timedelta(seconds=5),
                )

            self.assertGreater(processed["processed"], 0)
            self.assertGreaterEqual(processed["remaining"], 0)

    def test_process_and_repair_commands_report_drain_and_cleanup(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = _sqlite_config(Path(temp_dir) / "ops.sqlite3")
            ledger = UsageLedger(config=config)
            queued_at = datetime.now(timezone.utc)
            worker_paths = SlowEnrichmentQueuePaths(root=Path(temp_dir) / "worker")
            enqueue_slow_enrichment_candidates(
                tick_id="tick-1",
                queued_at=queued_at,
                ranked_candidates=[_candidate("MSFT", rank=1, selected=False)],
                selected_candidates=[],
                usage_ledger=ledger,
                paths=worker_paths,
                start_worker=False,
                max_pending_items=5,
            )

            with (
                patch(
                    "app.framework.engine.slow_enrichment_queue.load_runtime_config",
                    return_value=config,
                ),
                patch.object(UsageLedger, "get_market_bars_for_window", _fake_bars),
            ):
                processed = process_slow_enrichment_queue_until_idle(
                    paths=worker_paths,
                    batch_size=1,
                    max_batches=2,
                )
                repaired = repair_slow_enrichment_queue(now=queued_at + timedelta(minutes=20))

            self.assertEqual(processed["processed"], 1)
            self.assertEqual(processed["remaining"], 0)
            self.assertIn("repaired_expired", processed)
            self.assertIn("pending_after_repair", repaired)


def _fake_bars(self: UsageLedger, **kwargs: object) -> list[dict[str, object]]:
    end_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index in range(21):
        close = 100.0 + index
        rows.append(
            {
                "bar_timestamp": end_at - timedelta(minutes=21 - index),
                "open_price": close - 0.5,
                "high_price": close,
                "low_price": close - 1.0,
                "close_price": close,
                "volume": 1000 + index,
            }
        )
    return rows


def _candidate(symbol: str, *, rank: int, selected: bool) -> dict[str, object]:
    return {
        "symbol": symbol,
        "source": "alpaca_market_data",
        "asset_class": "equity",
        "rank": rank,
        "selected": selected,
        "discovery_score": 10.0 - rank,
        "close_price": 123.45,
        "movement_pct": 0.5,
        "volume": 1000,
        "trade_count": 50,
        "bar_timestamp": "2026-06-04T12:00:00+00:00",
    }


def _sqlite_config(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        usage_ledger_db_path=path,
        operations_db_backend_preference="sqlite",
        postgres_configured=False,
        database_url="",
        paper_execution_enabled=False,
        live_execution_enabled=False,
        slow_enrichment_queue_max_pending_items=500,
        slow_enrichment_queue_worker_batch_size=25,
        slow_enrichment_queue_worker_max_batches=4,
        slow_enrichment_queue_processing_timeout_seconds=900,
        slow_enrichment_queue_max_retries=3,
        slow_enrichment_queue_retry_backoff_seconds=120,
    )


def _sqlite_rows(path: Path, table: str) -> list[dict[str, object]]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY job_id ASC").fetchall()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    unittest.main()
