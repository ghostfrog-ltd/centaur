from __future__ import annotations

from dataclasses import dataclass
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
    slack_enabled: bool
    slack_webhook_url: str
    slack_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class TestRunResult:
    exit_code: int
    output: str
    duration_seconds: float

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
    heading = (
        "Centaur test monitor failed"
        if kind == "failed"
        else "Centaur test monitor is still failing"
    )
    command = " ".join(shlex.quote(item) for item in config.command)
    tail = output_tail or "(no test output captured)"
    return (
        f"{heading}: exit={result.exit_code}, fingerprint={fingerprint[:12]}, "
        f"duration={result.duration_seconds:.1f}s.\n"
        f"Command: {command}\n"
        "Reset reminders for this exact failure with: "
        "scripts/run_test_monitor.py --reset-failure-notification\n"
        f"Last output:\n{tail}"
    )


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
