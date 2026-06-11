from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import sys
from time import monotonic
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

ALLOWED_REAL_SOURCES = {"real_heartbeat"}
ALLOWED_REAL_ORIGINS = {"launchd_scheduled", "real_heartbeat", "forced_one_shot"}


class OutcomeRecordingStatusReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=True,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )

    def build_report(self, *, lookback_hours: int = 24) -> dict[str, Any]:
        started = monotonic()
        self._log_report_phase("build_report", "start")
        cycles = self._real_research_cycles(limit=200)
        latest_cycle = cycles[0] if cycles else None
        if latest_cycle is None:
            result = {"status": "not_found", "reason": "No persisted real research cycle is available yet."}
            self._log_report_phase("build_report", "done", elapsed_ms=int((monotonic() - started) * 1000))
            return result
        as_of = datetime.now().astimezone()
        lookback_start = as_of - timedelta(hours=max(1, int(lookback_hours or 24)))
        latest_cycle_id = str(latest_cycle.get("tick_id", "") or "")
        latest_cycle_decisions = self.usage_ledger.list_research_cycle_decisions(cycle_id=latest_cycle_id, limit=500)
        recent_cycles = [item for item in cycles if self._started_at(item) >= lookback_start]
        replay_run_ids = self._collect_replay_run_ids(recent_cycles)
        replay_rows = self._load_replay_checkpoint_rows(replay_run_ids=replay_run_ids)
        latest_run_ids = self._collect_replay_run_ids([latest_cycle])
        latest_replay_rows = [row for row in replay_rows if str(row.get("replay_run_id", "")) in latest_run_ids]
        heartbeat_steps = self._recent_heartbeat_outcome_steps(limit=50)
        latest_heartbeat = heartbeat_steps[0] if heartbeat_steps else {}

        replay_summary = self._summarize_replay_rows(rows=replay_rows, as_of=as_of)
        latest_groups = self._latest_cycle_groups(decisions=latest_cycle_decisions, replay_rows=latest_replay_rows)
        liquidity_probe = self._find_group(latest_groups, "liquidity_probe.steady_flow", "steady_flow", "15Min")
        hour_zero_sample = [
            item
            for item in latest_groups
            if str(item.get("timeframe", "")) == "1Hour" and int(item.get("sample_size_actual", 0) or 0) <= 0
        ]
        verdict = self._final_verdict(
            latest_groups=latest_groups,
            replay_summary=replay_summary,
            latest_heartbeat=latest_heartbeat,
        )
        result = {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "storage_tables": ["shadow_trade_proposals", "shadow_trade_outcomes"],
            "creator_paths": {
                "live_heartbeat": "app/heartbeat/steps/21_shadow_outcomes/implementation/main.py",
                "historical_replay": "app/framework/engine/replay.py",
            },
            "latest_heartbeat_outcome_step": latest_heartbeat,
            "recent_heartbeat_outcome_steps": heartbeat_steps[:10],
            "latest_real_research_cycle": {
                "cycle_id": latest_cycle_id,
                "started_at": latest_cycle.get("started_at"),
                "replay_run_ids": sorted(latest_run_ids),
                "groups": latest_groups,
                "liquidity_probe_15m": liquidity_probe,
                "one_hour_zero_sample_groups": hour_zero_sample,
            },
            "lookback_24h": replay_summary,
            "verdict": verdict,
        }
        self._log_report_phase("build_report", "done", elapsed_ms=int((monotonic() - started) * 1000))
        return result

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        started = monotonic()
        self._log_report_phase("render", "start")
        report = report or self.build_report()
        if report.get("status") != "ok":
            rendered = (
                "Outcome Recording Status\n"
                f"status={report.get('status', 'unknown')}\n"
                f"reason={report.get('reason', '-')}"
            )
            self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - started) * 1000))
            return rendered
        latest_heartbeat = report.get("latest_heartbeat_outcome_step", {}) or {}
        latest_cycle = report.get("latest_real_research_cycle", {}) or {}
        lookback = report.get("lookback_24h", {}) or {}
        lines = [
            "Outcome Recording Status",
            f"backend={report.get('backend', '-')}",
            f"storage_tables={','.join(report.get('storage_tables', []) or ['-'])}",
            "creator_paths="
            f"live_heartbeat:{report.get('creator_paths', {}).get('live_heartbeat', '-')};"
            f"historical_replay:{report.get('creator_paths', {}).get('historical_replay', '-')}",
            "",
            "Latest Heartbeat Outcome Step",
            f"tick_id={latest_heartbeat.get('tick_id', '-')}"
            f" | started_at={self._fmt_dt(latest_heartbeat.get('started_at'))}"
            f" | mode={latest_heartbeat.get('mode', '-')}"
            f" | checkpoints_due={latest_heartbeat.get('checkpoints_due', '-')}"
            f" | checkpoints_evaluated={latest_heartbeat.get('checkpoints_evaluated', '-')}"
            f" | waiting_for_future_bars={latest_heartbeat.get('waiting_for_future_bars', '-')}"
            f" | bars_loaded={latest_heartbeat.get('bars_loaded', '-')}",
            "",
            "Latest Real Research Cycle",
            f"cycle_id={latest_cycle.get('cycle_id', '-')}"
            f" | started_at={self._fmt_dt(latest_cycle.get('started_at'))}"
            f" | replay_run_ids={','.join(latest_cycle.get('replay_run_ids', []) or ['-'])}",
        ]
        for item in latest_cycle.get("groups", []) or []:
            lines.append(
                f"group={item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | replay_windows={item.get('replay_windows_actual', '-')}/{item.get('replay_windows_required', '-')}"
                f" | sample_size={item.get('sample_size_actual', '-')}/{item.get('sample_size_required', '-')}"
                f" | outcome_rows={item.get('outcome_rows_found', '-')}"
                f" | replay_proposals={item.get('replay_proposals_found', '-')}"
                f" | replay_outcomes_recorded={item.get('replay_outcomes_recorded', '-')}"
            )
            lines.append(
                f"  net_return={float(item.get('net_return_actual', 0.0) or 0.0):.6f}/{float(item.get('net_return_required', 0.0) or 0.0):.6f}"
                f" | win_rate={float(item.get('win_rate_actual', 0.0) or 0.0):.6f}/{float(item.get('win_rate_required', 0.0) or 0.0):.6f}"
                f" | symbols={item.get('symbols_tested', 0)}"
                f" | explanation={item.get('explanation', '-')}"
            )
        liquidity_probe = latest_cycle.get("liquidity_probe_15m", {}) or {}
        if liquidity_probe:
            lines.extend(
                [
                    "",
                    "Liquidity Probe 15Min",
                    f"replay_windows={liquidity_probe.get('replay_windows_actual', '-')}/{liquidity_probe.get('replay_windows_required', '-')}"
                    f" | sample_size={liquidity_probe.get('sample_size_actual', '-')}/{liquidity_probe.get('sample_size_required', '-')}"
                    f" | replay_proposals={liquidity_probe.get('replay_proposals_found', '-')}"
                    f" | replay_outcomes_recorded={liquidity_probe.get('replay_outcomes_recorded', '-')}"
                    f" | explanation={liquidity_probe.get('explanation', '-')}",
                ]
            )
        lines.extend(
            [
                "",
                "Last 24 Hours",
                f"proposals_created={lookback.get('proposals_created', 0)}"
                f" | outcomes_expected={lookback.get('outcomes_expected', 0)}"
                f" | outcomes_recorded={lookback.get('outcomes_recorded', 0)}"
                f" | missing_matured_outcomes={lookback.get('missing_matured_outcomes', 0)}"
                f" | not_yet_due={lookback.get('not_yet_due', 0)}",
                f"checkpoint_code_counts={self._render_counts(lookback.get('checkpoint_code_counts', {}))}",
                f"mismatch_counts={self._render_counts(lookback.get('mismatch_counts', {}))}",
            ]
        )
        for item in lookback.get("missing_by_group", []) or []:
            lines.append(
                f"missing={item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | symbol={item.get('symbol', '-')}"
                f" | checkpoint={item.get('checkpoint_code', '-')}"
                f" | missing={item.get('missing_count', 0)}"
                f" | bars_found={item.get('bars_found', 0)}"
                f" | mismatch_reason={item.get('mismatch_reason', '-')}"
            )
        lines.extend(
            [
                "",
                f"verdict={report.get('verdict', 'mixed')}",
            ]
        )
        rendered = "\n".join(lines)
        self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - started) * 1000))
        return rendered

    def _real_research_cycles(self, *, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.usage_ledger.list_recent_tick_runs(limit=limit):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if str(run.get("pipeline", "") or "") != "research_cycle":
                continue
            if str(run.get("source", "") or "") not in ALLOWED_REAL_SOURCES:
                continue
            if str(run.get("cycle_origin", "") or "") not in ALLOWED_REAL_ORIGINS:
                continue
            rows.append(row)
        return rows

    def _recent_heartbeat_outcome_steps(self, *, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.usage_ledger.list_recent_tick_runs(limit=limit):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if str(run.get("pipeline", "") or "") == "research_cycle":
                continue
            state = snapshot.get("shadow_trade_outcomes", {}) if isinstance(snapshot, dict) else {}
            if not isinstance(state, dict):
                continue
            rows.append(
                {
                    "tick_id": str(row.get("tick_id", "") or ""),
                    "started_at": row.get("started_at"),
                    "mode": str(state.get("mode", "") or ""),
                    "checkpoints_due": int(state.get("checkpoints_due", 0) or 0),
                    "checkpoints_evaluated": int(state.get("checkpoints_evaluated", 0) or 0),
                    "waiting_for_future_bars": int(state.get("waiting_for_future_bars", 0) or 0),
                    "bars_loaded": int(state.get("bars_loaded", 0) or 0),
                }
            )
        return rows

    def _collect_replay_run_ids(self, cycles: list[dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for row in cycles:
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
            for item in list(state.get("replay_run_ids", []) or []):
                value = str(item or "").strip()
                if value:
                    ids.add(value)
        return ids

    def _load_replay_checkpoint_rows(self, *, replay_run_ids: set[str]) -> list[dict[str, Any]]:
        if not replay_run_ids:
            return []
        if self.usage_ledger.backend == "postgres":
            with self.usage_ledger._connect_postgres(scope="core") as connection:  # type: ignore[attr-defined]
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT p.proposal_id, p.proposed_at, p.strategy_id, p.profile_id, p.source, p.symbol,
                               p.note, p.holding_window_code, p.holding_window_minutes,
                               o.checkpoint_code, o.checkpoint_minutes, o.due_at, o.evaluated_at, o.outcome_status
                        FROM shadow_trade_proposals p
                        JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                        WHERE split_part(p.note, ':', 2) = ANY(%s)
                        ORDER BY p.proposed_at ASC, p.proposal_id ASC, o.checkpoint_minutes ASC
                        """,
                        (list(replay_run_ids),),
                    )
                    columns = [item[0] for item in cursor.description]
                    rows = [dict(zip(columns, record)) for record in cursor.fetchall()]
        else:
            placeholders = ",".join("?" for _ in replay_run_ids)
            with self.usage_ledger._connect_sqlite() as connection:  # type: ignore[attr-defined]
                cursor = connection.execute(
                    f"""
                    SELECT p.proposal_id, p.proposed_at, p.strategy_id, p.profile_id, p.source, p.symbol,
                           p.note, p.holding_window_code, p.holding_window_minutes,
                           o.checkpoint_code, o.checkpoint_minutes, o.due_at, o.evaluated_at, o.outcome_status
                    FROM shadow_trade_proposals p
                    JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                    WHERE substr(
                            p.note,
                            instr(p.note, ':') + 1,
                            instr(substr(p.note, instr(p.note, ':') + 1), ':') - 1
                          ) IN ({placeholders})
                    ORDER BY p.proposed_at ASC, p.proposal_id ASC, o.checkpoint_minutes ASC
                    """,
                    tuple(replay_run_ids),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("proposed_at", "due_at", "evaluated_at"):
                item[key] = self.usage_ledger._normalize_db_datetime_value(item.get(key))  # type: ignore[attr-defined]
            item["replay_timeframe"] = self._parse_replay_timeframe(str(item.get("note", "") or ""))
            item["replay_run_id"] = self._parse_replay_run_id(str(item.get("note", "") or ""))
            normalized.append(item)
        return normalized

    def _latest_cycle_groups(
        self,
        *,
        decisions: list[dict[str, Any]],
        replay_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in replay_rows:
            key = (
                str(item.get("strategy_id", "") or ""),
                str(item.get("profile_id", "") or ""),
                str(item.get("replay_timeframe", "") or ""),
            )
            rows_by_key[key].append(item)
        groups: list[dict[str, Any]] = []
        for item in decisions:
            timeframe = str(item.get("timeframe", "") or "")
            key = (
                str(item.get("strategy_id", "") or ""),
                str(item.get("profile_id", "") or ""),
                timeframe,
            )
            matched = rows_by_key.get(key, [])
            proposals = {str(row.get("proposal_id", "") or "") for row in matched}
            outcomes_recorded = sum(1 for row in matched if isinstance(row.get("evaluated_at"), datetime))
            group = {
                "strategy_id": key[0],
                "profile_id": key[1],
                "timeframe": timeframe,
                "replay_windows_actual": int(item.get("windows_tested_count", 0) or 0),
                "replay_windows_required": int(self.config.research_min_windows),
                "sample_size_actual": int(item.get("proposals_created", 0) or 0),
                "sample_size_required": int(self.config.research_min_proposals),
                "outcome_rows_found": int(item.get("outcomes_recorded", 0) or 0),
                "replay_proposals_found": len([p for p in proposals if p]),
                "replay_outcomes_recorded": outcomes_recorded,
                "net_return_actual": float((item.get("net_return_summary_json", {}) or {}).get("avg_pct", 0.0) or 0.0),
                "net_return_required": float(self.config.research_min_net_return_pct),
                "win_rate_actual": float((item.get("win_rate_summary_json", {}) or {}).get("avg", 0.0) or 0.0),
                "win_rate_required": float(self.config.research_min_net_win_rate),
                "symbols_tested": len(list(item.get("symbol_universe_json", []) or [])),
                "blocked_reasons": list(item.get("blocker_reasons_json", []) or item.get("blocker_reasons", []) or []),
            }
            group["explanation"] = self._group_explanation(group=group)
            groups.append(group)
        return groups

    def _group_explanation(self, *, group: dict[str, Any]) -> str:
        if int(group.get("sample_size_actual", 0) or 0) <= 0 and int(group.get("replay_proposals_found", 0) or 0) <= 0:
            return "No replay proposals were created for this strategy/timeframe, so zero sample is expected from replay evidence rather than an outcome-recorder miss."
        if int(group.get("sample_size_actual", 0) or 0) > 0 and int(group.get("replay_outcomes_recorded", 0) or 0) >= int(
            group.get("outcome_rows_found", 0) or 0
        ):
            return "Replay proposals and outcome rows were recorded; low sample is driven by too few qualifying proposals, not missing recorded outcomes."
        if int(group.get("replay_windows_actual", 0) or 0) < int(group.get("replay_windows_required", 0) or 0):
            return "Replay evidence is still constrained by incomplete eligible windows for this timeframe."
        return "This row needs more evidence review."

    def _summarize_replay_rows(self, *, rows: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
        proposals_created = len({str(row.get("proposal_id", "") or "") for row in rows if str(row.get("proposal_id", "") or "")})
        outcomes_expected = 0
        outcomes_recorded = 0
        not_yet_due = 0
        missing_rows: list[dict[str, Any]] = []
        checkpoint_counts = Counter()
        mismatch_counts = Counter()
        missing_by_group: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            checkpoint = str(row.get("checkpoint_code", "") or "")
            checkpoint_counts[checkpoint] += 1
            due_at = row.get("due_at")
            evaluated_at = row.get("evaluated_at")
            if isinstance(due_at, datetime) and due_at <= as_of:
                outcomes_expected += 1
                if isinstance(evaluated_at, datetime):
                    outcomes_recorded += 1
                else:
                    missing_rows.append(row)
            else:
                not_yet_due += 1
        for row in missing_rows:
            proposed_at = row.get("proposed_at")
            bars = []
            if isinstance(proposed_at, datetime):
                bars = self.usage_ledger.get_market_bars_for_window(
                    source=str(row.get("source", "") or ""),
                    symbol=str(row.get("symbol", "") or ""),
                    start_at=proposed_at,
                    end_at=as_of,
                )
            bars_found = len(bars)
            mismatch_reason = "bars_found_pending_outcome" if bars_found > 0 else "no_bars_found_for_symbol_source"
            mismatch_counts[mismatch_reason] += 1
            key = (
                str(row.get("strategy_id", "") or ""),
                str(row.get("profile_id", "") or ""),
                str(row.get("replay_timeframe", "") or ""),
                str(row.get("symbol", "") or ""),
                str(row.get("checkpoint_code", "") or ""),
            )
            current = missing_by_group.setdefault(
                key,
                {
                    "strategy_id": key[0],
                    "profile_id": key[1],
                    "timeframe": key[2],
                    "symbol": key[3],
                    "checkpoint_code": key[4],
                    "missing_count": 0,
                    "bars_found": 0,
                    "mismatch_reason": mismatch_reason,
                },
            )
            current["missing_count"] = int(current["missing_count"]) + 1
            current["bars_found"] = max(int(current["bars_found"]), bars_found)
            if bars_found > 0:
                current["mismatch_reason"] = "bars_found_pending_outcome"
        return {
            "proposals_created": proposals_created,
            "outcomes_expected": outcomes_expected,
            "outcomes_recorded": outcomes_recorded,
            "missing_matured_outcomes": max(0, outcomes_expected - outcomes_recorded),
            "not_yet_due": not_yet_due,
            "checkpoint_code_counts": dict(checkpoint_counts),
            "mismatch_counts": dict(mismatch_counts),
            "missing_by_group": sorted(
                missing_by_group.values(),
                key=lambda item: (-int(item.get("missing_count", 0) or 0), str(item.get("strategy_id", "")), str(item.get("symbol", ""))),
            ),
        }

    def _find_group(
        self,
        groups: list[dict[str, Any]],
        strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> dict[str, Any]:
        for item in groups:
            if (
                str(item.get("strategy_id", "")) == strategy_id
                and str(item.get("profile_id", "")) == profile_id
                and str(item.get("timeframe", "")) == timeframe
            ):
                return item
        return {}

    def _parse_replay_timeframe(self, note: str) -> str:
        parts = note.split(":")
        if len(parts) >= 3:
            token = parts[2].strip().lower()
            if token == "15min":
                return "15Min"
            if token == "1hour":
                return "1Hour"
            return token
        return "-"

    def _parse_replay_run_id(self, note: str) -> str:
        parts = note.split(":")
        return parts[1].strip() if len(parts) >= 2 else ""

    def _final_verdict(
        self,
        *,
        latest_groups: list[dict[str, Any]],
        replay_summary: dict[str, Any],
        latest_heartbeat: dict[str, Any],
    ) -> str:
        if latest_heartbeat and int(latest_heartbeat.get("checkpoints_due", 0) or 0) > 0 and int(
            latest_heartbeat.get("checkpoints_evaluated", 0) or 0
        ) <= 0:
            return "outcome_recorder_not_running"
        if int(replay_summary.get("missing_matured_outcomes", 0) or 0) > 0:
            mismatch_counts = replay_summary.get("mismatch_counts", {}) or {}
            if int(mismatch_counts.get("no_bars_found_for_symbol_source", 0) or 0) > 0:
                return "historical_data_gap"
            if int(mismatch_counts.get("bars_found_pending_outcome", 0) or 0) > 0:
                return "outcome_lookup_bug"
        window_blocked = sum(1 for item in latest_groups if int(item.get("replay_windows_actual", 0) or 0) < int(item.get("replay_windows_required", 0) or 0))
        zero_sample = sum(1 for item in latest_groups if int(item.get("sample_size_actual", 0) or 0) <= 0)
        bad_perf = sum(
            1
            for item in latest_groups
            if int(item.get("sample_size_actual", 0) or 0) >= int(item.get("sample_size_required", 0) or 0)
            and (
                float(item.get("net_return_actual", 0.0) or 0.0) < float(item.get("net_return_required", 0.0) or 0.0)
                or float(item.get("win_rate_actual", 0.0) or 0.0) < float(item.get("win_rate_required", 0.0) or 0.0)
            )
        )
        if window_blocked > 0 and zero_sample <= 0 and bad_perf <= 0:
            return "waiting_for_future_windows"
        if bad_perf > 0 and window_blocked <= 0 and zero_sample <= 0:
            return "strategies_underperforming"
        return "mixed"

    def _started_at(self, row: dict[str, Any]) -> datetime:
        value = row.get("started_at")
        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(0).astimezone()

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _render_counts(self, counts: dict[str, int] | Counter[str]) -> str:
        items = sorted(((str(k), int(v)) for k, v in counts.items() if int(v) > 0), key=lambda item: (-item[1], item[0]))
        return ",".join(f"{key}:{value}" for key, value in items) if items else "-"

    def _log_report_phase(self, phase: str, status: str, *, elapsed_ms: int | None = None) -> None:
        message = (
            f"report_diagnostic report=outcome_recording_status phase={phase} status={status}"
            f" backend={self.usage_ledger.backend}"
        )
        if elapsed_ms is not None:
            message += f" elapsed_ms={elapsed_ms}"
        print(message, file=sys.stderr, flush=True)
