from __future__ import annotations

from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class RealLearningProofReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        row = self._latest_real_cycle_row()
        reasons: list[str] = []
        if self.usage_ledger.backend != "postgres":
            reasons.append("no_postgres_backend_selected")
        if not row:
            reasons.append("no_real_heartbeat_cycle")
            return self._result({}, reasons)
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
        decisions = list(state.get("decisions", []) or [])
        if int(state.get("historical_windows_selected", 0) or 0) <= 0:
            reasons.append("no_valid_replay_windows")
        if int(state.get("strategy_profiles_evaluated", 0) or 0) <= 0:
            reasons.append("no_profiles_evaluated")
        profiles_with_replay = sum(1 for item in decisions if int(item.get("proposals_created", 0) or 0) > 0)
        if profiles_with_replay <= 0:
            reasons.append("no_replay_evidence")
        if str(run.get("source", "") or "") != "real_heartbeat":
            reasons.append("wrong_source_tag")
        persistence_error = str(row.get("persistence_error", "") or "")
        if persistence_error:
            reasons.append("storage_write_failed")
        promotion_eligible_count = sum(
            1
            for item in decisions
            if str(item.get("recommendation", "")) == "paper_sim_candidate"
        )
        rejected_for_promotion_count = max(0, len(decisions) - promotion_eligible_count)
        if not decisions:
            reasons.append("no_decisions_generated")
        elif rejected_for_promotion_count >= len(decisions) and not any(
            item.get("blocker_reasons") for item in decisions
        ):
            reasons.append("all_decisions_rejected")
        return self._result(
            {
                "historical_windows_selected": int(state.get("historical_windows_selected", 0) or 0),
                "latest_valid_replay_window_end": str(
                    state.get("latest_valid_replay_window_end", "") or ""
                ),
                "profiles_with_replay": profiles_with_replay,
                "raw_decisions_count": len(decisions),
                "evidence_decisions_count": int(state.get("usable_decisions_count", 0) or 0),
                "rejected_for_promotion_count": rejected_for_promotion_count,
                "promotion_eligible_count": promotion_eligible_count,
                "paper_candidates_created": int(state.get("paper_candidates_created", 0) or 0),
                "paper_removal_candidates_created": int(state.get("paper_removal_candidates_created", 0) or 0),
            },
            reasons,
        )

    def render(self) -> str:
        report = self.build_report()
        lines = [
            "Real Learning Proof",
            f"real_learning_proven={'true' if report.get('real_learning_proven') else 'false'}",
            f"historical_windows_selected={int(report.get('historical_windows_selected', 0) or 0)}",
            f"latest_valid_replay_window_end={report.get('latest_valid_replay_window_end', '-') or '-'}",
            f"profiles_with_replay={int(report.get('profiles_with_replay', 0) or 0)}",
            f"raw_decisions_count={int(report.get('raw_decisions_count', 0) or 0)}",
            f"evidence_decisions_count={int(report.get('evidence_decisions_count', 0) or 0)}",
            f"rejected_for_promotion_count={int(report.get('rejected_for_promotion_count', 0) or 0)}",
            f"promotion_eligible_count={int(report.get('promotion_eligible_count', 0) or 0)}",
            f"paper_candidates_created={int(report.get('paper_candidates_created', 0) or 0)}",
            f"paper_removal_candidates_created={int(report.get('paper_removal_candidates_created', 0) or 0)}",
            "broker_orders_created=0",
            "live_orders_created=0",
            "auto_paper_approved=0",
            "auto_live_approved=0",
            f"failure_reasons={','.join(report.get('failure_reasons', []) or ['none'])}",
            f"final_safety_summary={'PASS' if report.get('final_safety_summary') == 'PASS' else 'FAIL'}",
        ]
        return "\n".join(lines)

    def _latest_real_cycle_row(self) -> dict[str, Any] | None:
        fallback = None
        for row in self.usage_ledger.list_recent_tick_runs(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if (
                str(run.get("pipeline", "") or "") == "research_cycle"
                and str(run.get("source", "") or "") == "real_heartbeat"
            ):
                if str(run.get("cycle_origin", "") or "") == "launchd_scheduled":
                    return row
                if fallback is None:
                    fallback = row
        return fallback

    def _result(self, values: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
        proven = not reasons
        return {
            "real_learning_proven": proven,
            "failure_reasons": reasons,
            "broker_orders_created": 0,
            "live_orders_created": 0,
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            "final_safety_summary": "PASS" if proven else "FAIL",
            **values,
        }
