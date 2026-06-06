from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.framework.engine.technicals import (
    compute_volatility_breakout_context,
    merge_bar_rows,
)
from app.framework.runtime.settings import PROJECT_ROOT, load_runtime_config
from app.framework.storage.usage import UsageLedger


DEFAULT_MAX_PENDING_ITEMS = 500
DEFAULT_WORKER_BATCH_SIZE = 25
DEFAULT_WORKER_MAX_BATCHES = 4
LOOKBACK_PERIODS = 20


@dataclass(frozen=True, slots=True)
class SlowEnrichmentQueuePaths:
    root: Path

    @classmethod
    def default(cls) -> "SlowEnrichmentQueuePaths":
        return cls(root=PROJECT_ROOT / ".runtime" / "slow_enrichment_queue")

    @property
    def worker_lock_path(self) -> Path:
        return self.root / "worker.lock.json"

    @property
    def worker_log_path(self) -> Path:
        return self.root / "worker.log"


def enqueue_slow_enrichment_candidates(
    *,
    tick_id: str,
    queued_at: datetime,
    ranked_candidates: list[dict[str, Any]],
    selected_candidates: list[dict[str, Any]],
    usage_ledger: UsageLedger | None = None,
    paths: SlowEnrichmentQueuePaths | None = None,
    start_worker: bool = True,
    max_pending_items: int | None = None,
) -> dict[str, Any]:
    """Queue non-selected candidates for advisory slow enrichment.

    This queue is deliberately outside the order/proposal path. It lets the
    control tick prove a parallel slow worker can consume leftover candidates
    without allowing stale or background output to authorize trades.
    """

    queue_paths = paths or SlowEnrichmentQueuePaths.default()
    queue_paths.root.mkdir(parents=True, exist_ok=True)
    ledger = usage_ledger or UsageLedger(config=load_runtime_config())
    configured_max_pending = (
        int(max_pending_items)
        if max_pending_items is not None
        else int(getattr(ledger.config, "slow_enrichment_queue_max_pending_items", DEFAULT_MAX_PENDING_ITEMS))
    )

    selected_keys = {
        _candidate_key(candidate)
        for candidate in selected_candidates
        if _candidate_key(candidate)
    }
    expires_at = queued_at + timedelta(minutes=2)

    jobs: list[dict[str, Any]] = []
    for candidate in ranked_candidates:
        key = _candidate_key(candidate)
        if not key or key in selected_keys:
            continue
        job_id = f"{tick_id}:{key[0]}:{key[1]}"
        jobs.append(
            {
                "job_id": job_id,
                "tick_id": tick_id,
                "queued_at": queued_at,
                "expires_at": expires_at,
                "purpose": "slow_research_enrichment",
                "trade_authority": "none",
                "source": key[0],
                "symbol": key[1],
                "asset_class": str(candidate.get("asset_class", "")),
                "rank": int(candidate.get("rank", 0) or 0),
                "discovery_score": float(candidate.get("discovery_score", 0) or 0),
                "bar_timestamp": _coerce_datetime(candidate.get("bar_timestamp")),
                "candidate": candidate,
            }
        )

    queue_result = ledger.enqueue_slow_enrichment_jobs(
        jobs=jobs,
        max_pending_items=configured_max_pending,
        queued_at=queued_at,
    )

    worker_status: dict[str, Any] = {"worker_status": "not_started"}
    if start_worker and queue_result.get("enqueued", 0) > 0:
        worker_status = start_slow_enrichment_worker_if_idle(paths=queue_paths)

    return {
        "mode": "queued" if queue_result.get("enqueued", 0) else "idle",
        "ranked_candidates": len(ranked_candidates),
        "selected_candidates": len(selected_candidates),
        "queue_candidates": max(0, len(ranked_candidates) - len(selected_keys)),
        "enqueued": int(queue_result.get("enqueued", 0) or 0),
        "refreshed": int(queue_result.get("refreshed", 0) or 0),
        "pending_before": int(queue_result.get("pending_before", 0) or 0),
        "pending_after_estimate": int(queue_result.get("pending_after_estimate", 0) or 0),
        "max_pending_items": configured_max_pending,
        "repaired_expired": int(queue_result.get("repaired_expired", 0) or 0),
        "repaired_stale_processing": int(queue_result.get("repaired_stale_processing", 0) or 0),
        "refreshed_processed": int(queue_result.get("refreshed_processed", 0) or 0),
        "refreshed_failed": int(queue_result.get("refreshed_failed", 0) or 0),
        "refreshed_expired": int(queue_result.get("refreshed_expired", 0) or 0),
        "refreshed_pending": int(queue_result.get("refreshed_pending", 0) or 0),
        "refreshed_processing": int(queue_result.get("refreshed_processing", 0) or 0),
        "skipped_reasons": {
            "invalid_work_key": int(queue_result.get("skipped_invalid_work_key", 0) or 0),
            "pending_cap_reached": int(queue_result.get("skipped_pending_cap", 0) or 0),
        },
        "storage": "operations_db",
        **worker_status,
    }


def start_slow_enrichment_worker_if_idle(
    *,
    paths: SlowEnrichmentQueuePaths | None = None,
) -> dict[str, Any]:
    queue_paths = paths or SlowEnrichmentQueuePaths.default()
    queue_paths.root.mkdir(parents=True, exist_ok=True)

    existing = _read_worker_lock(queue_paths.worker_lock_path)
    existing_pid = _to_int(existing.get("pid")) if existing else None
    if existing_pid and _pid_is_running(existing_pid):
        return {
            "worker_status": "already_running",
            "worker_started": False,
            "worker_pid": existing_pid,
        }
    if existing_pid:
        _safe_unlink(queue_paths.worker_lock_path)

    log_handle = queue_paths.worker_log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.framework.engine.slow_enrichment_worker"],
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
    )
    _write_json(
        queue_paths.worker_lock_path,
        {
            "pid": process.pid,
            "started_at": datetime.now().astimezone().isoformat(),
            "status": "started_by_tick",
        },
    )
    log_handle.close()
    return {
        "worker_status": "started",
        "worker_started": True,
        "worker_pid": process.pid,
    }


def process_slow_enrichment_queue(
    *,
    paths: SlowEnrichmentQueuePaths | None = None,
    batch_size: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    queue_paths = paths or SlowEnrichmentQueuePaths.default()
    queue_paths.root.mkdir(parents=True, exist_ok=True)
    checked_at = now or datetime.now().astimezone()
    config = load_runtime_config()
    ledger = UsageLedger(config=config)
    effective_batch_size = (
        int(batch_size)
        if batch_size is not None
        else int(getattr(config, "slow_enrichment_queue_worker_batch_size", DEFAULT_WORKER_BATCH_SIZE))
    )
    repair = ledger.repair_slow_enrichment_jobs(repaired_at=checked_at)
    batch = ledger.claim_slow_enrichment_jobs(
        limit=max(0, effective_batch_size),
        claimed_at=checked_at,
    )
    processed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for record in batch:
        try:
            processed.append(
                _process_one_record(
                    record=record,
                    ledger=ledger,
                    processed_at=checked_at,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            errors.append(
                {
                    "job_id": record.get("job_id", ""),
                    "tick_id": record.get("tick_id", ""),
                    "errored_at": checked_at,
                    "error": f"{type(exc).__name__}: {exc}",
                    "record": record,
                }
            )

    ledger.complete_slow_enrichment_jobs(
        processed=processed,
        errors=errors,
        completed_at=checked_at,
    )
    remaining = ledger.count_slow_enrichment_jobs(statuses=("pending", "processing"))
    retry_pending = ledger.count_slow_enrichment_jobs(statuses=("failed", "expired"))

    return {
        "processed": len(processed),
        "errors": len(errors),
        "remaining": remaining,
        "terminal": retry_pending,
        "batch_size": effective_batch_size,
        "repaired_expired": int(repair.get("expired_reset", 0) or 0),
        "repaired_stale_processing": int(repair.get("stale_processing_reset", 0) or 0),
        "checked_at": checked_at.isoformat(),
    }


def process_slow_enrichment_queue_until_idle(
    *,
    paths: SlowEnrichmentQueuePaths | None = None,
    batch_size: int | None = None,
    max_batches: int | None = None,
) -> dict[str, Any]:
    queue_paths = paths or SlowEnrichmentQueuePaths.default()
    config = load_runtime_config()
    effective_batch_size = (
        int(batch_size)
        if batch_size is not None
        else int(getattr(config, "slow_enrichment_queue_worker_batch_size", DEFAULT_WORKER_BATCH_SIZE))
    )
    effective_max_batches = (
        int(max_batches)
        if max_batches is not None
        else int(getattr(config, "slow_enrichment_queue_worker_max_batches", DEFAULT_WORKER_MAX_BATCHES))
    )
    total_processed = 0
    total_errors = 0
    total_repaired_expired = 0
    total_repaired_stale_processing = 0
    last_result: dict[str, Any] = {
        "remaining": 0,
        "checked_at": datetime.now().astimezone().isoformat(),
    }
    batches_run = 0

    for _ in range(max(1, effective_max_batches)):
        last_result = process_slow_enrichment_queue(
            paths=queue_paths,
            batch_size=effective_batch_size,
        )
        batches_run += 1
        total_processed += int(last_result.get("processed", 0) or 0)
        total_errors += int(last_result.get("errors", 0) or 0)
        total_repaired_expired += int(last_result.get("repaired_expired", 0) or 0)
        total_repaired_stale_processing += int(last_result.get("repaired_stale_processing", 0) or 0)
        if int(last_result.get("remaining", 0) or 0) <= 0:
            break
        if int(last_result.get("processed", 0) or 0) <= 0 and int(last_result.get("errors", 0) or 0) <= 0:
            break

    return {
        "processed": total_processed,
        "errors": total_errors,
        "repaired_expired": total_repaired_expired,
        "repaired_stale_processing": total_repaired_stale_processing,
        "remaining": int(last_result.get("remaining", 0) or 0),
        "terminal": int(last_result.get("terminal", 0) or 0),
        "batch_size": effective_batch_size,
        "batches_run": batches_run,
        "max_batches": effective_max_batches,
        "checked_at": last_result.get("checked_at"),
    }


def repair_slow_enrichment_queue(*, now: datetime | None = None) -> dict[str, Any]:
    repaired_at = now or datetime.now().astimezone()
    config = load_runtime_config()
    ledger = UsageLedger(config=config)
    repair = ledger.repair_slow_enrichment_jobs(repaired_at=repaired_at)
    return {
        "repaired_at": repaired_at.isoformat(),
        "expired_reset": int(repair.get("expired_reset", 0) or 0),
        "stale_processing_reset": int(repair.get("stale_processing_reset", 0) or 0),
        "pending_after_repair": ledger.count_slow_enrichment_jobs(statuses=("pending", "processing")),
        "terminal_after_repair": ledger.count_slow_enrichment_jobs(statuses=("failed", "expired")),
    }


def _process_one_record(
    *,
    record: dict[str, Any],
    ledger: UsageLedger,
    processed_at: datetime,
) -> dict[str, Any]:
    candidate = dict(record.get("candidate") or {})
    source = str(candidate.get("source", "")).strip()
    symbol = str(candidate.get("symbol", "")).upper().strip()
    end_at = _coerce_datetime(candidate.get("bar_timestamp")) or processed_at
    start_at = end_at - timedelta(minutes=max(60, LOOKBACK_PERIODS * 3))
    rows = ledger.get_market_bars_for_window(
        source=source,
        symbol=symbol,
        start_at=start_at,
        end_at=end_at,
    )
    live_row = _candidate_as_bar_row(candidate)
    technical_rows = merge_bar_rows(historical_rows=rows, live_row=live_row)
    technical_context = compute_volatility_breakout_context(
        bars=technical_rows,
        lookback_periods=LOOKBACK_PERIODS,
    )
    return {
        "job_id": record.get("job_id", ""),
        "tick_id": record.get("tick_id", ""),
        "processed_at": processed_at,
        "purpose": "slow_research_enrichment",
        "trade_authority": "none",
        "source": source,
        "symbol": symbol,
        "rank": candidate.get("rank"),
        "selected": bool(candidate.get("selected")),
        "technical_context": technical_context,
    }


def _candidate_as_bar_row(candidate: dict[str, Any]) -> dict[str, Any] | None:
    close_price = _to_float(candidate.get("close_price"))
    if close_price is None:
        return None
    timestamp = _coerce_datetime(candidate.get("bar_timestamp"))
    return {
        "source": candidate.get("source", ""),
        "symbol": candidate.get("symbol", ""),
        "captured_at": timestamp,
        "bar_timestamp": timestamp,
        "open_price": close_price,
        "high_price": close_price,
        "low_price": close_price,
        "close_price": close_price,
        "close_price_gbp": _to_float(candidate.get("close_price_gbp")),
        "volume": _to_float(candidate.get("volume")),
        "trade_count": _to_int(candidate.get("trade_count")),
    }


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str] | None:
    source = str(candidate.get("source", "")).strip()
    symbol = str(candidate.get("symbol", "")).upper().strip()
    if not source or not symbol:
        return None
    return (source, symbol)


def _read_worker_lock(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, default=str), encoding="utf-8")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
