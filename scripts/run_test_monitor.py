#!/Volumes/Bob/www/ghostfrog-centaur/.venv-mac/bin/python
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.framework.runtime.slack import SlackNotificationError
from app.framework.runtime.settings import load_runtime_config
from app.framework.runtime.test_monitor import (
    append_scheduler_freshness_check,
    append_monitor_log,
    load_dotenv,
    load_state,
    load_test_monitor_config,
    mark_alerts_sent,
    plan_state_update,
    reset_failure_notification,
    run_test_command,
    send_slack_alerts,
    write_state,
)
from app.framework.storage.usage import UsageLedger


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and monitor the Centaur unit suite.")
    parser.add_argument(
        "--reset-failure-notification",
        action="store_true",
        help="Acknowledge the current failure fingerprint and stop reminders until it changes.",
    )
    args = parser.parse_args()

    dotenv = load_dotenv(PROJECT_ROOT / ".env")
    environ = {**dotenv, **os.environ}
    config = load_test_monitor_config(project_root=PROJECT_ROOT, environ=environ)
    now = datetime.now(timezone.utc)

    if args.reset_failure_notification:
        state = reset_failure_notification(
            state=load_state(config.state_path),
            now=now,
        )
        write_state(config.state_path, state)
        append_monitor_log(
            config.log_path,
            f"[{now.isoformat()}] reset current failure notification",
        )
        print(f"Reset test monitor notification state at {config.state_path}")
        return 0

    if not config.enabled:
        append_monitor_log(config.log_path, f"[{now.isoformat()}] monitor disabled")
        return 0

    try:
        result = run_test_command(command=config.command, cwd=PROJECT_ROOT)
        latest_tick = None
        scheduler_check_error = ""
        if config.scheduler_freshness_enabled:
            try:
                runtime_config = load_runtime_config()
                latest_tick = UsageLedger(config=runtime_config).get_latest_tick_run()
            except Exception as exc:
                scheduler_check_error = f"{type(exc).__name__}: {exc}"
        result = append_scheduler_freshness_check(
            result=result,
            config=config,
            latest_tick=latest_tick,
            now=now,
            check_error=scheduler_check_error,
        )
        state, alerts = plan_state_update(
            previous_state=load_state(config.state_path),
            result=result,
            config=config,
            now=now,
        )
        sent_kinds: list[str] = []
        try:
            sent_kinds = send_slack_alerts(config=config, alerts=alerts)
        except SlackNotificationError as exc:
            append_monitor_log(
                config.log_path,
                f"[{now.isoformat()}] slack send failed: {exc}",
            )
        if sent_kinds:
            state = mark_alerts_sent(state=state, alerts=alerts, now=now)
        write_state(config.state_path, state)
        append_monitor_log(
            config.log_path,
            (
                f"[{now.isoformat()}] exit={result.exit_code} "
                f"alerts_planned={len(alerts)} alerts_sent={len(sent_kinds)}"
            ),
        )
        if result.output:
            append_monitor_log(config.log_path, result.output)
        return result.exit_code
    except Exception:
        append_monitor_log(
            config.log_path,
            f"[{now.isoformat()}] monitor crashed\n{traceback.format_exc()}",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
