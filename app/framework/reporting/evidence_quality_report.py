from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import inf
import sys
from time import monotonic
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

ALLOWED_REAL_SOURCES = {"real_heartbeat"}
ALLOWED_REAL_ORIGINS = {"launchd_scheduled", "real_heartbeat", "forced_one_shot"}


class EvidenceQualityReport:
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
        build_started = monotonic()
        self._log_report_phase("build_report", "start")
        cycles = self._real_research_cycles(limit=200)
        latest = cycles[0] if cycles else None
        if latest is None:
            result = {"status": "not_found", "reason": "No persisted real research cycle is available yet."}
            self._log_report_phase("build_report", "done", elapsed_ms=int((monotonic() - build_started) * 1000))
            return result

        latest_cycle_id = str((latest or {}).get("tick_id", "") or "")
        latest_groups = self._load_cycle_groups(cycle_id=latest_cycle_id)
        lookback_start = self._started_at(latest) - timedelta(hours=max(1, int(lookback_hours or 24)))
        lookback_groups = self._aggregate_groups(
            cycle_ids=[
                str(item.get("tick_id", "") or "")
                for item in cycles
                if self._started_at(item) >= lookback_start
            ]
        )
        blocker_counts = Counter()
        split_counts = Counter()
        for item in latest_groups:
            blocker_counts.update(item.get("blocker_bucket_counts", {}))
            split_counts.update(item.get("split_blockers", []))
        closest = sorted(
            latest_groups,
            key=lambda item: (
                0 if int(item.get("sample_size_actual", 0) or 0) > 0 else 1,
                float(item.get("distance_to_paper", inf) or inf),
                -int(item.get("sample_size_actual", 0) or 0),
                str(item.get("strategy_id", "")),
                str(item.get("profile_id", "")),
                str(item.get("timeframe", "")),
            ),
        )[:5]
        actionable_fix = self._actionable_fix(latest_groups=latest_groups, blocker_counts=blocker_counts)
        verdict = self._final_verdict(latest_groups=latest_groups, blocker_counts=blocker_counts)
        result = {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "latest_cycle": {
                "cycle_id": latest_cycle_id,
                "started_at": latest.get("started_at"),
                "groups": latest_groups,
                "blocker_counts": dict(blocker_counts),
                "split_blocker_counts": dict(split_counts),
            },
            "lookback_24h": {
                "hours": max(1, int(lookback_hours or 24)),
                "group_count": len(lookback_groups),
                "groups": lookback_groups,
            },
            "closest_to_paper": closest,
            "single_most_actionable_next_fix": actionable_fix,
            "verdict": verdict,
        }
        self._log_report_phase("build_report", "done", elapsed_ms=int((monotonic() - build_started) * 1000))
        return result

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        render_started = monotonic()
        self._log_report_phase("render", "start")
        report = report or self.build_report()
        if report.get("status") != "ok":
            rendered = (
                "Evidence Quality Report\n"
                f"status={report.get('status', 'unknown')}\n"
                f"reason={report.get('reason', '-')}"
            )
            self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - render_started) * 1000))
            return rendered
        latest = report.get("latest_cycle", {}) or {}
        lines = [
            "Evidence Quality Report",
            f"backend={report.get('backend', '-')}",
            "",
            "Latest Real Research Cycle",
            f"cycle_id={latest.get('cycle_id', '-')}"
            f" | started_at={self._fmt_dt(latest.get('started_at'))}",
            f"blocker_counts={self._render_counts(latest.get('blocker_counts', {}))}",
            f"split_blockers={self._render_counts(latest.get('split_blocker_counts', {}))}",
        ]
        for item in latest.get("groups", []) or []:
            lines.append(
                f"group={item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
            )
            lines.append(
                f"  replay_windows={item.get('replay_windows_actual', '-')}/{item.get('replay_windows_required', '-')}"
                f" | sample_size={item.get('sample_size_actual', '-')}/{item.get('sample_size_required', '-')}"
                f" | net_return={float(item.get('net_return_actual', 0.0) or 0.0):.6f}/{float(item.get('net_return_required', 0.0) or 0.0):.6f}"
                f" | win_rate={float(item.get('win_rate_actual', 0.0) or 0.0):.6f}/{float(item.get('win_rate_required', 0.0) or 0.0):.6f}"
            )
            lines.append(
                f"  symbols_tested={item.get('symbols_tested', 0)}"
                f" | outcome_rows_found={item.get('outcome_rows_found', 0)}"
                f" | missing_outcome_rows={item.get('missing_outcome_rows', 0)}"
            )
            lines.append(
                "  split_blockers="
                + ",".join(item.get("split_blockers", []) or ["none"])
            )
            lines.append(
                "  blocked_reasons="
                + ",".join(item.get("blocker_reasons", []) or ["none"])
            )
        lines.extend(
            [
                "",
                "Top 5 Closest To Paper",
            ]
        )
        for item in report.get("closest_to_paper", []) or []:
            lines.append(
                f"closest={item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | sample_size={item.get('sample_size_actual', '-')}"
                f" | distance={float(item.get('distance_to_paper', 0.0) or 0.0):.6f}"
                f" | split_blockers={','.join(item.get('split_blockers', []) or ['none'])}"
            )
        lookback = report.get("lookback_24h", {}) or {}
        lines.extend(
            [
                "",
                "Last 24 Hours",
                f"hours={lookback.get('hours', 24)} | group_count={lookback.get('group_count', 0)}",
            ]
        )
        for item in lookback.get("groups", []) or []:
            lines.append(
                f"group_24h={item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | cycles={item.get('cycles_seen', 0)}"
                f" | best_replay_windows={item.get('replay_windows_actual', '-')}/{item.get('replay_windows_required', '-')}"
                f" | sample_size={item.get('sample_size_actual', '-')}/{item.get('sample_size_required', '-')}"
                f" | net_return={float(item.get('net_return_actual', 0.0) or 0.0):.6f}/{float(item.get('net_return_required', 0.0) or 0.0):.6f}"
                f" | win_rate={float(item.get('win_rate_actual', 0.0) or 0.0):.6f}/{float(item.get('win_rate_required', 0.0) or 0.0):.6f}"
            )
        lines.extend(
            [
                "",
                f"single_most_actionable_next_fix={report.get('single_most_actionable_next_fix', '-')}",
                f"verdict={report.get('verdict', 'mixed')}",
            ]
        )
        rendered = "\n".join(lines)
        self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - render_started) * 1000))
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

    def _load_cycle_groups(self, *, cycle_id: str) -> list[dict[str, Any]]:
        decisions = self.usage_ledger.list_research_cycle_decisions(cycle_id=cycle_id, limit=500)
        return [self._decision_group(item, cycles_seen=1) for item in decisions]

    def _aggregate_groups(self, *, cycle_ids: list[str]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for cycle_id in cycle_ids:
            for item in self.usage_ledger.list_research_cycle_decisions(cycle_id=cycle_id, limit=500):
                key = (
                    str(item.get("strategy_id", "") or ""),
                    str(item.get("profile_id", "") or ""),
                    str(item.get("timeframe", "") or ""),
                )
                grouped[key].append(item)
        aggregated: list[dict[str, Any]] = []
        for _, rows in sorted(grouped.items()):
            aggregated.append(self._aggregate_group_rows(rows))
        return aggregated

    def _aggregate_group_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        latest = rows[0]
        best_windows = max(int(item.get("windows_tested_count", 0) or 0) for item in rows)
        best_samples = max(int(item.get("proposals_created", 0) or 0) for item in rows)
        best_outcomes = max(int(item.get("outcomes_recorded", 0) or 0) for item in rows)
        best_net = max(float((item.get("net_return_summary_json", {}) or {}).get("avg_pct", 0.0) or 0.0) for item in rows)
        best_win = max(float((item.get("win_rate_summary_json", {}) or {}).get("avg", 0.0) or 0.0) for item in rows)
        symbols = sorted(
            {
                str(symbol)
                for item in rows
                for symbol in list(item.get("symbol_universe_json", []) or [])
                if str(symbol).strip()
            }
        )
        all_reasons = [
            str(reason).strip()
            for item in rows
            for reason in list(item.get("blocker_reasons_json", []) or item.get("blocker_reasons", []) or [])
            if str(reason).strip()
        ]
        aggregated = self._decision_group(latest, cycles_seen=len(rows))
        aggregated.update(
            {
                "replay_windows_actual": best_windows,
                "sample_size_actual": best_samples,
                "outcome_rows_found": best_outcomes,
                "missing_outcome_rows": max(0, best_samples - best_outcomes),
                "net_return_actual": best_net,
                "win_rate_actual": best_win,
                "symbols_tested": len(symbols),
                "cycles_seen": len(rows),
                "blocker_reasons": sorted(set(all_reasons)),
            }
        )
        aggregated["split_blockers"] = self._split_blockers(
            reasons=aggregated["blocker_reasons"],
            windows_actual=best_windows,
            sample_actual=best_samples,
            net_actual=best_net,
            win_actual=best_win,
            outcome_rows_found=best_outcomes,
            missing_outcome_rows=aggregated["missing_outcome_rows"],
        )
        aggregated["blocker_bucket_counts"] = Counter(aggregated["split_blockers"])
        aggregated["distance_to_paper"] = self._distance_to_paper(aggregated)
        return aggregated

    def _decision_group(self, item: dict[str, Any], *, cycles_seen: int) -> dict[str, Any]:
        raw = self._as_dict(item.get("raw_json")) or item
        reasons = [
            str(reason).strip()
            for reason in list(item.get("blocker_reasons_json", []) or item.get("blocker_reasons", []) or [])
            if str(reason).strip()
        ]
        windows_actual = int(item.get("windows_tested_count", raw.get("windows_tested_count", 0)) or 0)
        sample_actual = int(item.get("proposals_created", raw.get("proposals_created", 0)) or 0)
        outcome_rows_found = int(item.get("outcomes_recorded", raw.get("outcomes_recorded", 0)) or 0)
        missing_outcome_rows = max(0, sample_actual - outcome_rows_found)
        net_summary = self._as_dict(item.get("net_return_summary_json")) or self._as_dict(raw.get("net_return_summary"))
        win_summary = self._as_dict(item.get("win_rate_summary_json")) or self._as_dict(raw.get("win_rate_summary"))
        net_actual = float(net_summary.get("avg_pct", 0.0) or 0.0)
        win_actual = float(win_summary.get("avg", 0.0) or 0.0)
        symbols = list(item.get("symbol_universe_json", raw.get("symbol_universe", [])) or [])
        group = {
            "strategy_id": str(item.get("strategy_id", raw.get("strategy_id", "")) or "-"),
            "profile_id": str(item.get("profile_id", raw.get("profile_id", "")) or "-"),
            "timeframe": str(item.get("timeframe", raw.get("timeframe", "")) or "-"),
            "replay_windows_actual": windows_actual,
            "replay_windows_required": int(self.config.research_min_windows),
            "sample_size_actual": sample_actual,
            "sample_size_required": int(self.config.research_min_proposals),
            "net_return_actual": net_actual,
            "net_return_required": float(self.config.research_min_net_return_pct),
            "win_rate_actual": win_actual,
            "win_rate_required": float(self.config.research_min_net_win_rate),
            "symbols_tested": len(symbols),
            "outcome_rows_found": outcome_rows_found,
            "missing_outcome_rows": missing_outcome_rows,
            "blocker_reasons": reasons,
            "cycles_seen": cycles_seen,
        }
        split = self._split_blockers(
            reasons=reasons,
            windows_actual=windows_actual,
            sample_actual=sample_actual,
            net_actual=net_actual,
            win_actual=win_actual,
            outcome_rows_found=outcome_rows_found,
            missing_outcome_rows=missing_outcome_rows,
        )
        group["split_blockers"] = split
        group["blocker_bucket_counts"] = Counter(split)
        group["distance_to_paper"] = self._distance_to_paper(group)
        return group

    def _split_blockers(
        self,
        *,
        reasons: list[str],
        windows_actual: int,
        sample_actual: int,
        net_actual: float,
        win_actual: float,
        outcome_rows_found: int,
        missing_outcome_rows: int,
    ) -> list[str]:
        split: list[str] = []
        required_windows = int(self.config.research_min_windows)
        required_sample = int(self.config.research_min_proposals)
        required_net = float(self.config.research_min_net_return_pct)
        required_win = float(self.config.research_min_net_win_rate)
        normalized = ",".join(reason.lower() for reason in reasons)
        if windows_actual < required_windows:
            split.append("not_enough_future_windows_yet")
        if (
            any(token in normalized for token in ("historical_row", "historical_rows", "no_historical", "missing_historical", "timeframe:"))
            or missing_outcome_rows > 0
            or (sample_actual > 0 and outcome_rows_found <= 0)
        ):
            split.append("missing_historical_or_outcome_rows")
        if sample_actual >= required_sample and (net_actual < required_net or win_actual < required_win):
            split.append("enough_sample_but_bad_performance")
        if sample_actual > 0 and sample_actual < required_sample and net_actual >= required_net and win_actual >= required_win:
            split.append("enough_performance_but_too_little_sample")
        return sorted(set(split)) or ["mixed"]

    def _distance_to_paper(self, item: dict[str, Any]) -> float:
        return (
            max(0, int(item.get("replay_windows_required", 0) or 0) - int(item.get("replay_windows_actual", 0) or 0))
            + max(0, int(item.get("sample_size_required", 0) or 0) - int(item.get("sample_size_actual", 0) or 0))
            / max(1, int(item.get("sample_size_required", 1) or 1))
            + max(0.0, float(item.get("net_return_required", 0.0) or 0.0) - float(item.get("net_return_actual", 0.0) or 0.0))
            / max(abs(float(item.get("net_return_required", 0.0) or 0.0)), 1e-9)
            + max(0.0, float(item.get("win_rate_required", 0.0) or 0.0) - float(item.get("win_rate_actual", 0.0) or 0.0))
            / max(abs(float(item.get("win_rate_required", 0.0) or 0.0)), 1e-9)
        )

    def _actionable_fix(self, *, latest_groups: list[dict[str, Any]], blocker_counts: Counter[str]) -> str:
        if int(blocker_counts.get("missing_historical_or_outcome_rows", 0) or 0) > 0:
            rows_with_zero_outcomes = sum(1 for item in latest_groups if int(item.get("outcome_rows_found", 0) or 0) <= 0)
            rows_with_missing = sum(1 for item in latest_groups if int(item.get("missing_outcome_rows", 0) or 0) > 0)
            if rows_with_zero_outcomes > 0 or rows_with_missing > 0:
                return "fix outcome recording"
            return "broaden historical data collection"
        if int(blocker_counts.get("not_enough_future_windows_yet", 0) or 0) > 0:
            return "wait for more data"
        if int(blocker_counts.get("enough_sample_but_bad_performance", 0) or 0) > 0:
            return "improve strategy logic"
        sparse = sum(1 for item in latest_groups if int(item.get("symbols_tested", 0) or 0) <= 1)
        if sparse >= max(1, len(latest_groups) // 2):
            return "adjust candidate universe"
        return "wait for more data"

    def _final_verdict(self, *, latest_groups: list[dict[str, Any]], blocker_counts: Counter[str]) -> str:
        if not latest_groups:
            return "mixed"
        if int(blocker_counts.get("not_enough_future_windows_yet", 0) or 0) > 0 and sum(blocker_counts.values()) == int(
            blocker_counts.get("not_enough_future_windows_yet", 0) or 0
        ):
            return "waiting_for_more_future_windows"
        if int(blocker_counts.get("missing_historical_or_outcome_rows", 0) or 0) > 0 and int(
            blocker_counts.get("enough_sample_but_bad_performance", 0) or 0
        ) <= 0:
            return "missing_outcome_data"
        if int(blocker_counts.get("enough_sample_but_bad_performance", 0) or 0) > 0 and int(
            blocker_counts.get("missing_historical_or_outcome_rows", 0) or 0
        ) <= 0 and int(blocker_counts.get("not_enough_future_windows_yet", 0) or 0) <= 0:
            return "strategies_underperforming"
        sparse = sum(1 for item in latest_groups if int(item.get("symbols_tested", 0) or 0) <= 1)
        if (
            sparse >= max(1, len(latest_groups) // 2)
            and int(blocker_counts.get("missing_historical_or_outcome_rows", 0) or 0) > 0
            and int(blocker_counts.get("enough_sample_but_bad_performance", 0) or 0) <= 0
            and int(blocker_counts.get("not_enough_future_windows_yet", 0) or 0) <= 0
        ):
            return "candidate_universe_too_sparse"
        return "mixed"

    def _render_counts(self, counts: dict[str, int] | Counter[str]) -> str:
        items = sorted(((str(k), int(v)) for k, v in counts.items() if int(v) > 0), key=lambda item: (-item[1], item[0]))
        return ",".join(f"{key}:{value}" for key, value in items) if items else "-"

    def _started_at(self, row: dict[str, Any]) -> datetime:
        value = row.get("started_at")
        if isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(0).astimezone()

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _log_report_phase(self, phase: str, status: str, *, elapsed_ms: int | None = None) -> None:
        message = (
            f"report_diagnostic report=evidence_quality phase={phase} status={status}"
            f" backend={self.usage_ledger.backend}"
        )
        if elapsed_ms is not None:
            message += f" elapsed_ms={elapsed_ms}"
        print(message, file=sys.stderr, flush=True)
