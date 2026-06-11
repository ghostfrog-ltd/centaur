from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ResearchCycleStatusReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def render(self) -> str:
        report = self.build_report()
        lines = ["Research Cycle Status", f"status={report.get('status', 'unknown')}"]
        reason = str(report.get("reason", "") or "").strip()
        if reason:
            lines.append(f"reason={reason}")
        latest_heartbeat = report.get("latest_heartbeat", {}) or {}
        if latest_heartbeat:
            lines.extend(
                [
                    f"latest_heartbeat_tick_id={latest_heartbeat.get('heartbeat_tick_id', '-')}",
                    f"autonomous_learning_called={'yes' if latest_heartbeat.get('autonomous_learning_called') else 'no'}",
                    f"research_cycle_enabled={'yes' if latest_heartbeat.get('research_cycle_enabled') else 'no'}",
                    f"research_cycle_enabled_raw_value={latest_heartbeat.get('research_cycle_enabled_raw_value', '-') or '-'}",
                    f"research_cycle_enabled_env_file_value={latest_heartbeat.get('research_cycle_enabled_env_file_value', '-') or '-'}",
                    f"research_cycle_enabled_value_source={latest_heartbeat.get('research_cycle_enabled_value_source', '-') or '-'}",
                    f"research_cycle_env_path={latest_heartbeat.get('research_cycle_env_path', '-') or '-'}",
                    f"research_cycle_due={'yes' if latest_heartbeat.get('research_cycle_due') else 'no'}",
                    f"research_cycle_last_started_at={latest_heartbeat.get('research_cycle_last_started_at', '-') or '-'}",
                    f"research_cycle_min_interval_minutes={int(latest_heartbeat.get('research_cycle_min_interval_minutes', 0) or 0)}",
                    f"research_cycle_started={'yes' if latest_heartbeat.get('research_cycle_started') else 'no'}",
                    f"research_cycle_completed={'yes' if latest_heartbeat.get('research_cycle_completed') else 'no'}",
                    f"research_cycle_skipped_reason={latest_heartbeat.get('research_cycle_skipped_reason', '-') or '-'}",
                    f"research_cycle_source={latest_heartbeat.get('research_cycle_source', '-') or '-'}",
                    f"research_cycle_origin={latest_heartbeat.get('cycle_origin', '-') or '-'}",
                    f"research_cycle_parent_process_mode={latest_heartbeat.get('parent_process_mode', '-') or '-'}",
                    f"research_cycle_command_source={latest_heartbeat.get('command_source', '-') or '-'}",
                    f"research_cycle_id={latest_heartbeat.get('research_cycle_id', '-') or '-'}",
                    f"research_decisions_written={int(latest_heartbeat.get('research_decisions_written', 0) or 0)}",
                    f"evidence_decisions_count={int(latest_heartbeat.get('usable_decisions_count', 0) or 0)}",
                    f"paper_candidates_created={int(latest_heartbeat.get('paper_candidates_created', 0) or 0)}",
                    f"paper_removal_candidates_created={int(latest_heartbeat.get('paper_removal_candidates_created', 0) or 0)}",
                    f"attention_alerts_resolved={int(latest_heartbeat.get('attention_alerts_resolved', 0) or 0)}",
                    f"attention_alerts_created={int(latest_heartbeat.get('attention_alerts_created', 0) or 0)}",
                ]
            )
            persistence_error = str(latest_heartbeat.get("research_cycle_persistence_error", "") or "")
            if persistence_error:
                lines.append(f"research_cycle_persistence_error={persistence_error}")
        latest_real_cycle = report.get("latest_real_cycle", {}) or {}
        if latest_real_cycle:
            blockers = ",".join(latest_real_cycle.get("blockers", []) or ["none"])
            top_rejected = list(report.get("top_rejected_decisions", []) or [])
            lines.extend(
                [
                    f"latest_real_heartbeat_tick_id={latest_real_cycle.get('latest_real_heartbeat_tick_id', '-')}",
                    f"latest_real_cycle_id={latest_real_cycle.get('latest_real_research_cycle_id', '-')}",
                    f"research_cycle_source={latest_real_cycle.get('source', '-')}",
                    f"research_cycle_origin={latest_real_cycle.get('cycle_origin', '-')}",
                    f"research_cycle_parent_process_mode={latest_real_cycle.get('parent_process_mode', '-')}",
                    f"research_cycle_command_source={latest_real_cycle.get('command_source', '-')}",
                    f"latest_real_cycle_started_at={latest_real_cycle.get('latest_real_research_cycle_started_at', '-')}",
                    f"historical_windows_selected_count={int(latest_real_cycle.get('historical_windows_selected', 0) or 0)}",
                    f"replay_windows_accepted_count={int(latest_real_cycle.get('replay_windows_accepted_count', 0) or 0)}",
                    f"replay_windows_rejected_count={int(latest_real_cycle.get('replay_windows_rejected_count', 0) or 0)}",
                    f"latest_valid_replay_window_end={latest_real_cycle.get('latest_valid_replay_window_end', '-') or '-'}",
                    f"profiles_evaluated={int(latest_real_cycle.get('strategy_profiles_evaluated', 0) or 0)}",
                    f"profiles_with_replay_evidence={int(report.get('profiles_with_replay_evidence', 0) or 0)}",
                    f"profiles_with_paper_sim_evidence={int(report.get('profiles_with_paper_sim_evidence', 0) or 0)}",
                    f"latest_real_raw_decisions_count={int(report.get('raw_decisions_count', 0) or 0)}",
                    f"latest_real_evidence_decisions_count={int(report.get('evidence_decisions_count', 0) or 0)}",
                    f"latest_real_rejected_for_promotion_count={int(report.get('rejected_for_promotion_count', 0) or 0)}",
                    f"latest_real_promotion_eligible_count={int(report.get('promotion_eligible_count', 0) or 0)}",
                    f"latest_real_paper_candidates_created={int(latest_real_cycle.get('paper_candidates_created', 0) or 0)}",
                    f"latest_real_removal_candidates_created={int(latest_real_cycle.get('paper_removal_candidates_created', 0) or 0)}",
                    f"top_blocker={report.get('top_fitness_blocker', '-') or '-'}",
                    f"blocked_by_replay_evidence={'yes' if report.get('blocked_by_replay_evidence') else 'no'}",
                    f"blocked_by_paper_sim_evidence={'yes' if report.get('blocked_by_paper_sim_evidence') else 'no'}",
                    f"blocked_by_fitness_threshold={'yes' if report.get('blocked_by_fitness_threshold') else 'no'}",
                    f"blocked_by_sample_size={'yes' if report.get('blocked_by_sample_size') else 'no'}",
                    f"blocked_by_allocation_policy={'yes' if report.get('blocked_by_allocation_policy') else 'no'}",
                    f"blocked_by_missing_historical_windows={'yes' if report.get('blocked_by_missing_historical_windows') else 'no'}",
                    f"blockers={blockers}",
                ]
            )
            for item in top_rejected:
                lines.append(
                    "top_rejected_decision="
                    f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                    f" | recommendation={item.get('recommendation', '-')}"
                    f" | reason={item.get('reason', '-')}"
                )
        return "\n".join(lines)

    def build_report(self) -> dict[str, Any]:
        latest_real_cycle = self.usage_ledger.latest_real_heartbeat_research_cycle_summary()
        latest_heartbeat = self._latest_heartbeat_autonomous_learning_summary()
        latest_real_cycle_row = self._latest_real_cycle_row()
        real_cycle_analysis = self._analyze_real_cycle(row=latest_real_cycle_row)
        status = "ok" if latest_real_cycle else "not_found"
        reason = ""
        if not latest_real_cycle:
            reason = self._derive_missing_reason(latest_heartbeat=latest_heartbeat)
        return {
            "status": status,
            "reason": reason,
            "latest_real_cycle": latest_real_cycle,
            "latest_heartbeat": latest_heartbeat,
            **real_cycle_analysis,
        }

    def _latest_heartbeat_autonomous_learning_summary(self) -> dict[str, Any]:
        for row in self.usage_ledger.list_recent_tick_runs(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            heartbeat = snapshot.get("heartbeat", {})
            if not isinstance(heartbeat, dict):
                continue
            autonomous = heartbeat.get("autonomous_learning", {})
            if not isinstance(autonomous, dict):
                continue
            return {
                "heartbeat_tick_id": str(heartbeat.get("tick_id", "") or row.get("tick_id", "")),
                "started_at": self._fmt_dt(row.get("started_at")),
                **autonomous,
            }
        return {}

    def _latest_real_cycle_row(self) -> dict[str, Any] | None:
        fallback = None
        for row in self.usage_ledger.list_recent_tick_runs(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            run = snapshot.get("run", {})
            if not isinstance(run, dict):
                continue
            if (
                str(run.get("pipeline", "") or "") == "research_cycle"
                and str(run.get("source", "") or "") == "real_heartbeat"
            ):
                if str(run.get("cycle_origin", "") or "") == "launchd_scheduled":
                    return row
                if fallback is None:
                    fallback = row
        return fallback

    def _analyze_real_cycle(self, *, row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {
                "raw_decisions_count": 0,
                "evidence_decisions_count": 0,
                "rejected_for_promotion_count": 0,
                "promotion_eligible_count": 0,
                "profiles_with_replay_evidence": 0,
                "profiles_with_paper_sim_evidence": 0,
                "top_rejected_decisions": [],
                "top_fitness_blocker": "",
                "blocked_by_replay_evidence": False,
                "blocked_by_paper_sim_evidence": False,
                "blocked_by_fitness_threshold": False,
                "blocked_by_sample_size": False,
                "blocked_by_allocation_policy": False,
                "blocked_by_missing_historical_windows": False,
            }
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
        decisions = list(state.get("decisions", []) or [])
        raw_decisions_count = len(decisions)
        promotion_eligible_decisions = [
            item
            for item in decisions
            if str(item.get("recommendation", "")) == "paper_sim_candidate"
        ]
        rejected_decisions = [
            item
            for item in decisions
            if str(item.get("recommendation", "")) != "paper_sim_candidate"
        ]
        blocker_counter: Counter[str] = Counter()
        blocked_by_replay_evidence = False
        blocked_by_paper_sim_evidence = False
        blocked_by_fitness_threshold = False
        blocked_by_sample_size = False
        blocked_by_allocation_policy = False
        blocked_by_missing_historical_windows = int(state.get("historical_windows_selected", 0) or 0) <= 0
        profiles_with_replay_evidence = 0
        profiles_with_paper_sim_evidence = 0
        for item in rejected_decisions:
            reasons = list(item.get("blocker_reasons", []) or [])
            for reason in reasons:
                label = str(reason or "").strip()
                if not label:
                    continue
                blocker_counter[label] += 1
                if label in {"insufficient_replay_windows"} or label.startswith("timeframe:"):
                    blocked_by_replay_evidence = True
                if label in {"paper_allocation_excludes_backtest_evidence", "live_allocation_excludes_backtest_evidence"}:
                    blocked_by_allocation_policy = True
                if label in {"insufficient_sample_size"}:
                    blocked_by_sample_size = True
                if label in {"net_return_below_threshold", "win_rate_below_threshold"}:
                    blocked_by_fitness_threshold = True
            if int(item.get("outcomes_recorded", 0) or 0) <= 0:
                blocked_by_paper_sim_evidence = True
        for item in decisions:
            if int(item.get("proposals_created", 0) or 0) > 0:
                profiles_with_replay_evidence += 1
            if int(item.get("outcomes_recorded", 0) or 0) > 0:
                profiles_with_paper_sim_evidence += 1
        top_rejected_decisions = []
        for item in rejected_decisions[:5]:
            reasons = list(item.get("blocker_reasons", []) or [])
            top_rejected_decisions.append(
                {
                    "strategy_id": str(item.get("strategy_id", "") or "-"),
                    "profile_id": str(item.get("profile_id", "") or "-"),
                    "recommendation": str(item.get("recommendation", "") or "-"),
                    "reason": reasons[0] if reasons else "no_blocker_reason_recorded",
                }
            )
        return {
            "raw_decisions_count": raw_decisions_count,
            "evidence_decisions_count": int(state.get("usable_decisions_count", 0) or 0),
            "rejected_for_promotion_count": len(rejected_decisions),
            "promotion_eligible_count": len(promotion_eligible_decisions),
            "profiles_with_replay_evidence": profiles_with_replay_evidence,
            "profiles_with_paper_sim_evidence": profiles_with_paper_sim_evidence,
            "top_rejected_decisions": top_rejected_decisions,
            "top_fitness_blocker": blocker_counter.most_common(1)[0][0] if blocker_counter else "",
            "blocked_by_replay_evidence": blocked_by_replay_evidence,
            "blocked_by_paper_sim_evidence": blocked_by_paper_sim_evidence,
            "blocked_by_fitness_threshold": blocked_by_fitness_threshold,
            "blocked_by_sample_size": blocked_by_sample_size,
            "blocked_by_allocation_policy": blocked_by_allocation_policy,
            "blocked_by_missing_historical_windows": blocked_by_missing_historical_windows,
        }

    def _derive_missing_reason(self, *, latest_heartbeat: dict[str, Any]) -> str:
        if not latest_heartbeat:
            return "heartbeat_has_not_called_autonomous_learning"
        if not bool(latest_heartbeat.get("autonomous_learning_called")):
            return "heartbeat_has_not_called_autonomous_learning"
        if not bool(latest_heartbeat.get("research_cycle_enabled")):
            return "research_disabled"
        if not bool(latest_heartbeat.get("research_cycle_due")):
            return "not_due_yet"
        if not bool(latest_heartbeat.get("research_cycle_started")):
            return "heartbeat_has_not_called_autonomous_learning"
        source = str(latest_heartbeat.get("research_cycle_source", "") or "")
        if source and source != "real_heartbeat":
            return "wrong_source_tag"
        if str(latest_heartbeat.get("research_cycle_persistence_error", "") or "").strip():
            return "storage_write_failed"
        skipped_reason = str(latest_heartbeat.get("research_cycle_skipped_reason", "") or "").strip()
        if skipped_reason == "cycle_failed_before_persistence":
            return "cycle_failed_before_persistence"
        if skipped_reason == "wrong_source_tag":
            return "wrong_source_tag"
        if skipped_reason == "storage_write_failed":
            return "storage_write_failed"
        if skipped_reason == "no_usable_decisions":
            return "no_usable_decisions"
        if bool(latest_heartbeat.get("research_cycle_completed")):
            return "cycle_failed_before_persistence"
        return "heartbeat_has_not_called_autonomous_learning"

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")
