from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.framework.engine.threshold_advisor_worker import (
    ThresholdAdvisorWorkerPaths,
    request_threshold_advisor_update,
)


class ThresholdAdvisorWorkerTests(unittest.TestCase):
    def test_disabled_worker_does_not_spawn(self) -> None:
        with TemporaryDirectory() as temp_dir:
            paths = ThresholdAdvisorWorkerPaths(root=Path(temp_dir))
            result = request_threshold_advisor_update(
                tick_id="tick-1",
                requested_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
                current_signal_preview=[],
                paths=paths,
                enabled=False,
            )

            self.assertEqual(result["worker_status"], "disabled")
            self.assertFalse(result["worker_started"])
            self.assertEqual(result["trade_authority"], "none")
            self.assertFalse(paths.request_path.exists())

    def test_enabled_worker_writes_request_and_spawns_once(self) -> None:
        with TemporaryDirectory() as temp_dir:
            paths = ThresholdAdvisorWorkerPaths(root=Path(temp_dir))
            fake_process = SimpleNamespace(pid=4242)

            with (
                patch(
                    "app.framework.engine.threshold_advisor_worker.subprocess.Popen",
                    return_value=fake_process,
                ) as popen,
                patch(
                    "app.framework.engine.threshold_advisor_worker._pid_is_running",
                    return_value=True,
                ),
            ):
                first = request_threshold_advisor_update(
                    tick_id="tick-1",
                    requested_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
                    current_signal_preview=[{"symbol": "AAPL"}],
                    paths=paths,
                    enabled=True,
                )
                second = request_threshold_advisor_update(
                    tick_id="tick-2",
                    requested_at=datetime(2026, 6, 4, 12, 0, 30, tzinfo=timezone.utc),
                    current_signal_preview=[{"symbol": "MSFT"}],
                    paths=paths,
                    enabled=True,
                )

            self.assertEqual(first["worker_status"], "started")
            self.assertEqual(first["worker_pid"], 4242)
            self.assertEqual(second["worker_status"], "already_running")
            self.assertEqual(second["worker_pid"], 4242)
            self.assertEqual(popen.call_count, 1)
            self.assertTrue(paths.request_path.exists())
            self.assertTrue(paths.worker_lock_path.exists())


if __name__ == "__main__":
    unittest.main()
