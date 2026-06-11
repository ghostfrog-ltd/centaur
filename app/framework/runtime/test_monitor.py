from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable

from app.framework.runtime.slack import SlackNotificationError, SlackWebhookClient


@dataclass(frozen=True, slots=True)
class TestMonitorConfig:
    enabled: bool
    command: tuple[str, ...]
    state_path: Path
    log_path: Path
    reminder_minutes: int
    output_tail_lines: int
    scheduler_freshness_enabled: bool
    scheduler_max_age_minutes: int
    slack_enabled: bool
    slack_webhook_url: str
    slack_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class TestRunResult:
    exit_code: int
    output: str
    duration_seconds: float
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class PlannedAlert:
    kind: str
    text: str


def load_test_monitor_config(
    *,
    project_root: Path,
    environ: dict[str, str],
) -> TestMonitorConfig:
    command_text = environ.get("TEST_MONITOR_COMMAND", "").strip()
    command = (
        tuple(shlex.split(command_text))
        if command_text
        else (sys.executable, "-m", "unittest", "discover", "tests")
    )
    return TestMonitorConfig(
        enabled=_parse_bool(environ.get("TEST_MONITOR_ENABLED"), default=True),
        command=command,
        state_path=_resolve_project_path(
            project_root,
            environ.get("TEST_MONITOR_STATE_PATH", ".runtime/test_monitor_state.json"),
        ),
        log_path=_resolve_project_path(
            project_root,
            environ.get("TEST_MONITOR_LOG_PATH", "logs/test_monitor.log"),
        ),
        reminder_minutes=max(
            1,
            _parse_int(environ.get("TEST_MONITOR_REMINDER_MINUTES"), default=60),
        ),
        output_tail_lines=max(
            5,
            _parse_int(environ.get("TEST_MONITOR_OUTPUT_TAIL_LINES"), default=80),
        ),
        scheduler_freshness_enabled=_parse_bool(
            environ.get("TEST_MONITOR_SCHEDULER_FRESHNESS_ENABLED"),
            default=True,
        ),
        scheduler_max_age_minutes=max(
            1,
            _parse_int(
                environ.get("TEST_MONITOR_SCHEDULER_MAX_AGE_MINUTES"),
                default=10,
            ),
        ),
        slack_enabled=_parse_bool(
            environ.get("TEST_MONITOR_SLACK_ENABLED"),
            default=_parse_bool(environ.get("SLACK_ALERTS_ENABLED"), default=False),
        ),
        slack_webhook_url=str(environ.get("SLACK_WEBHOOK_URL", "") or "").strip(),
        slack_timeout_seconds=max(
            1,
            _parse_int(environ.get("SLACK_REQUEST_TIMEOUT_SECONDS"), default=5),
        ),
    )


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        loaded[key] = _strip_env_value(value.strip())
    return loaded


def run_test_command(
    *,
    command: tuple[str, ...],
    cwd: Path,
    now: Callable[[], datetime] | None = None,
) -> TestRunResult:
    clock = now or _utc_now
    started_at = clock()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    finished_at = clock()
    return TestRunResult(
        exit_code=int(completed.returncode),
        output=str(completed.stdout or ""),
        duration_seconds=max(0.0, (finished_at - started_at).total_seconds()),
        checks={
            "unit_tests": {
                "status": "pass" if int(completed.returncode) == 0 else "fail",
                "summary": (
                    "Unit tests passed."
                    if int(completed.returncode) == 0
                    else f"Unit tests failed with exit={int(completed.returncode)}."
                ),
            }
        },
    )


def preflight_operations_store_for_scheduler(*, runtime_config: Any) -> tuple[bool, str]:
    preference = str(
        getattr(runtime_config, "operations_db_backend_preference", "") or ""
    ).strip().lower()
    postgres_configured = bool(getattr(runtime_config, "postgres_configured", False))
    database_url = str(getattr(runtime_config, "database_url", "") or "").strip()
    paper_execution_enabled = bool(
        getattr(runtime_config, "paper_execution_enabled", False)
    )
    live_execution_enabled = bool(getattr(runtime_config, "live_execution_enabled", False))
    postgres_required = (
        paper_execution_enabled
        or live_execution_enabled
        or preference == "postgres"
        or postgres_configured
    )
    if not postgres_required:
        return True, "PostgreSQL operations store is not required for this runtime."
    if not postgres_configured or not database_url:
        return (
            False,
            "PostgreSQL operations store is unavailable; check DATABASE_URL/POSTGRES_* settings.",
        )
    return True, "PostgreSQL operations store is configured."


def append_scheduler_freshness_check(
    *,
    result: TestRunResult,
    config: TestMonitorConfig,
    latest_tick: dict[str, Any] | None,
    now: datetime,
    check_error: str = "",
) -> TestRunResult:
    """Fold the non-mutating scheduler liveness check into the monitored result."""
    if not config.scheduler_freshness_enabled:
        return result

    checks = dict(result.checks)
    passed = False
    lines = ["", "Centaur scheduler freshness check:"]
    scheduler_status = "fail"
    scheduler_summary = ""
    operations_store_status = "pass"
    operations_store_summary = "Operations store preflight passed."
    if check_error:
        operations_store_status = "fail"
        operations_store_summary = check_error
        scheduler_status = "skipped"
        scheduler_summary = (
            "Scheduler freshness check skipped because operations store preflight failed."
        )
        lines.append("SKIPPED: operations store preflight failed")
        lines.append(f"Reason: {check_error}")
    elif latest_tick is None:
        scheduler_summary = "No control tick has been recorded."
        lines.append("FAILED: no control tick has been recorded")
    else:
        tick_id = str(latest_tick.get("tick_id") or "-")
        status = str(latest_tick.get("status") or "unknown").strip().lower()
        started_at = _coerce_datetime(latest_tick.get("started_at"))
        if started_at is None:
            lines.append(
                f"FAILED: latest tick {tick_id} has no parseable started_at value"
            )
        else:
            age_seconds = max(0, int((now - started_at).total_seconds()))
            max_age_seconds = config.scheduler_max_age_minutes * 60
            age_text = _format_age(seconds=age_seconds)
            if status == "ok" and age_seconds <= max_age_seconds:
                passed = True
                scheduler_status = "pass"
                scheduler_summary = (
                    f"Latest tick {tick_id} is fresh and ok with age={age_text}."
                )
                lines.append(
                    f"PASS: latest tick {tick_id} status=ok age={age_text} "
                    f"limit={config.scheduler_max_age_minutes}m"
                )
            else:
                reason = "stale" if age_seconds > max_age_seconds else "not_ok"
                scheduler_summary = (
                    f"Latest tick {tick_id} failed freshness with status={status} "
                    f"age={age_text} reason={reason}."
                )
                lines.append(
                    f"FAILED: latest tick {tick_id} status={status} age={age_text} "
                    f"limit={config.scheduler_max_age_minutes}m reason={reason}"
                )

    output = "\n".join(
        part for part in [result.output.rstrip(), "\n".join(lines)] if part
    )
    checks["operations_store"] = {
        "status": operations_store_status,
        "summary": operations_store_summary,
    }
    checks["scheduler_freshness"] = {
        "status": scheduler_status,
        "summary": scheduler_summary,
    }
    if result.exit_code != 0:
        exit_code = result.exit_code
    elif scheduler_status == "fail":
        exit_code = 1
    else:
        exit_code = 0
    return TestRunResult(
        exit_code=exit_code,
        output=output,
        duration_seconds=result.duration_seconds,
        checks=checks,
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def append_monitor_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def plan_state_update(
    *,
    previous_state: dict[str, Any],
    result: TestRunResult,
    config: TestMonitorConfig,
    now: datetime,
) -> tuple[dict[str, Any], list[PlannedAlert]]:
    state = dict(previous_state)
    now_text = now.isoformat()
    alerts: list[PlannedAlert] = []
    previous_failure = str(state.get("current_failure_fingerprint", "") or "")

    state["last_run_at"] = now_text
    state["last_exit_code"] = result.exit_code
    state["last_duration_seconds"] = round(result.duration_seconds, 3)

    if result.passed:
        if previous_failure:
            alerts.append(
                PlannedAlert(
                    kind="recovered",
                    text=(
                        "Centaur test monitor recovered: the scheduled unit suite is passing again "
                        f"after failure {previous_failure[:12]}."
                    ),
                )
            )
        state.update(
            {
                "last_status": "passed",
                "last_passed_at": now_text,
                "current_failure_fingerprint": "",
                "current_failure_first_seen_at": "",
                "current_failure_last_seen_at": "",
                "current_failure_output_tail": "",
                "acknowledged_failure_fingerprint": "",
            }
        )
        return state, alerts

    fingerprint = build_failure_fingerprint(result)
    output_tail = tail_output(result.output, line_limit=config.output_tail_lines)
    first_seen = (
        str(state.get("current_failure_first_seen_at", "") or "")
        if previous_failure == fingerprint
        else now_text
    )
    state.update(
        {
            "last_status": "failed",
            "current_failure_fingerprint": fingerprint,
            "current_failure_first_seen_at": first_seen,
            "current_failure_last_seen_at": now_text,
            "current_failure_output_tail": output_tail,
        }
    )

    acknowledged = str(state.get("acknowledged_failure_fingerprint", "") or "")
    if acknowledged == fingerprint:
        return state, alerts

    last_alert_at = _parse_datetime(str(state.get("last_alert_at", "") or ""))
    should_alert = previous_failure != fingerprint or last_alert_at is None
    if last_alert_at is not None:
        should_alert = should_alert or now - last_alert_at >= timedelta(
            minutes=config.reminder_minutes,
        )
    if should_alert:
        kind = "failed" if previous_failure != fingerprint else "still_failed"
        alerts.append(
            PlannedAlert(
                kind=kind,
                text=_failure_message(
                    kind=kind,
                    fingerprint=fingerprint,
                    result=result,
                    config=config,
                    output_tail=output_tail,
                ),
            )
        )
    return state, alerts


def mark_alerts_sent(
    *,
    state: dict[str, Any],
    alerts: list[PlannedAlert],
    now: datetime,
) -> dict[str, Any]:
    if not alerts:
        return state
    updated = dict(state)
    failed_alerts = [alert for alert in alerts if alert.kind in {"failed", "still_failed"}]
    if failed_alerts:
        updated["last_alert_at"] = now.isoformat()
        updated["alert_count"] = int(updated.get("alert_count", 0) or 0) + len(
            failed_alerts
        )
    if any(alert.kind == "recovered" for alert in alerts):
        updated["last_recovery_alert_at"] = now.isoformat()
    return updated


def reset_failure_notification(*, state: dict[str, Any], now: datetime) -> dict[str, Any]:
    updated = dict(state)
    fingerprint = str(updated.get("current_failure_fingerprint", "") or "")
    if fingerprint:
        updated["acknowledged_failure_fingerprint"] = fingerprint
        updated["notification_reset_at"] = now.isoformat()
    else:
        updated["notification_reset_at"] = now.isoformat()
        updated["acknowledged_failure_fingerprint"] = ""
    return updated


def send_slack_alerts(
    *,
    config: TestMonitorConfig,
    alerts: list[PlannedAlert],
    post_message: Callable[[str], None] | None = None,
) -> list[str]:
    if not alerts or not config.slack_enabled:
        return []
    if post_message is None:
        client = SlackWebhookClient(
            webhook_url=config.slack_webhook_url,
            timeout_seconds=config.slack_timeout_seconds,
        )
        post_message = client.post_message

    sent: list[str] = []
    for alert in alerts:
        try:
            post_message(alert.text)
        except SlackNotificationError:
            raise
        sent.append(alert.kind)
    return sent


def build_failure_fingerprint(result: TestRunResult) -> str:
    digest = hashlib.sha256()
    digest.update(str(result.exit_code).encode("utf-8"))
    digest.update(b"\n")
    digest.update(tail_output(result.output, line_limit=80).encode("utf-8"))
    return digest.hexdigest()


def tail_output(output: str, *, line_limit: int) -> str:
    lines = str(output or "").splitlines()
    return "\n".join(lines[-max(1, line_limit) :]).strip()


def _failure_message(
    *,
    kind: str,
    fingerprint: str,
    result: TestRunResult,
    config: TestMonitorConfig,
    output_tail: str,
) -> str:
    unit_status = str((result.checks.get("unit_tests") or {}).get("status", "")).lower()
    ops_status = str((result.checks.get("operations_store") or {}).get("status", "")).lower()
    scheduler_status = str(
        (result.checks.get("scheduler_freshness") or {}).get("status", "")
    ).lower()
    if unit_status == "pass" and ops_status == "fail":
        heading = (
            "Centaur monitor runtime issue"
            if kind == "failed"
            else "Centaur monitor runtime issue is still unresolved"
        )
    elif unit_status == "pass" and scheduler_status == "fail":
        heading = (
            "Centaur scheduler freshness check failed"
            if kind == "failed"
            else "Centaur scheduler freshness check is still failing"
        )
    else:
        heading = (
            "Centaur test monitor failed"
            if kind == "failed"
            else "Centaur test monitor is still failing"
        )
    command = " ".join(shlex.quote(item) for item in config.command)
    tail = output_tail or "(no test output captured)"
    lines = [
        f"{heading}: exit={result.exit_code}, fingerprint={fingerprint[:12]}, duration={result.duration_seconds:.1f}s.",
        f"Command: {command}",
    ]
    if unit_status == "pass" and ops_status == "fail":
        lines.append(
            "Tests passed, but scheduler freshness check failed because PostgreSQL operations store is unavailable."
        )
    else:
        unit_summary = str((result.checks.get("unit_tests") or {}).get("summary", "") or "")
        ops_summary = str((result.checks.get("operations_store") or {}).get("summary", "") or "")
        scheduler_summary = str((result.checks.get("scheduler_freshness") or {}).get("summary", "") or "")
        if unit_summary:
            lines.append(f"Unit tests: {unit_summary}")
        if ops_summary:
            lines.append(f"Operations store: {ops_summary}")
        if scheduler_summary:
            lines.append(f"Scheduler freshness: {scheduler_summary}")
    lines.extend(
        [
            "Reset reminders for this exact failure with: scripts/run_test_monitor.py --reset-failure-notification",
            f"Last output:\n{tail}",
        ]
    )
    return "\n".join(lines)


def _resolve_project_path(project_root: Path, value: str) -> Path:
    path = Path(str(value or "").strip())
    if path.is_absolute():
        return path
    return project_root / path


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _parse_datetime(str(value or ""))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_age(*, seconds: int) -> str:
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes}m{remaining_seconds}s"
    if minutes:
        return f"{minutes}m{remaining_seconds}s"
    return f"{remaining_seconds}s"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
