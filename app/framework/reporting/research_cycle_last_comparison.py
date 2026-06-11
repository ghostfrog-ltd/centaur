from __future__ import annotations

from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ResearchCycleLastComparisonReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        launchd_only: bool = False,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.launchd_only = bool(launchd_only)

    def build_report(self) -> dict[str, Any]:
        rows = self.usage_ledger.list_recent_tick_runs(limit=500)
        heartbeat_rows = {
            str(row.get("tick_id", "")): row
            for row in rows
            if isinstance((row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}), dict)
            and "heartbeat" in (row.get("state_snapshot_json", {}) or {})
        }
        forced_row = None
        launchd_row = None
        simulated_row = None
        for row in rows:
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if (
                str(run.get("pipeline", "") or "") != "research_cycle"
                or str(run.get("source", "") or "") != "real_heartbeat"
            ):
                continue
            origin = self._row_origin(row=row, heartbeat_rows=heartbeat_rows)
            if origin == "forced_one_shot" and forced_row is None:
                forced_row = row
            elif origin == "launchd_scheduled" and launchd_row is None:
                launchd_row = row
            elif origin == "simulated_natural" and simulated_row is None:
                simulated_row = row
            if forced_row is not None and launchd_row is not None and simulated_row is not None:
                break
        natural_status = "not_found"
        natural_cycle = {}
        if launchd_row is not None:
            natural_status = "found"
            natural_cycle = self._cycle_snapshot(row=launchd_row, heartbeat_rows=heartbeat_rows)
        elif simulated_row is not None and not self.launchd_only:
            natural_status = "simulated_only"
            natural_cycle = self._cycle_snapshot(row=simulated_row, heartbeat_rows=heartbeat_rows)
        return {
            "force_mode_changes_anything_besides_interval_due_state": False,
            "forced_cycle": self._cycle_snapshot(row=forced_row, heartbeat_rows=heartbeat_rows),
            "natural_cycle_status": natural_status,
            "natural_cycle": natural_cycle,
            "real_launchd_cycle_status": "found" if launchd_row is not None else "missing",
            "real_launchd_cycle": self._cycle_snapshot(row=launchd_row, heartbeat_rows=heartbeat_rows),
            "simulated_cycle_status": "found" if simulated_row is not None else "missing",
            "simulated_cycle": self._cycle_snapshot(row=simulated_row, heartbeat_rows=heartbeat_rows),
        }

    def render(self) -> str:
        report = self.build_report()
        lines = [
            "Research Cycle Last Comparison",
            "force_mode_changes_anything_besides_interval_due_state="
            + ("yes" if report.get("force_mode_changes_anything_besides_interval_due_state") else "no"),
            f"real_launchd_cycle_status={report.get('real_launchd_cycle_status', 'missing')}",
        ]
        if not self.launchd_only:
            lines.append(f"simulated_cycle_status={report.get('simulated_cycle_status', 'missing')}")
        lines.extend(self._render_cycle("forced", dict(report.get("forced_cycle", {}) or {}), status_override=None))
        lines.extend(
            self._render_cycle(
                "natural",
                dict(report.get("natural_cycle", {}) or {}),
                status_override=str(report.get("natural_cycle_status", "not_found") or "not_found"),
            )
        )
        return "\n".join(lines)

    def _render_cycle(
        self,
        label: str,
        cycle: dict[str, Any],
        *,
        status_override: str | None,
    ) -> list[str]:
        status = status_override or ("found" if cycle else "not_found")
        lines = [f"{label}_cycle_status={status}"]
        if not cycle:
            return lines
        lines.extend(
            [
                f"{label}_cycle_id={cycle.get('cycle_id', '-') or '-'}",
                f"{label}_cycle_origin={cycle.get('cycle_origin', '-') or '-'}",
                f"{label}_parent_heartbeat_tick_id={cycle.get('parent_heartbeat_tick_id', '-') or '-'}",
                f"{label}_parent_process_mode={cycle.get('parent_process_mode', '-') or '-'}",
                f"{label}_command_source={cycle.get('command_source', '-') or '-'}",
                f"{label}_force_mode={'yes' if cycle.get('force_mode') else 'no'}",
                f"{label}_started_at={cycle.get('started_at', '-') or '-'}",
                f"{label}_replay_timeframes={','.join(cycle.get('replay_timeframes', []) or ['-'])}",
                f"{label}_days={cycle.get('days', '-')}",
                f"{label}_max_timestamps={cycle.get('max_timestamps', '-')}",
                f"{label}_selected_symbol_universe={cycle.get('selected_symbol_universe_text', '-') or '-'}",
                f"{label}_latest_available_historical_bar_at={cycle.get('latest_available_historical_bar_at', '-') or '-'}",
                f"{label}_max_required_future_horizon={cycle.get('max_required_future_horizon', '-') or '-'}",
                f"{label}_latest_valid_replay_window_end={cycle.get('latest_valid_replay_window_end', '-') or '-'}",
                f"{label}_candidate_windows_found={int(cycle.get('candidate_windows_found', 0) or 0)}",
                f"{label}_candidate_windows_accepted={int(cycle.get('candidate_windows_accepted', 0) or 0)}",
                f"{label}_candidate_windows_rejected={int(cycle.get('candidate_windows_rejected', 0) or 0)}",
                f"{label}_rejection_reasons={','.join(cycle.get('rejection_reasons', []) or ['none'])}",
                f"{label}_config_sources={cycle.get('config_sources_text', '-') or '-'}",
            ]
        )
        for item in cycle.get("replay_timeframe_rows", []) or []:
            lines.append(
                f"{label}_timeframe="
                f"timeframe={item.get('timeframe', '-')}"
                f" | days={item.get('days', '-')}"
                f" | max_timestamps={item.get('max_timestamps', '-')}"
                f" | latest_available_historical_bar_at={item.get('latest_available_historical_bar_at', '-') or '-'}"
                f" | max_required_future_horizon={item.get('max_required_future_horizon', '-') or '-'}"
                f" | latest_valid_replay_window_end={item.get('latest_valid_replay_window_end', '-') or '-'}"
            )
        for item in cycle.get("accepted_windows", []) or []:
            lines.append(
                f"{label}_accepted_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
            )
        for item in cycle.get("rejected_windows", []) or []:
            lines.append(
                f"{label}_rejected_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        return lines

    def _cycle_snapshot(
        self,
        *,
        row: dict[str, Any] | None,
        heartbeat_rows: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not row:
            return {}
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
        parent_tick_id = str(run.get("parent_tick_id", "") or "")
        setting_sources = dict(run.get("replay_setting_sources", {}) or {})
        coverage = dict(state.get("timeframe_historical_coverage", {}) or {})
        replay_timeframes = list(state.get("timeframes_used", []) or [])
        skipped = list(state.get("timeframes_skipped", []) or [])
        replay_timeframes.extend(
            str(item.get("timeframe", "") or "")
            for item in skipped
            if str(item.get("timeframe", "") or "")
        )
        ordered_timeframes: list[str] = []
        for timeframe in replay_timeframes:
            if timeframe and timeframe not in ordered_timeframes:
                ordered_timeframes.append(timeframe)
        selected_universe = dict(
            state.get("selected_symbol_universe", {}) or run.get("selected_symbol_universe", {}) or {}
        )
        config_sources_text = ",".join(
            f"{name}:{str((details or {}).get('source', '-') or '-')}"
            for name, details in sorted(setting_sources.items())
        )
        rejection_reasons = sorted(
            {
                str(item.get("reason", "") or "").strip()
                for item in list(state.get("replay_window_rejections", []) or [])
                if str(item.get("reason", "") or "").strip()
            }
            | {
                str(item.get("reason", "") or "").strip()
                for item in skipped
                if str(item.get("reason", "") or "").strip()
            }
        )
        origin = self._row_origin(row=row, heartbeat_rows=heartbeat_rows)
        return {
            "cycle_id": str(run.get("research_cycle_id", "") or row.get("tick_id", "")),
            "cycle_origin": origin,
            "parent_heartbeat_tick_id": parent_tick_id,
            "parent_process_mode": str(run.get("parent_process_mode", "") or "-"),
            "command_source": str(run.get("command_source", "") or "-"),
            "force_mode": bool(run.get("force_mode")),
            "started_at": str(run.get("research_started_at", "") or row.get("started_at", "") or ""),
            "replay_timeframes": ordered_timeframes,
            "days": int(run.get("days", 0) or 0),
            "max_timestamps": int(run.get("max_replay_timestamps", 0) or 0),
            "selected_symbol_universe_text": (
                f"equity={','.join(selected_universe.get('equity', []) or ['-'])};"
                f"crypto={','.join(selected_universe.get('crypto', []) or ['-'])}"
            ),
            "latest_available_historical_bar_at": str(state.get("latest_available_historical_bar_at", "") or "-"),
            "max_required_future_horizon": str(state.get("max_required_future_horizon", "") or "-"),
            "latest_valid_replay_window_end": str(state.get("latest_valid_replay_window_end", "") or "-"),
            "candidate_windows_found": int(
                state.get("replay_window_candidate_count", len(state.get("replay_window_candidates", []) or []))
                or 0
            ),
            "candidate_windows_accepted": int(state.get("replay_windows_accepted_count", 0) or 0),
            "candidate_windows_rejected": int(state.get("replay_windows_rejected_count", 0) or 0),
            "rejection_reasons": rejection_reasons,
            "config_sources_text": config_sources_text or "-",
            "replay_timeframe_rows": [
                {
                    "timeframe": timeframe,
                    "days": int(run.get("days", 0) or 0),
                    "max_timestamps": int(run.get("max_replay_timestamps", 0) or 0),
                    "latest_available_historical_bar_at": str(
                        (coverage.get(timeframe, {}) or {}).get("latest_available_historical_bar_at", "") or "-"
                    ),
                    "max_required_future_horizon": str(
                        (coverage.get(timeframe, {}) or {}).get("max_required_future_horizon", "") or "-"
                    ),
                    "latest_valid_replay_window_end": str(
                        (coverage.get(timeframe, {}) or {}).get("latest_valid_replay_window_end", "") or "-"
                    ),
                }
                for timeframe in ordered_timeframes
            ],
            "accepted_windows": list(state.get("replay_window_acceptances", []) or []),
            "rejected_windows": list(state.get("replay_window_rejections", []) or []),
        }

    def _row_origin(
        self,
        *,
        row: dict[str, Any],
        heartbeat_rows: dict[str, dict[str, Any]],
    ) -> str:
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        explicit = str(run.get("cycle_origin", "") or "").strip()
        if explicit:
            return explicit
        parent_tick_id = str(run.get("parent_tick_id", "") or "")
        if parent_tick_id.startswith("sim-"):
            return "simulated_natural"
        heartbeat_row = heartbeat_rows.get(parent_tick_id, {})
        heartbeat = (
            ((heartbeat_row or {}).get("state_snapshot_json", {}) or {}).get("heartbeat", {})
            if isinstance(heartbeat_row, dict)
            else {}
        )
        autonomous = dict((heartbeat or {}).get("autonomous_learning", {}) or {})
        if bool(autonomous.get("forced_research_cycle")):
            return "forced_one_shot"
        if parent_tick_id and parent_tick_id.replace("-", "").isdigit():
            return "launchd_scheduled"
        return "manual_cli"
