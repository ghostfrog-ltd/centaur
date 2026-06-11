from __future__ import annotations

from typing import Any

from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.reporting.symbol_subset_stability import normalize_symbol_subset_verdict
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = "Read-only paper-candidate decision report. No paper trades, approvals, or live settings were changed."


class PaperCandidateDecisionReport:
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
            lock_timeout_ms=None,
        )
        self.portfolio_planner = StrategyPortfolioResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
            operator_mode=True,
        )

    def build_report(self) -> dict[str, Any]:
        planner_report = self.portfolio_planner.build_report()
        ranked = list(planner_report.get("ranked_strategies", []) or [])
        known_best = self._find_strategy(
            ranked=ranked,
            summary=planner_report.get("current_known_best_candidate"),
        )
        status = self._paper_candidate_status(known_best)
        paper_candidate = known_best if status == "eligible" else {}
        action = self._next_required_action(known_best, planner_report)
        latest_evidence = self._latest_symbol_replay_evidence(known_best)
        wide = dict(known_best.get("wide_symbol_stability", {}) or {})
        branch_outcome = self._branch_outcome(
            known_best=known_best,
            latest_evidence=latest_evidence,
            wide_symbol_stability=wide,
        )
        rotation = self._rotation_decision(
            known_best=known_best,
            latest_evidence=latest_evidence,
            wide_symbol_stability=wide,
            planner_report=planner_report,
            ranked=ranked,
            branch_outcome=branch_outcome,
        )
        next_candidate = dict(rotation.get("next_candidate") or {})
        planner_requires_operational_followup = self._planner_requires_operational_followup(planner_report)
        if planner_requires_operational_followup:
            next_candidate = {}
        blocked_or_parked = self._blocked_or_parked_candidate(
            planner_report=planner_report,
            known_best=known_best,
        )
        has_followup_evidence = bool(latest_evidence) or bool(wide)
        paper_candidate_status = (
            "eligible"
            if status == "eligible"
            else ("none_approved" if rotation.get("rotation_required") and has_followup_evidence else status)
        )
        return {
            "title": "Paper Candidate Decision Report",
            "current_known_best_candidate": self._identity_string(known_best),
            "current_paper_candidate": self._identity_string(paper_candidate) if paper_candidate else None,
            "blocked_or_parked_candidate": blocked_or_parked,
            "portfolio_research_status": str(planner_report.get("portfolio_research_status", "") or ""),
            "research_universe_status": str(planner_report.get("research_universe_status", "") or ""),
            "paper_candidate_status": paper_candidate_status,
            "paper_trading_allowed": "yes" if self._paper_trading_allowed(paper_candidate) else "no",
            "paper_block_reason": self._paper_block_reason(known_best, status),
            "failed_audit_reason": self._failed_audit_reason(known_best),
            "blocked_candidate": self._identity_string(known_best) if status == "blocked" else "",
            "blocked_reason": self._paper_block_reason(known_best, status),
            "latest_followup_verdict": self._latest_followup_verdict(latest_evidence, wide),
            "branch_outcome": branch_outcome,
            "rotation_required": "yes" if rotation.get("rotation_required") else "no",
            "rotation_reason": str(rotation.get("rotation_reason", "") or ""),
            "next_candidate_to_review": self._identity_string(next_candidate) if next_candidate else "",
            "next_candidate_reason": str(rotation.get("next_candidate_reason", "") or ""),
            "next_required_action": action,
            "next_required_operator_action": self._next_required_operator_action(planner_report, action),
            "terminal_research_state": str(planner_report.get("terminal_research_state", "") or ""),
            "no_actionable_reason": str(planner_report.get("no_actionable_reason", "") or ""),
            "next_safe_operator_action": str(planner_report.get("next_safe_operator_action", "") or ""),
            "next_check_command": str(planner_report.get("next_check_command", "") or ""),
            "recommended_next_command": self._recommended_next_command(
                known_best=known_best,
                planner_report=planner_report,
                next_required_action=action,
                rotation=rotation,
            ),
            "next_actionable_research_candidate": self._identity_string(next_candidate) if next_candidate else "",
            "next_actionable_research_reason": str(rotation.get("next_candidate_reason", "") or ""),
            "next_actionable_research_command": str(rotation.get("next_recommended_command", "") or ""),
            "selected_next_strategy": self._identity_string(next_candidate) if next_candidate else "",
            "next_portfolio_action": str(rotation.get("next_research_action", "") or ""),
            "next_research_candidate": self._identity_string(next_candidate) if next_candidate else "",
            "next_research_action": str(rotation.get("next_research_action", "") or ""),
            "unblock_condition": self._unblock_condition(known_best),
            "permanent_stop_condition": self._permanent_stop_condition(known_best),
            "branch_under_review": str(known_best.get("stopped_branch_name", "") or ""),
            "stopped_branch": str(planner_report.get("stopped_branch", "") or ""),
            "stopped_reason": self._stopped_reason(known_best, planner_report),
            "current_sample_size": int(known_best.get("latest_sample_size", 0) or 0),
            "current_net_return_after_costs": float(known_best.get("latest_net_return_after_costs", 0.0) or 0.0),
            "wide_sample_size": int(planner_report.get("wide_sample_size", 0) or 0),
            "wide_net_return_after_costs": float(planner_report.get("wide_net_return_after_costs", 0.0) or 0.0),
            "wider_replay_execution_status": self._wider_replay_execution_status(latest_evidence),
            "wider_replay_verdict": self._wider_replay_verdict(latest_evidence, wide),
            "wider_replay_symbol_specific": self._wider_replay_symbol_specific(known_best, latest_evidence, wide),
            "wider_replay_sample_size": self._wider_replay_sample_size(latest_evidence, wide),
            "wider_replay_net_return_after_costs": self._wider_replay_net_return_after_costs(latest_evidence, wide),
            "wider_replay_drawdown": self._wider_replay_drawdown(latest_evidence, wide),
            "wider_replay_sample_size_adequate": self._wider_replay_sample_size_adequate(known_best, latest_evidence, wide),
            "wider_replay_symbol_diversity": self._wider_replay_symbol_diversity(latest_evidence, wide),
            "required_out_of_sample_window": self._required_out_of_sample_window(known_best),
            "minimum_required_sample_size": self._minimum_required_sample_size(known_best),
            "required_symbol_diversity": self._required_symbol_diversity(known_best),
            "required_stability_checks": self._required_stability_checks(known_best),
            "safety_statement": SAFETY_STATEMENT,
        }

    def render(self) -> str:
        report = self.build_report()
        lines = [
            str(report.get("title", "Paper Candidate Decision Report")),
            f"rotation_required={report.get('rotation_required', '') or ''}",
            f"branch_outcome={report.get('branch_outcome', '') or ''}",
            "",
            "Final Summary",
            f"current_known_best_candidate={report.get('current_known_best_candidate', '') or ''}",
            f"current_paper_candidate={report.get('current_paper_candidate', '') or ''}",
            f"paper_candidate_status={report.get('paper_candidate_status', '') or ''}",
            f"paper_trading_allowed={report.get('paper_trading_allowed', '') or ''}",
            f"blocked_or_parked_candidate={report.get('blocked_or_parked_candidate', '') or ''}",
            f"next_actionable_research_candidate={report.get('next_actionable_research_candidate', '') or ''}",
            f"next_actionable_research_reason={report.get('next_actionable_research_reason', '') or ''}",
            f"next_actionable_research_command={report.get('next_actionable_research_command', '') or ''}",
            f"portfolio_research_status={report.get('portfolio_research_status', '') or ''}",
            f"research_universe_status={report.get('research_universe_status', '') or ''}",
            f"next_required_operator_action={report.get('next_required_operator_action', '') or ''}",
            f"terminal_research_state={report.get('terminal_research_state', '') or ''}",
            f"no_actionable_reason={report.get('no_actionable_reason', '') or ''}",
            f"next_safe_operator_action={report.get('next_safe_operator_action', '') or ''}",
            f"next_check_command={report.get('next_check_command', '') or ''}",
            f"selected_next_strategy={report.get('selected_next_strategy', '') or ''}",
            f"next_portfolio_action={report.get('next_portfolio_action', '') or ''}",
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def _find_strategy(
        self,
        *,
        ranked: list[dict[str, Any]],
        summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        summary = dict(summary or {})
        for item in ranked:
            if (
                str(item.get("base_strategy_id", "") or "") == str(summary.get("base_strategy_id", "") or "")
                and str(item.get("profile_id", "") or "") == str(summary.get("profile_id", "") or "")
                and str(item.get("timeframe", "") or "") == str(summary.get("timeframe", "") or "")
            ):
                return item
        return {}

    def _identity_string(self, item: dict[str, Any]) -> str:
        if not item:
            return ""
        return (
            f"{str(item.get('base_strategy_id', '') or '')}/"
            f"{str(item.get('profile_id', '') or '')}/"
            f"{str(item.get('timeframe', '') or '')}"
        )

    def _paper_candidate_status(self, known_best: dict[str, Any]) -> str:
        if str(known_best.get("research_status", "") or "") == "paper_candidate_requires_manual_approval":
            return "eligible"
        return "blocked"

    def _paper_trading_allowed(self, paper_candidate: dict[str, Any]) -> bool:
        if not paper_candidate:
            return False
        promotion = self.usage_ledger.get_strategy_promotion(
            strategy_id=str(paper_candidate.get("base_strategy_id", "") or ""),
            profile_id=str(paper_candidate.get("profile_id", "") or ""),
        ) or {}
        return bool(promotion.get("paper_approved"))

    def _paper_block_reason(self, known_best: dict[str, Any], status: str) -> str:
        if status != "blocked":
            return ""
        audit_verdict = str(((known_best.get("audit_report", {}) or {}).get("audit_verdict", "")) or "")
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "concentration_fragility"
        if audit_verdict == "paper_candidate_reject_due_to_drawdown":
            return "drawdown_limit"
        return {
            "data_gap": "data_gap",
            "insufficient_data_after_precompute": "insufficient_data",
            "insufficient_data": "insufficient_data",
            "insufficient_history_after_variant_research": "insufficient_data",
            "deprioritise_until_new_data": "deprioritised",
            "no_viable_signal_after_variant_research": "deprioritised",
            "no_viable_signal_after_precompute": "deprioritised",
            "deprioritise": "deprioritised",
            "retire_candidate": "retired",
            "untested_strategy": "untested_strategy",
            "audit_required": "audit_required",
            "active_research": "active_research",
        }.get(str(known_best.get("research_status", "") or ""), "not_paper_eligible")

    def _failed_audit_reason(self, known_best: dict[str, Any]) -> str:
        return str(((known_best.get("audit_report", {}) or {}).get("audit_verdict", "")) or "")

    def _next_required_action(self, known_best: dict[str, Any], planner_report: dict[str, Any]) -> str:
        if self._planner_requires_operational_followup(planner_report):
            return str(planner_report.get("next_portfolio_action", "") or "no_actionable_candidate")
        if str(known_best.get("research_status", "") or "") == "promising_but_failed_audit":
            return "collect_more_out_of_sample_data"
        return str(planner_report.get("next_portfolio_action", "") or "review_portfolio_research")

    def _next_required_operator_action(self, planner_report: dict[str, Any], next_required_action: str) -> str:
        next_data_runtime_action = dict(planner_report.get("next_data_runtime_action", {}) or {})
        return str(
            planner_report.get("next_required_operator_action", "")
            or next_data_runtime_action.get("data_or_runtime_action", "")
            or next_data_runtime_action.get("action", "")
            or next_required_action
            or ""
        )

    def _recommended_next_command(
        self,
        *,
        known_best: dict[str, Any],
        planner_report: dict[str, Any],
        next_required_action: str,
        rotation: dict[str, Any],
    ) -> str:
        if rotation.get("rotation_required"):
            return str(rotation.get("next_recommended_command", "") or ".venv-mac/bin/python main.py --strategy-portfolio-research-planner")
        planner_action = str(planner_report.get("next_portfolio_action", "") or "")
        if planner_action in {
            "optimise_or_precompute_replay_dataset",
            "backfill_or_resample_data",
            "adjust_signal_generation_research_only",
            "expand_signal_generation_research_only",
            "generate_new_research_candidates",
            "precompute_bounded_dip_rebound_15Min_outcomes",
            "optimise_specific_crypto_15Min_replay_cache",
            "precompute_specific_replay_cache",
            "no_actionable_candidate",
        }:
            next_data_runtime_action = dict(planner_report.get("next_data_runtime_action", {}) or {})
            return str(
                planner_report.get("proposed_next_command", "")
                or next_data_runtime_action.get("data_or_runtime_action", "")
                or next_data_runtime_action.get("action", "")
                or ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset"
            )
        if next_required_action == "collect_more_out_of_sample_data":
            variant_id = str(known_best.get("selected_variant_id", "") or "")
            symbol = str(known_best.get("selected_symbol", "") or "WDC")
            return (
                ".venv-mac/bin/python main.py --collect-symbol-replay-evidence "
                f"--base-strategy {known_best.get('base_strategy_id', '')} "
                f"--profile-id {known_best.get('profile_id', '')} "
                f"--timeframe {known_best.get('timeframe', '')} "
                f"--variant-id {variant_id} --symbol {symbol}"
            ).strip()
        return str(planner_report.get("proposed_next_command", "") or ".venv-mac/bin/python main.py --strategy-portfolio-research-planner")

    def _blocked_or_parked_candidate(
        self,
        *,
        planner_report: dict[str, Any],
        known_best: dict[str, Any],
    ) -> str:
        summary = dict(planner_report.get("blocked_or_parked_candidate") or {})
        if summary:
            candidate = self._find_strategy(
                ranked=list(planner_report.get("ranked_strategies", []) or []),
                summary=summary,
            )
            if candidate:
                return self._identity_string(candidate)
            return self._identity_string(summary)
        if known_best and str(known_best.get("research_status", "") or "") != "paper_candidate_requires_manual_approval":
            return self._identity_string(known_best)
        return str(planner_report.get("stopped_branch", "") or "")

    def _unblock_condition(self, known_best: dict[str, Any]) -> str:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return (
                "passes paper-candidate audit after wider replay with adequate sample size, "
                "positive net return after costs, acceptable drawdown, and no single-symbol concentration fragility"
            )
        return "meets paper-candidate policy and manual approval requirements"

    def _permanent_stop_condition(self, known_best: dict[str, Any]) -> str:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return "wider replay remains negative, unstable, or concentrated after required out-of-sample validation"
        return "candidate remains below paper-candidate quality requirements after required validation"

    def _stopped_reason(self, known_best: dict[str, Any], planner_report: dict[str, Any]) -> str:
        audit_reason = self._paper_block_reason(known_best, "blocked")
        if audit_reason:
            return audit_reason
        return str(planner_report.get("stopped_reason", "") or "")

    def _required_out_of_sample_window(self, known_best: dict[str, Any]) -> str:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return "wider stored historical bar period with fresh out-of-sample replay coverage"
        return ""

    def _minimum_required_sample_size(self, known_best: dict[str, Any]) -> int:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return 200
        return 0

    def _required_symbol_diversity(self, known_best: dict[str, Any]) -> str:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return "at least 3 symbols with no single symbol dominating profit contribution"
        return ""

    def _required_stability_checks(self, known_best: dict[str, Any]) -> list[str]:
        if self._failed_audit_reason(known_best) == "paper_candidate_reject_due_to_concentration":
            return [
                "positive_net_return_after_costs",
                "acceptable_drawdown",
                "adequate_sample_size",
                "no_single_symbol_concentration_fragility",
            ]
        return []

    def _latest_symbol_replay_evidence(self, known_best: dict[str, Any]) -> dict[str, Any]:
        variant_id = str(known_best.get("selected_variant_id", "") or "")
        if not variant_id:
            return {}
        symbol = str(known_best.get("selected_symbol", "") or "").upper()
        for item in self.usage_ledger.list_strategy_variant_evaluations(
            base_strategy_id=str(known_best.get("base_strategy_id", "") or ""),
            profile_id=str(known_best.get("profile_id", "") or ""),
            timeframe=str(known_best.get("timeframe", "") or ""),
            variant_id=variant_id,
            limit=50,
        ):
            raw = dict(item.get("raw_json", {}) or {})
            if raw.get("report_type") != "symbol_replay_evidence_plan":
                continue
            if symbol and str(raw.get("symbol", "")).upper() != symbol:
                continue
            return raw
        return {}

    def _branch_outcome(
        self,
        *,
        known_best: dict[str, Any],
        latest_evidence: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
    ) -> str:
        if self._paper_trading_allowed(known_best):
            return "paper_approved"
        verdict = str((wide_symbol_stability or {}).get("stability_verdict", "") or "")
        verdict = normalize_symbol_subset_verdict(verdict)
        if verdict in {"symbol_unstable", "symbol_not_promising"}:
            return "permanently_stopped"
        if verdict == "symbol_promising_and_stable":
            return "eligible_for_reaudit"
        if str((latest_evidence or {}).get("execution_status", "") or "") == "executed_research_only":
            return "still_blocked"
        return "still_blocked"

    def _latest_followup_verdict(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> str:
        wide_verdict = str((wide_symbol_stability or {}).get("stability_verdict", "") or "")
        wide_verdict = normalize_symbol_subset_verdict(wide_verdict)
        if wide_verdict:
            return wide_verdict
        evidence_verdict = str((latest_evidence or {}).get("executed_wider_stability_verdict", "") or "")
        if evidence_verdict:
            return normalize_symbol_subset_verdict(evidence_verdict)
        return str((latest_evidence or {}).get("evidence_action_verdict", "") or "not_run")

    def _rotation_decision(
        self,
        *,
        known_best: dict[str, Any],
        latest_evidence: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
        planner_report: dict[str, Any],
        ranked: list[dict[str, Any]],
        branch_outcome: str,
    ) -> dict[str, Any]:
        latest_followup_verdict = self._latest_followup_verdict(latest_evidence, wide_symbol_stability)
        followup_unresolved = latest_followup_verdict in {
            "no_usable_subset_data",
            "symbol_promising_but_insufficient",
        }
        rotation_required = (
            str(known_best.get("research_status", "") or "") == "promising_but_failed_audit"
            and branch_outcome == "still_blocked"
            and followup_unresolved
        )
        next_candidate = self._next_candidate_to_review(planner_report=planner_report, ranked=ranked)
        next_research_action = self._next_research_action(
            next_candidate=next_candidate,
            rotation_required=rotation_required,
            planner_report=planner_report,
        )
        return {
            "rotation_required": rotation_required,
            "rotation_reason": "followup_evidence_did_not_unblock_candidate" if rotation_required else "",
            "next_candidate": next_candidate,
            "next_candidate_reason": self._next_candidate_reason(next_candidate=next_candidate, rotation_required=rotation_required),
            "next_research_action": next_research_action,
            "next_recommended_command": self._next_recommended_research_command(
                planner_report=planner_report,
                next_candidate=next_candidate,
                next_research_action=next_research_action,
            ),
        }

    def _next_candidate_to_review(
        self,
        *,
        planner_report: dict[str, Any],
        ranked: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self._planner_requires_operational_followup(planner_report):
            return {}
        selected = dict(planner_report.get("selected_next_strategy") or {})
        if selected:
            return self._find_strategy(ranked=ranked, summary=selected)
        summary = dict(planner_report.get("next_paper_candidate") or {})
        if summary:
            return self._find_strategy(ranked=ranked, summary=summary)
        return {}

    def _planner_requires_operational_followup(self, planner_report: dict[str, Any]) -> bool:
        next_candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        if next_candidate:
            return False
        planner_action = str(planner_report.get("next_portfolio_action", "") or "")
        if planner_action == "no_actionable_candidate":
            return True
        return planner_action in {
            "optimise_or_precompute_replay_dataset",
            "backfill_or_resample_data",
            "adjust_signal_generation_research_only",
            "precompute_bounded_dip_rebound_15Min_outcomes",
            "optimise_specific_crypto_15Min_replay_cache",
            "precompute_specific_replay_cache",
        }

    def _next_candidate_reason(self, *, next_candidate: dict[str, Any], rotation_required: bool) -> str:
        if not next_candidate:
            return "no_remaining_paper_candidate_met_safe_selection_rules"
        status = str(next_candidate.get("research_status", "") or "")
        if status == "audit_required":
            return "best_available_candidate_requires_read_only_audit_before_any_manual_paper_decision"
        if status in {"untested_strategy", "insufficient_data", "active_research"}:
            return "best_available_candidate_from_portfolio_planner"
        if rotation_required:
            return "next_best_available_candidate_after_blocked_followup_remained_unresolved"
        return "best_available_candidate_from_portfolio_planner"

    def _next_research_action(
        self,
        *,
        next_candidate: dict[str, Any],
        rotation_required: bool,
        planner_report: dict[str, Any],
    ) -> str:
        planner_next_candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        if planner_next_candidate and next_candidate and self._identity_string(planner_next_candidate) == self._identity_string(next_candidate):
            return str(planner_report.get("next_portfolio_action", "") or "diagnose_next_best_strategy")
        if next_candidate:
            status = str(next_candidate.get("research_status", "") or "")
            if status == "audit_required":
                return "audit_paper_candidate"
            return "diagnose_next_best_strategy"
        planner_action = str(planner_report.get("next_portfolio_action", "") or "")
        return planner_action or "no_actionable_candidate"

    def _next_recommended_research_command(
        self,
        *,
        planner_report: dict[str, Any],
        next_candidate: dict[str, Any],
        next_research_action: str,
    ) -> str:
        if self._planner_requires_operational_followup(planner_report):
            return ""
        planner_next_candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        if planner_next_candidate and next_candidate and self._identity_string(planner_next_candidate) == self._identity_string(next_candidate):
            return str(
                planner_report.get("next_actionable_research_command", "")
                or planner_report.get("proposed_next_command", "")
                or ""
            )
        if next_research_action == "audit_paper_candidate" and next_candidate:
            variant_id = str(next_candidate.get("selected_variant_id", "") or "")
            variant_clause = f" --variant-id {variant_id}" if variant_id else ""
            return (
                ".venv-mac/bin/python main.py --paper-candidate-audit "
                f"--base-strategy {next_candidate.get('base_strategy_id', '')} "
                f"--profile-id {next_candidate.get('profile_id', '')} "
                f"--timeframe {next_candidate.get('timeframe', '')}{variant_clause}"
            ).strip()
        if next_research_action == "diagnose_next_best_strategy" and next_candidate:
            return (
                ".venv-mac/bin/python main.py --diagnose-next-best-strategy "
                f"--base-strategy {next_candidate.get('base_strategy_id', '')} "
                f"--profile-id {next_candidate.get('profile_id', '')} "
                f"--timeframe {next_candidate.get('timeframe', '')}"
            ).strip()
        return str(planner_report.get("proposed_next_command", "") or ".venv-mac/bin/python main.py --strategy-portfolio-research-planner")

    def _wider_replay_execution_status(self, latest_evidence: dict[str, Any]) -> str:
        return str((latest_evidence or {}).get("execution_status", "") or "not_run")

    def _wider_replay_verdict(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> str:
        verdict = str((wide_symbol_stability or {}).get("stability_verdict", "") or "")
        if verdict:
            return normalize_symbol_subset_verdict(verdict)
        evidence_verdict = str((latest_evidence or {}).get("evidence_action_verdict", "") or "unavailable")
        if evidence_verdict == "unavailable":
            return evidence_verdict
        return normalize_symbol_subset_verdict(evidence_verdict)

    def _wider_replay_symbol_specific(
        self,
        known_best: dict[str, Any],
        latest_evidence: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
    ) -> str:
        symbol = str(known_best.get("selected_symbol", "") or "").upper()
        if not symbol:
            return "unknown"
        rows = list((((wide_symbol_stability or {}).get("cohort_comparison", {}) or {}).get("rows", []) or []))
        if rows:
            return "yes" if any(str(item.get("symbol", "")).upper() == symbol for item in rows) else "no"
        return "yes" if str((latest_evidence or {}).get("symbol", "")).upper() == symbol else "unknown"

    def _wider_replay_sample_size(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> int:
        summary = dict((wide_symbol_stability or {}).get("selected_symbol_summary", {}) or {})
        if summary:
            return int(summary.get("sample_size", 0) or 0)
        return int((((latest_evidence or {}).get("executed_wider_symbol_summary", {}) or {}).get("sample_size", 0) or 0))

    def _wider_replay_net_return_after_costs(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> float:
        summary = dict((wide_symbol_stability or {}).get("selected_symbol_summary", {}) or {})
        if summary:
            return float(summary.get("net_return_after_costs", 0.0) or 0.0)
        return float((((latest_evidence or {}).get("executed_wider_symbol_summary", {}) or {}).get("net_return_after_costs", 0.0) or 0.0))

    def _wider_replay_drawdown(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> Any:
        summary = dict((wide_symbol_stability or {}).get("selected_symbol_summary", {}) or {})
        if summary:
            return summary.get("drawdown")
        return ((latest_evidence or {}).get("executed_wider_symbol_summary", {}) or {}).get("drawdown")

    def _wider_replay_sample_size_adequate(
        self,
        known_best: dict[str, Any],
        latest_evidence: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
    ) -> str:
        sample_size = self._wider_replay_sample_size(latest_evidence, wide_symbol_stability)
        return "yes" if sample_size >= self._minimum_required_sample_size(known_best) else "no"

    def _wider_replay_symbol_diversity(self, latest_evidence: dict[str, Any], wide_symbol_stability: dict[str, Any]) -> str:
        cohort = dict((wide_symbol_stability or {}).get("cohort_comparison", {}) or {})
        rows = list(cohort.get("rows", []) or [])
        if rows:
            return "improved" if len({str(item.get('symbol', '')).upper() for item in rows if item.get('symbol')}) >= 3 else "still_concentrated"
        execution_status = str((latest_evidence or {}).get("execution_status", "") or "")
        if execution_status == "executed_research_only":
            return "unknown"
        return "still_concentrated"
