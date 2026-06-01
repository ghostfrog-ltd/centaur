from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.runtime.test_monitor import (
    TestMonitorConfig,
    TestRunResult,
    build_failure_fingerprint,
    mark_alerts_sent,
    plan_state_update,
    reset_failure_notification,
)


class TestMonitorTests(unittest.TestCase):
    def test_first_failure_plans_slack_alert(self) -> None:
        state, alerts = plan_state_update(
            previous_state={},
            result=self._failed_result("FAILED test_strategy_registry"),
            config=self._config(),
            now=self._now(),
        )

        self.assertEqual(state["last_status"], "failed")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, "failed")
        self.assertIn("Reset reminders", alerts[0].text)

    def test_still_failing_waits_for_reminder_interval(self) -> None:
        config = self._config()
        failed = self._failed_result("FAILED test_strategy_registry")
        now = self._now()
        state, alerts = plan_state_update(
            previous_state={},
            result=failed,
            config=config,
            now=now,
        )
        self.assertEqual(len(alerts), 1)
        state = mark_alerts_sent(state=state, alerts=alerts, now=now)

        _, early_alerts = plan_state_update(
            previous_state=state,
            result=failed,
            config=config,
            now=now + timedelta(minutes=30),
        )
        self.assertEqual(early_alerts, [])

        _, later_alerts = plan_state_update(
            previous_state=state,
            result=failed,
            config=config,
            now=now + timedelta(minutes=61),
        )
        self.assertEqual(len(later_alerts), 1)
        self.assertEqual(later_alerts[0].kind, "still_failed")

    def test_reset_silences_same_failure_fingerprint(self) -> None:
        config = self._config()
        failed = self._failed_result("FAILED test_strategy_registry")
        fingerprint = build_failure_fingerprint(failed)
        state = {
            "current_failure_fingerprint": fingerprint,
            "last_status": "failed",
        }

        reset_state = reset_failure_notification(state=state, now=self._now())
        _, alerts = plan_state_update(
            previous_state=reset_state,
            result=failed,
            config=config,
            now=self._now() + timedelta(hours=2),
        )

        self.assertEqual(alerts, [])
        self.assertEqual(
            reset_state["acknowledged_failure_fingerprint"],
            fingerprint,
        )

    def test_recovery_alert_clears_active_failure(self) -> None:
        state, alerts = plan_state_update(
            previous_state={
                "last_status": "failed",
                "current_failure_fingerprint": "abc123",
            },
            result=TestRunResult(exit_code=0, output="OK", duration_seconds=0.4),
            config=self._config(),
            now=self._now(),
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, "recovered")
        self.assertEqual(state["last_status"], "passed")
        self.assertEqual(state["current_failure_fingerprint"], "")

    def _failed_result(self, output: str) -> TestRunResult:
        return TestRunResult(exit_code=1, output=output, duration_seconds=0.5)

    def _config(self) -> TestMonitorConfig:
        temp_root = Path(tempfile.gettempdir())
        return TestMonitorConfig(
            enabled=True,
            command=("python", "-m", "unittest", "discover", "tests"),
            state_path=temp_root / "centaur-test-monitor-state.json",
            log_path=temp_root / "centaur-test-monitor.log",
            reminder_minutes=60,
            output_tail_lines=20,
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.test/services/example",
            slack_timeout_seconds=5,
        )

    def _now(self) -> datetime:
        return datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
