from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.framework.reporting.threshold_advisor import ThresholdAdvisor
from app.framework.runtime.settings import PROJECT_ROOT, load_runtime_config
from app.framework.storage.usage import UsageLedger


@dataclass(frozen=True, slots=True)
class ThresholdAdvisorWorkerPaths:
    root: Path

    @classmethod
    def default(cls) -> "ThresholdAdvisorWorkerPaths":
        return cls(root=PROJECT_ROOT / ".runtime" / "threshold_advisor_worker")

    @property
    def worker_lock_path(self) -> Path:
        return self.root / "worker.lock.json"

    @property
    def worker_log_path(self) -> Path:
        return self.root / "worker.log"

    @property
    def request_path(self) -> Path:
        return self.root / "latest_request.json"


def request_threshold_advisor_update(
    *,
    tick_id: str,
    requested_at: datetime,
    current_signal_preview: list[dict[str, Any]],
    paths: ThresholdAdvisorWorkerPaths | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Start the GA/adaptive-threshold worker without blocking the tick.

    The worker has no trade authority. It only updates the persisted adaptive
    threshold state that future trading ticks may read as cached evidence.
    """

    if not enabled:
        return {
            "mode": "disabled",
            "worker_status": "disabled",
            "worker_started": False,
            "trade_authority": "none",
        }

    worker_paths = paths or ThresholdAdvisorWorkerPaths.default()
    worker_paths.root.mkdir(parents=True, exist_ok=True)
    _write_json(
        worker_paths.request_path,
        {
            "tick_id": tick_id,
            "requested_at": requested_at.isoformat(),
            "current_signal_preview": current_signal_preview[:25],
        },
    )
    return {
        "mode": "async_adaptive_threshold",
        "storage": "operations_db",
        "trade_authority": "none",
        **start_threshold_advisor_worker_if_idle(paths=worker_paths),
    }


def start_threshold_advisor_worker_if_idle(
    *,
    paths: ThresholdAdvisorWorkerPaths | None = None,
) -> dict[str, Any]:
    worker_paths = paths or ThresholdAdvisorWorkerPaths.default()
    worker_paths.root.mkdir(parents=True, exist_ok=True)

    existing = _read_worker_lock(worker_paths.worker_lock_path)
    existing_pid = _to_int(existing.get("pid")) if existing else None
    if existing_pid and _pid_is_running(existing_pid):
        return {
            "worker_status": "already_running",
            "worker_started": False,
            "worker_pid": existing_pid,
        }
    if existing_pid:
        _safe_unlink(worker_paths.worker_lock_path)

    log_handle = worker_paths.worker_log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.framework.engine.threshold_advisor_process"],
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
    )
    _write_json(
        worker_paths.worker_lock_path,
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


def process_threshold_advisor_once(
    *,
    paths: ThresholdAdvisorWorkerPaths | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    worker_paths = paths or ThresholdAdvisorWorkerPaths.default()
    worker_paths.root.mkdir(parents=True, exist_ok=True)
    processed_at = now or datetime.now().astimezone()
    request = _read_worker_lock(worker_paths.request_path)
    tick_id = str(request.get("tick_id") or f"threshold-worker-{processed_at.isoformat()}")
    preview = request.get("current_signal_preview")
    current_signal_preview = preview if isinstance(preview, list) else []
    config = load_runtime_config()
    ledger = UsageLedger(config=config)
    result = ThresholdAdvisor(config=config, usage_ledger=ledger).effective_threshold(
        tick_id=tick_id,
        now=processed_at,
        current_signal_preview=[
            item for item in current_signal_preview if isinstance(item, dict)
        ],
    )
    return {
        "tick_id": tick_id,
        "processed_at": processed_at.isoformat(),
        "status": "ok",
        "trade_authority": "none",
        "applied": bool(result.get("applied")),
        "effective_threshold": result.get("effective_threshold"),
        "action": result.get("action", "hold"),
        "confidence": result.get("confidence", "-"),
        "advice_status": result.get("advice_status", "-"),
        "reason": result.get("reason", "-"),
    }


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


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
