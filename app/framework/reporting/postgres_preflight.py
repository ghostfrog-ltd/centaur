from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import plistlib
from typing import Any
from urllib.parse import urlparse

from app.framework.runtime.models import TickReport
from app.framework.runtime.settings import DEFAULT_ENV_PATH, PROJECT_ROOT, load_runtime_config
from app.framework.storage.usage import UsageLedger


class PostgresPreflightReport:
    """Render a read-only-ish PostgreSQL runtime diagnostics report.

    The only intentional write is an optional diagnostic tick-row probe when a
    PostgreSQL-backed operations ledger is available.
    """

    def build_report(self) -> dict[str, Any]:
        env_file = DEFAULT_ENV_PATH
        env_file_exists = env_file.exists()
        env_values = self._read_env_file(env_file)
        config = load_runtime_config()
        parsed_url = urlparse(str(config.database_url or ""))
        report: dict[str, Any] = {
            "cwd": str(Path.cwd()),
            "project_root": str(PROJECT_ROOT),
            "env_file_loaded": bool(env_file_exists),
            "env_file_path": str(env_file),
            "runtime_requires_postgres": self._runtime_requires_postgres(config),
            "why_sqlite_fallback_is_refused": self._why_sqlite_fallback_is_refused(config),
            "env_key_presence": self._env_key_presence(config=config, env_values=env_values),
            "database_host": parsed_url.hostname or str(os.getenv("POSTGRES_HOST", "") or ""),
            "database_port": parsed_url.port or str(os.getenv("POSTGRES_PORT", "5432") or "5432"),
            "database_name": parsed_url.path.lstrip("/") or str(os.getenv("POSTGRES_DB", "") or ""),
            "database_user": parsed_url.username or str(os.getenv("POSTGRES_USER", "") or ""),
            "launchd": self._launchd_diagnostics(),
        }

        ledger = None
        ledger_error = ""
        try:
            ledger = UsageLedger(config=config)
            report["selected_storage_backend"] = str(ledger.backend)
            report["selected_storage_backend_detail"] = str(ledger.backend_detail)
        except Exception as exc:
            ledger_error = f"{type(exc).__name__}: {exc}"
            report["selected_storage_backend"] = "unavailable"
            report["selected_storage_backend_detail"] = ledger_error

        connection_ok = False
        operations_tables_exist = False
        latest_tick_read_ok = False
        test_snapshot_roundtrip_ok = False
        latest_tick_error = ""
        snapshot_error = ""
        tables_error = ""
        if ledger is not None and ledger.backend == "postgres":
            try:
                connection_ok = True
                operations_tables_exist, tables_error = self._check_required_tables(ledger)
                try:
                    latest_tick = ledger.get_latest_tick_run()
                    latest_tick_read_ok = latest_tick is not None or operations_tables_exist
                except Exception as exc:
                    latest_tick_error = f"{type(exc).__name__}: {exc}"
                try:
                    test_snapshot_roundtrip_ok = self._write_and_read_probe_tick(ledger)
                except Exception as exc:
                    snapshot_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                connection_ok = False
                ledger_error = f"{type(exc).__name__}: {exc}"

        report["postgres_connection_succeeds"] = connection_ok
        report["required_operations_tables_exist"] = operations_tables_exist
        report["required_operations_tables_error"] = tables_error
        report["latest_control_tick_readable"] = latest_tick_read_ok
        report["latest_control_tick_error"] = latest_tick_error or ledger_error
        report["test_heartbeat_snapshot_roundtrip_ok"] = test_snapshot_roundtrip_ok
        report["test_heartbeat_snapshot_error"] = snapshot_error
        return report

    def render(self, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        launchd = dict(report.get("launchd", {}) or {})
        lines = [
            "Centaur PostgreSQL Preflight",
            f"current_working_directory={report.get('cwd', '-')}",
            f"project_root={report.get('project_root', '-')}",
            f"env_file_loaded={'yes' if report.get('env_file_loaded') else 'no'}",
            f"environment_file={report.get('env_file_path', '-')}",
            f"runtime_requires_postgres={'yes' if report.get('runtime_requires_postgres') else 'no'}",
            f"selected_storage_backend={report.get('selected_storage_backend', '-')}",
            f"selected_storage_backend_detail={report.get('selected_storage_backend_detail', '-')}",
            f"database_host={report.get('database_host', '-') or '-'}",
            f"database_port={report.get('database_port', '-') or '-'}",
            f"database_name={report.get('database_name', '-') or '-'}",
            f"database_user={report.get('database_user', '-') or '-'}",
            f"postgres_connection_succeeds={'yes' if report.get('postgres_connection_succeeds') else 'no'}",
            f"required_operations_tables_exist={'yes' if report.get('required_operations_tables_exist') else 'no'}",
            f"latest_control_tick_readable={'yes' if report.get('latest_control_tick_readable') else 'no'}",
            f"test_heartbeat_snapshot_roundtrip_ok={'yes' if report.get('test_heartbeat_snapshot_roundtrip_ok') else 'no'}",
            f"why_sqlite_fallback_is_refused={report.get('why_sqlite_fallback_is_refused', '-')}",
            "env_config_key_presence:",
        ]
        for key, value in sorted((report.get("env_key_presence", {}) or {}).items()):
            lines.append(f"- {key}={'present' if value else 'missing'}")
        if report.get("required_operations_tables_error"):
            lines.append(
                f"required_operations_tables_error={report.get('required_operations_tables_error')}"
            )
        if report.get("latest_control_tick_error"):
            lines.append(f"latest_control_tick_error={report.get('latest_control_tick_error')}")
        if report.get("test_heartbeat_snapshot_error"):
            lines.append(
                f"test_heartbeat_snapshot_error={report.get('test_heartbeat_snapshot_error')}"
            )
        lines.extend(
            [
                "launchd_diagnostics:",
                f"- plist_path={launchd.get('plist_path', '-')}",
                f"- program_arguments={launchd.get('program_arguments', [])}",
                f"- working_directory={launchd.get('working_directory', '-')}",
                f"- environment_variables={launchd.get('environment_variables', {})}",
                f"- wrapper_log_path={launchd.get('wrapper_log_path', '-')}",
                f"- runtime_log_path={launchd.get('runtime_log_path', '-')}",
                f"- dotenv_loading_mode={launchd.get('dotenv_loading_mode', '-')}",
            ]
        )
        return "\n".join(lines)

    def _runtime_requires_postgres(self, config: Any) -> bool:
        preference = str(getattr(config, "operations_db_backend_preference", "") or "").strip().lower()
        return bool(
            getattr(config, "paper_execution_enabled", False)
            or getattr(config, "live_execution_enabled", False)
            or preference == "postgres"
            or getattr(config, "postgres_configured", False)
        )

    def _why_sqlite_fallback_is_refused(self, config: Any) -> str:
        reasons: list[str] = []
        if bool(getattr(config, "paper_execution_enabled", False)):
            reasons.append("paper_execution_enabled")
        if bool(getattr(config, "live_execution_enabled", False)):
            reasons.append("live_execution_enabled")
        if str(getattr(config, "operations_db_backend_preference", "") or "").strip().lower() == "postgres":
            reasons.append("operations_db_backend_preference=postgres")
        if bool(getattr(config, "postgres_configured", False)):
            reasons.append("postgres_configured")
        return ",".join(reasons) or "sqlite_fallback_allowed"

    def _env_key_presence(self, *, config: Any, env_values: dict[str, str]) -> dict[str, bool]:
        keys = [
            "DATABASE_URL",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_SCHEMA",
            "POSTGRES_CORE_SCHEMA",
            "POSTGRES_PAPER_SCHEMA",
            "POSTGRES_LIVE_SCHEMA",
            "OPERATIONS_DB_BACKEND_PREFERENCE",
            "RESEARCH_CYCLE_ENABLED",
            "SLACK_ALERTS_ENABLED",
        ]
        presence = {key: bool(str(os.getenv(key, "") or "").strip()) for key in keys}
        presence[".env_exists"] = bool(env_values)
        presence["runtime_database_url_resolved"] = bool(getattr(config, "database_url", ""))
        return presence

    def _read_env_file(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        loaded: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            loaded[key.strip()] = value.strip()
        return loaded

    def _check_required_tables(self, ledger: UsageLedger) -> tuple[bool, str]:
        probes = [
            ("tick_runs", lambda: ledger.list_recent_tick_runs(limit=1)),
            (
                "research_cycle_decisions",
                lambda: ledger.list_latest_research_cycle_decisions(),
            ),
            ("strategy_promotions", lambda: ledger.list_strategy_promotions()),
            (
                "attention_alerts",
                lambda: ledger.list_due_attention_alerts(due_at=datetime.now().astimezone()),
            ),
            (
                "shadow_trade_proposals",
                lambda: ledger.list_recent_shadow_trade_proposals(limit=1),
            ),
            (
                "strategy_fitness_snapshots",
                lambda: ledger.list_latest_strategy_fitness_snapshots(limit=1),
            ),
        ]
        failures: list[str] = []
        for name, probe in probes:
            try:
                probe()
            except Exception as exc:
                failures.append(f"{name} ({type(exc).__name__}: {exc})")
        if failures:
            return False, f"missing tables or unreadable surfaces: {', '.join(failures)}"
        return True, ""

    def _write_and_read_probe_tick(self, ledger: UsageLedger) -> bool:
        now = datetime.now().astimezone()
        tick_id = f"postgres-preflight-{now.strftime('%Y%m%d-%H%M%S-%f')}"
        report = TickReport(
            tick_id=tick_id,
            status="ok",
            started_at=now,
            ended_at=now,
            duration_seconds=0.0,
            state_snapshot={"postgres_preflight": {"probe": True}},
            operations_backend=ledger.backend,
            operations_backend_detail=ledger.backend_detail,
        )
        ledger.record_tick_run(report)
        row = ledger.get_tick_run(tick_id=tick_id)
        return bool(row) and str((row or {}).get("tick_id", "")) == tick_id

    def _launchd_diagnostics(self) -> dict[str, Any]:
        plist_path = PROJECT_ROOT / "ops" / "com.ghostfrog.centaur.control.plist"
        if not plist_path.exists():
            return {
                "plist_path": str(plist_path),
                "program_arguments": [],
                "working_directory": "",
                "environment_variables": {},
                "wrapper_log_path": str(Path.home() / "centaur_control_wrapper.log"),
                "runtime_log_path": str(Path.home() / ".centaur" / "runtime" / "control_tick.log"),
                "dotenv_loading_mode": "python_startup_load_runtime_config",
            }
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
        return {
            "plist_path": str(plist_path),
            "program_arguments": list(payload.get("ProgramArguments", []) or []),
            "working_directory": str(payload.get("WorkingDirectory", "") or ""),
            "environment_variables": dict(payload.get("EnvironmentVariables", {}) or {}),
            "wrapper_log_path": str(Path.home() / "centaur_control_wrapper.log"),
            "runtime_log_path": str(Path.home() / ".centaur" / "runtime" / "control_tick.log"),
            "dotenv_loading_mode": "python_startup_load_runtime_config",
        }
