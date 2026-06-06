from __future__ import annotations

from collections import Counter
from typing import Any

from app.framework.reporting.autopilot_proof import AutopilotProofRunner
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ResearchProofVsRealReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        proof_runner = AutopilotProofRunner()
        proof_result = proof_runner.run()
        proof_config = proof_runner._config()
        real_row = self._latest_real_cycle_row()
        real = self._real_cycle_summary(real_row=real_row)
        proof = self._proof_summary(proof_result=proof_result, proof_config=proof_config)
        return {
            "proof": proof,
            "real": real,
            "why_proof_has_candidates_but_real_does_not": self._why_diff(proof=proof, real=real),
        }

    def render(self) -> str:
        report = self.build_report()
        proof = report["proof"]
        real = report["real"]
        why = report["why_proof_has_candidates_but_real_does_not"]
        lines = [
            "Research Proof Vs Real",
            f"proof_inputs={proof.get('inputs_summary', '-')}",
            f"real_inputs={real.get('inputs_summary', '-')}",
            f"proof_uses_synthetic_evidence={proof.get('uses_synthetic_evidence', 'yes')}",
            f"real_uses_stored_historical_bars={real.get('uses_stored_historical_bars', 'no')}",
            f"proof_strategies_evaluated={int(proof.get('strategies_evaluated', 0) or 0)}",
            f"real_strategies_evaluated={int(real.get('strategies_evaluated', 0) or 0)}",
            f"proof_historical_windows_selected={int(proof.get('historical_windows_selected', 0) or 0)}",
            f"real_historical_windows_selected={int(real.get('historical_windows_selected', 0) or 0)}",
            f"proof_replay_evidence_counts={proof.get('replay_evidence_counts', '-')}",
            f"real_replay_evidence_counts={real.get('replay_evidence_counts', '-')}",
            f"proof_paper_sim_evidence_counts={proof.get('paper_sim_evidence_counts', '-')}",
            f"real_paper_sim_evidence_counts={real.get('paper_sim_evidence_counts', '-')}",
            f"real_raw_decisions_count={int(real.get('raw_decisions_count', 0) or 0)}",
            f"real_rejected_decisions_count={int(real.get('rejected_decisions_count', 0) or 0)}",
            f"proof_usable_decision_count={int(proof.get('usable_decision_count', 0) or 0)}",
            f"real_usable_decision_count={int(real.get('usable_decision_count', 0) or 0)}",
            f"proof_candidate_count={int(proof.get('candidate_count', 0) or 0)}",
            f"real_candidate_count={int(real.get('candidate_count', 0) or 0)}",
            f"proof_removal_candidate_count={int(proof.get('removal_candidate_count', 0) or 0)}",
            f"real_removal_candidate_count={int(real.get('removal_candidate_count', 0) or 0)}",
            f"proof_fitness_gates_applied={proof.get('fitness_gates_applied', '-')}",
            f"real_fitness_gates_applied={real.get('fitness_gates_applied', '-')}",
            f"proof_thresholds_applied={proof.get('thresholds_applied', '-')}",
            f"real_thresholds_applied={real.get('thresholds_applied', '-')}",
            f"why_proof_produces_candidates_but_real_does_not={why}",
        ]
        for item in list(real.get("top_rejected", []) or [])[:5]:
            lines.append(
                "real_top_rejected="
                f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | recommendation={item.get('recommendation', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        return "\n".join(lines)

    def _latest_real_cycle_row(self) -> dict[str, Any] | None:
        for row in self.usage_ledger.list_recent_tick_runs(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if (
                str(run.get("pipeline", "") or "") == "research_cycle"
                and str(run.get("source", "") or "") == "real_heartbeat"
            ):
                return row
        return None

    def _proof_summary(self, *, proof_result: dict[str, Any], proof_config: Any) -> dict[str, Any]:
        strategy_profiles = list(proof_result.get("strategy_profiles", []) or [])
        candidate_like = [
            item for item in strategy_profiles if str(item.get("internal_stage", "")) == "paper_candidate"
        ]
        removal_like = [
            item
            for item in strategy_profiles
            if str(item.get("internal_stage", "")) == "paper_removal_candidate"
        ]
        replay_evaluated = sum(1 for item in strategy_profiles if bool(item.get("research_evaluated")))
        paper_sim_evaluated = sum(1 for item in strategy_profiles if bool(item.get("paper_sim_evaluated")))
        return {
            "inputs_summary": (
                f"allowed_strategies={','.join(getattr(proof_config, 'research_allowed_strategies', ()) or ()) or '-'}"
                f"; crypto_symbols={','.join(getattr(proof_config, 'discovery_crypto_symbols', ()) or ()) or '-'}"
                f"; timeframe={getattr(proof_config, 'research_replay_timeframe', '-')}"
                f"; days={getattr(proof_config, 'research_replay_days', '-')}"
            ),
            "strategies_evaluated": int(proof_result.get("strategy_profiles_evaluated", 0) or 0),
            "historical_windows_selected": int(getattr(proof_config, "research_min_windows", 0) or 0),
            "replay_evidence_counts": f"profiles_with_replay={replay_evaluated}",
            "paper_sim_evidence_counts": f"profiles_with_paper_sim={paper_sim_evaluated}",
            "usable_decision_count": replay_evaluated,
            "candidate_count": len(candidate_like),
            "removal_candidate_count": len(removal_like),
            "fitness_gates_applied": "proof_research_runner,proof_shadow_signal_gates,manual_promotion_gate",
            "thresholds_applied": (
                f"min_windows={getattr(proof_config, 'research_min_windows', '-')};"
                f"min_proposals={getattr(proof_config, 'research_min_proposals', '-')};"
                f"min_net_return_pct={getattr(proof_config, 'research_min_net_return_pct', '-')};"
                f"min_net_win_rate={getattr(proof_config, 'research_min_net_win_rate', '-')}"
            ),
            "uses_synthetic_evidence": "yes",
        }

    def _real_cycle_summary(self, *, real_row: dict[str, Any] | None) -> dict[str, Any]:
        if not real_row:
            return {
                "inputs_summary": "-",
                "strategies_evaluated": 0,
                "historical_windows_selected": 0,
                "replay_evidence_counts": "-",
                "paper_sim_evidence_counts": "-",
                "raw_decisions_count": 0,
                "rejected_decisions_count": 0,
                "usable_decision_count": 0,
                "candidate_count": 0,
                "removal_candidate_count": 0,
                "fitness_gates_applied": "-",
                "thresholds_applied": "-",
                "top_rejected": [],
                "blockers": Counter(),
                "uses_stored_historical_bars": "no",
            }
        snapshot = real_row.get("state_snapshot_json", {}) if isinstance(real_row, dict) else {}
        run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
        decisions = list(state.get("decisions", []) or [])
        blockers: Counter[str] = Counter()
        top_rejected = []
        replay_profiles = 0
        paper_sim_profiles = 0
        for item in decisions:
            if int(item.get("proposals_created", 0) or 0) > 0:
                replay_profiles += 1
            if int(item.get("outcomes_recorded", 0) or 0) > 0:
                paper_sim_profiles += 1
            reasons = list(item.get("blocker_reasons", []) or [])
            if str(item.get("recommendation", "")) != "paper_sim_candidate" and len(top_rejected) < 5:
                top_rejected.append(
                    {
                        "strategy_id": str(item.get("strategy_id", "") or "-"),
                        "profile_id": str(item.get("profile_id", "") or "-"),
                        "recommendation": str(item.get("recommendation", "") or "-"),
                        "reason": reasons[0] if reasons else "no_blocker_reason_recorded",
                    }
                )
            for reason in reasons:
                label = str(reason or "").strip()
                if label:
                    blockers[label] += 1
        return {
            "inputs_summary": (
                f"source={run.get('source', '-')}; timeframe={run.get('timeframe', '-')};"
                f" days={run.get('days', '-')}; max_replay_timestamps={run.get('max_replay_timestamps', '-')}"
            ),
            "strategies_evaluated": int(state.get("strategy_profiles_evaluated", 0) or 0),
            "historical_windows_selected": len(state.get("replay_windows_tested", []) or []),
            "replay_evidence_counts": f"profiles_with_replay={replay_profiles}",
            "paper_sim_evidence_counts": f"profiles_with_paper_sim={paper_sim_profiles}",
            "raw_decisions_count": len(decisions),
            "rejected_decisions_count": sum(
                1 for item in decisions if str(item.get("recommendation", "")) != "paper_sim_candidate"
            ),
            "usable_decision_count": sum(
                1 for item in decisions if str(item.get("recommendation", "")) == "paper_sim_candidate"
            ),
            "candidate_count": int(state.get("paper_candidates_created", 0) or 0),
            "removal_candidate_count": int(state.get("paper_removal_candidates_created", 0) or 0),
            "fitness_gates_applied": "research_min_windows,research_min_proposals,research_min_net_return_pct,research_min_net_win_rate,allocation_backtest_policy",
            "thresholds_applied": (
                f"min_windows={getattr(self.config, 'research_min_windows', '-')};"
                f"min_proposals={getattr(self.config, 'research_min_proposals', '-')};"
                f"min_net_return_pct={getattr(self.config, 'research_min_net_return_pct', '-')};"
                f"min_net_win_rate={getattr(self.config, 'research_min_net_win_rate', '-')};"
                f"paper_backtest_in_allocation={'yes' if getattr(self.config, 'include_backtest_evidence_in_paper_fitness', False) else 'no'};"
                f"live_backtest_in_allocation={'yes' if getattr(self.config, 'include_backtest_evidence_in_live_fitness', False) else 'no'}"
            ),
            "top_rejected": top_rejected,
            "blockers": blockers,
            "uses_stored_historical_bars": "yes"
            if int(state.get("historical_windows_selected", 0) or 0) > 0
            else "no",
        }

    def _why_diff(self, *, proof: dict[str, Any], real: dict[str, Any]) -> str:
        reasons: list[str] = []
        if int(proof.get("candidate_count", 0) or 0) > int(real.get("candidate_count", 0) or 0):
            reasons.append("proof_runner_uses_synthetic_replay_and_paper_sim_evidence")
        blockers: Counter[str] = real.get("blockers", Counter()) or Counter()
        if blockers.get("paper_allocation_excludes_backtest_evidence", 0) or blockers.get("live_allocation_excludes_backtest_evidence", 0):
            reasons.append("real_runtime_blocks_allocation_from_backtest_evidence")
        if blockers.get("insufficient_sample_size", 0):
            reasons.append("real_runtime_failed_sample_size_threshold")
        if blockers.get("insufficient_replay_windows", 0):
            reasons.append("real_runtime_failed_replay_window_threshold")
        if blockers.get("net_return_below_threshold", 0) or blockers.get("win_rate_below_threshold", 0):
            reasons.append("real_runtime_failed_fitness_threshold")
        if not reasons:
            reasons.append("inspect_top_rejected_real_decisions")
        return ",".join(reasons)
