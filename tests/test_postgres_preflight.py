from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.framework.reporting.postgres_preflight import PostgresPreflightReport
from app.framework.storage.usage import UsageLedger


class PostgresPreflightTests(unittest.TestCase):
    def test_render_shows_required_diagnostics_without_database_url_secret(self) -> None:
        reporter = PostgresPreflightReport()
        rendered = reporter.render(
            {
                "cwd": "/tmp/demo",
                "project_root": "/repo",
                "env_file_loaded": True,
                "env_file_path": "/repo/.env",
                "runtime_requires_postgres": True,
                "selected_storage_backend": "unavailable",
                "selected_storage_backend_detail": "RuntimeError: DATABASE_URL not set",
                "database_host": "localhost",
                "database_port": "5432",
                "database_name": "centaur",
                "database_user": "gary",
                "postgres_connection_succeeds": False,
                "required_operations_tables_exist": False,
                "latest_control_tick_readable": False,
                "test_heartbeat_snapshot_roundtrip_ok": False,
                "why_sqlite_fallback_is_refused": "operations_db_backend_preference=postgres",
                "env_key_presence": {
                    "DATABASE_URL": False,
                    "POSTGRES_PASSWORD": True,
                },
                "launchd": {
                    "plist_path": "/repo/ops/com.ghostfrog.centaur.control.plist",
                    "program_arguments": ["/Users/test/.centaur/run_control_tick.sh"],
                    "working_directory": "/repo",
                    "environment_variables": {},
                    "wrapper_log_path": "/Users/test/centaur_control_wrapper.log",
                    "runtime_log_path": "/Users/test/.centaur/runtime/control_tick.log",
                    "dotenv_loading_mode": "python_startup_load_runtime_config",
                },
            }
        )

        self.assertIn("current_working_directory=/tmp/demo", rendered)
        self.assertIn("database_host=localhost", rendered)
        self.assertIn("database_user=gary", rendered)
        self.assertIn("POSTGRES_PASSWORD=present", rendered)
        self.assertNotIn("postgresql://", rendered)

    def test_usage_ledger_missing_config_error_lists_exact_missing_keys(self) -> None:
        ledger = UsageLedger.__new__(UsageLedger)
        ledger.config = SimpleNamespace(
            paper_execution_enabled=False,
            live_execution_enabled=False,
            operations_db_backend_preference="postgres",
            postgres_configured=False,
            database_url="",
        )

        message = ledger._build_postgres_missing_config_error()

        self.assertIn("DATABASE_URL not set", message)
        self.assertIn("POSTGRES_HOST not set", message)
        self.assertIn("Refusing SQLite fallback", message)


if __name__ == "__main__":
    unittest.main()
