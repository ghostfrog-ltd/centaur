from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport
from app.framework.reporting.paper_candidate_audit import PaperCandidateAuditReport
from app.framework.reporting.symbol_replay_evidence_plan import SymbolReplayEvidencePlanReport
from app.framework.reporting.strategy_research_planner import StrategyResearchPlannerReport
from app.framework.reporting.strategy_variant_research import (
    StrategyVariantResearchReport,
    StrategyVariantResearchService,
)
from app.framework.reporting.specific_replay_cache_precompute import (
    SpecificReplayCachePrecomputeReport,
)
from app.framework.reporting.symbol_subset_stability import SymbolSubsetStabilityReport
from app.framework.reporting.symbol_subset_stability import normalize_symbol_subset_verdict
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = "Research-only portfolio planner. No paper or live approval has been changed."
DEFAULT_RESEARCH_EXPANSION_COMMAND = ".venv-mac/bin/python main.py --research-expansion-planner"
DEFAULT_NO_ACTIONABLE_CHECK_COMMAND = ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
_GENERATED_CANDIDATE_METADATA_KEY = "__research_candidate_metadata__"


@dataclass(frozen=True)
class _StrategyIdentity:
    base_strategy_id: str
    profile_id: str
    timeframe: str


@dataclass(frozen=True)
class _AutopilotActionIdentity:
    base_strategy_id: str
    profile_id: str
    timeframe: str
    variant_id: str
    action_type: str
    command_type: str


class StrategyPortfolioResearchPlannerReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        operator_mode: bool = True,
    ) -> None:
        self.config = config or load_runtime_config()
        self.operator_mode = bool(operator_mode)
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=True,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=None,
        )
        self.research_usage_ledger = self.usage_ledger if usage_ledger is not None else UsageLedger(
            config=self.config,
            read_only=False,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )
        self.variant_reporter = StrategyVariantResearchReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.variant_service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.research_usage_ledger,
        )
        self.loss_reporter = StrategyLossDiagnosisReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.audit_reporter = PaperCandidateAuditReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.strategy_planner = StrategyResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.symbol_replay_evidence_reporter = SymbolReplayEvidencePlanReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.symbol_stability_reporter = SymbolSubsetStabilityReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self._cached_definitions: list[dict[str, Any]] | None = None
        self._cached_latest_decisions: list[dict[str, Any]] | None = None
        self._cached_promotions: dict[tuple[str, str], dict[str, Any]] = {}
        self._cached_variant_reports: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._cached_loss_reports: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._cached_strategy_plans: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._cached_audit_reports: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._cached_wide_stability: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self._cached_strategy_evaluations: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._cached_latest_autopilot_no_progress: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._cached_latest_signal_generation_diagnosis: dict[tuple[str, str, str], dict[str, Any]] = {}

    def build_report(
        self,
        *,
        parked_candidate_keys_this_run: list[str] | None = None,
    ) -> dict[str, Any]:
        run_scoped_parked_candidate_keys = self._normalise_parked_candidate_keys(
            parked_candidate_keys_this_run
        )
        strategies = [self._build_strategy_row(identity) for identity in self._identities()]
        ranked = sorted(
            strategies,
            key=lambda item: (
                int(item.get("priority_rank", 99) or 99),
                -float(item.get("priority_score", 0.0) or 0.0),
                -float(item.get("latest_sample_size", 0) or 0),
                str(item.get("base_strategy_id", "")),
                str(item.get("profile_id", "")),
            ),
        )
        stopped_branch = self._latest_stopped_branch(ranked)
        current_known_best = self._select_current_known_best_candidate(strategies)
        blocked_or_parked = self._blocked_or_parked_candidate(current_known_best)
        selected, selection_diagnostics = self._select_next_actionable_research_candidate(
            ranked,
            blocked_or_parked_candidate=blocked_or_parked,
            parked_candidate_keys_this_run=run_scoped_parked_candidate_keys,
        )
        next_paper_candidate = self._select_next_paper_candidate(ranked)
        selected_next_strategy = {
            "base_strategy_id": str(selected.get("base_strategy_id", "") or ""),
            "profile_id": str(selected.get("profile_id", "") or ""),
            "timeframe": str(selected.get("timeframe", "") or ""),
        } if selected else None
        next_paper_candidate_summary = self._candidate_summary(next_paper_candidate) if next_paper_candidate else None
        blocked_or_parked_summary = self._candidate_summary(blocked_or_parked) if blocked_or_parked else None
        next_actionable_summary = self._candidate_summary(selected) if selected else None
        selected_next_experiment_type = str(selected.get("latest_planner_recommendation", "") or "")
        if not selected_next_experiment_type:
            selected_next_experiment_type = self._default_experiment_type(selected)
        next_data_runtime_action = self._next_data_runtime_action(ranked, selected)
        research_expansion = self._research_expansion_state(
            ranked=ranked,
            next_data_runtime_action=next_data_runtime_action,
        )
        next_portfolio_action = self._next_portfolio_action(selected, ranked)
        if not selected and next_data_runtime_action:
            next_portfolio_action = str(next_data_runtime_action.get("action", "") or "no_actionable_candidate")
        elif not selected and not next_portfolio_action:
            next_portfolio_action = "no_actionable_candidate"
        next_required_operator_action = str(
            research_expansion.get("next_required_operator_action", "")
            or next_data_runtime_action.get("data_or_runtime_action", "")
            or next_data_runtime_action.get("action", "")
            or next_portfolio_action
            or "no_actionable_candidate"
        )
        no_actionable_plan = self._no_actionable_candidate_plan(
            ranked=ranked,
            research_expansion=research_expansion,
            next_data_runtime_action=next_data_runtime_action,
        )
        runtime_action_diagnostics = self._runtime_action_diagnostics(
            ranked=ranked,
            next_data_runtime_action=next_data_runtime_action,
        )
        return {
            "title": "Strategy Portfolio Research Planner",
            "ranked_strategies": ranked,
            "selected_next_strategy": selected_next_strategy,
            "next_paper_candidate": next_paper_candidate_summary,
            "selected_next_experiment_type": selected_next_experiment_type,
            "current_known_best_candidate": self._candidate_summary(current_known_best),
            "blocked_or_parked_candidate": blocked_or_parked_summary,
            "next_actionable_research_candidate": next_actionable_summary,
            "next_actionable_research_reason": self._portfolio_reason(selected, ranked),
            "next_actionable_research_command": self._proposed_next_command(selected, ranked),
            "run_scoped_parked_candidates_received": list(run_scoped_parked_candidate_keys),
            "next_actionable_research_candidate_diagnostics": selection_diagnostics,
            "next_data_runtime_action": next_data_runtime_action,
            "portfolio_research_status": str(research_expansion.get("portfolio_research_status", "") or "research_in_progress"),
            "research_universe_status": str(research_expansion.get("research_universe_status", "") or "active_current_strategy_set"),
            "research_expansion": research_expansion,
            "why_not_selected_for_paper": self._why_not_selected_for_paper(current_known_best),
            "stopped_branch": str(stopped_branch.get("branch_name", "") or ""),
            "stopped_reason": str(stopped_branch.get("stability_verdict", "") or ""),
            "wide_sample_size": int(stopped_branch.get("wide_sample_size", 0) or 0),
            "wide_net_return_after_costs": float(stopped_branch.get("wide_net_return_after_costs", 0.0) or 0.0),
            "reason": self._portfolio_reason(selected, ranked),
            "proposed_next_command": self._proposed_next_command(selected, ranked),
            "next_portfolio_action": next_portfolio_action,
            "next_required_operator_action": next_required_operator_action,
            "terminal_research_state": str(no_actionable_plan.get("terminal_research_state", "") or ""),
            "no_actionable_reason": str(no_actionable_plan.get("no_actionable_reason", "") or ""),
            "waiting_for": str(no_actionable_plan.get("waiting_for", "") or ""),
            "minimum_new_data_required": str(no_actionable_plan.get("minimum_new_data_required", "") or ""),
            "data_sources_needed": list(no_actionable_plan.get("data_sources_needed", []) or []),
            "research_universe_expansion_options": list(no_actionable_plan.get("research_universe_expansion_options", []) or []),
            "next_safe_operator_action": str(no_actionable_plan.get("next_safe_operator_action", "") or ""),
            "next_safe_operator_command": str(no_actionable_plan.get("next_safe_operator_command", "") or ""),
            "precompute_mapping_attempted": str(runtime_action_diagnostics.get("precompute_mapping_attempted", "") or ""),
            "mapped_precompute_command": str(runtime_action_diagnostics.get("mapped_precompute_command", "") or ""),
            "precompute_already_completed": str(runtime_action_diagnostics.get("precompute_already_completed", "") or ""),
            "why_next_safe_operator_command_blank": str(
                runtime_action_diagnostics.get("why_next_safe_operator_command_blank", "") or ""
            ),
            "next_check_command": str(no_actionable_plan.get("next_check_command", "") or ""),
            "no_actionable_candidate_plan": no_actionable_plan,
            "execution_available": self._execution_available(selected, ranked),
            "untested_strategies": [self._candidate_summary(item) for item in ranked if item.get("research_status") == "untested_strategy"],
            "data_gap_strategies": [self._candidate_summary(item) for item in ranked if item.get("research_status") == "data_gap"],
            "bad_strategies": [
                self._candidate_summary(item)
                for item in ranked
                if item.get("research_status") in {"deprioritise", "retire_candidate"}
            ],
            "deprioritised_strategies": [self._candidate_summary(item) for item in ranked if item.get("research_status") == "deprioritise"],
            "promising_but_failed_audit": [
                self._candidate_summary(item) for item in ranked if item.get("research_status") == "promising_but_failed_audit"
            ],
            "stopped_failed_branches": [self._stopped_or_failed_branch_summary(item) for item in ranked if self._is_stopped_or_failed_branch(item)],
            "safety_statement": SAFETY_STATEMENT,
        }

    def render(self) -> str:
        report = self.build_report()
        selected = report.get("selected_next_strategy") or {}
        lines = [
            str(report.get("title", "Strategy Portfolio Research Planner")),
            f"ranked_strategies_count={len(report.get('ranked_strategies', []) or [])}",
            f"execution_available={'yes' if report.get('execution_available') else 'no'}",
            "",
            "Final Summary",
            (
                "current_known_best_candidate="
                f"{self._summary_identity(report.get('current_known_best_candidate'))}"
            ),
            "current_paper_candidate=",
            "paper_candidate_status=",
            "paper_trading_allowed=",
            (
                "blocked_or_parked_candidate="
                f"{self._summary_identity(report.get('blocked_or_parked_candidate'))}"
            ),
            (
                "next_actionable_research_candidate="
                f"{self._summary_identity(report.get('next_actionable_research_candidate'))}"
            ),
            f"next_actionable_research_reason={report.get('next_actionable_research_reason', '') or ''}",
            f"next_actionable_research_command={report.get('next_actionable_research_command', '') or ''}",
            f"portfolio_research_status={report.get('portfolio_research_status', '') or ''}",
            f"research_universe_status={report.get('research_universe_status', '') or ''}",
            f"next_data_runtime_action={str((report.get('next_data_runtime_action', {}) or {}).get('data_or_runtime_action', '') or '')}",
            (
                "selected_next_strategy="
                f"{selected.get('base_strategy_id', '') or ''}/"
                f"{selected.get('profile_id', '') or ''}/"
                f"{selected.get('timeframe', '') or ''}"
            ),
            f"next_portfolio_action={report.get('next_portfolio_action', '') or ''}",
            f"next_required_operator_action={report.get('next_required_operator_action', '') or ''}",
            f"terminal_research_state={report.get('terminal_research_state', '') or ''}",
            f"no_actionable_reason={report.get('no_actionable_reason', '') or ''}",
            f"waiting_for={report.get('waiting_for', '') or ''}",
            f"minimum_new_data_required={report.get('minimum_new_data_required', '') or ''}",
            f"data_sources_needed={','.join(report.get('data_sources_needed', []) or [])}",
            f"research_universe_expansion_options={','.join(report.get('research_universe_expansion_options', []) or [])}",
            f"next_safe_operator_action={report.get('next_safe_operator_action', '') or ''}",
            f"next_safe_operator_command={report.get('next_safe_operator_command', '') or ''}",
            f"precompute_mapping_attempted={report.get('precompute_mapping_attempted', '') or ''}",
            f"mapped_precompute_command={report.get('mapped_precompute_command', '') or ''}",
            f"precompute_already_completed={report.get('precompute_already_completed', '') or ''}",
            f"why_next_safe_operator_command_blank={report.get('why_next_safe_operator_command_blank', '') or ''}",
            f"next_check_command={report.get('next_check_command', '') or ''}",
            f"data_gap_strategies_count={len(report.get('data_gap_strategies', []) or [])}",
            f"bad_strategies_count={len(report.get('bad_strategies', []) or [])}",
            f"untested_strategies_count={len(report.get('untested_strategies', []) or [])}",
            f"promising_but_failed_audit_count={len(report.get('promising_but_failed_audit', []) or [])}",
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def run_selected_strategy_diagnostics(
        self,
        *,
        base_strategy_id: str | None = None,
        profile_id: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        explicit_target = self._explicit_diagnostic_target(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        before = (
            {
                "selected_next_strategy": dict(explicit_target),
                "selected_next_experiment_type": "",
                "ranked_strategies": [],
            }
            if explicit_target
            else self.build_report()
        )
        selected = dict(explicit_target) if explicit_target else self._diagnostic_target(
            before=before,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        if not selected:
            return {
                "title": "Selected Strategy Diagnostics",
                "status": "no_selected_strategy",
                "selected_next_strategy": {},
                "before": before,
                "after": before,
                "safety_statement": SAFETY_STATEMENT,
            }
        base_strategy_id = str(selected.get("base_strategy_id", "") or "")
        profile_id = str(selected.get("profile_id", "") or "")
        timeframe = str(selected.get("timeframe", "") or "")
        before_evidence = self._evidence_snapshot(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        try:
            research_run = self.variant_service.run_research(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                created_by="strategy_portfolio_research_planner",
                bounded_diagnosis=bool(explicit_target),
            )
            status = "executed_research_only"
        except ValueError as exc:
            research_run = {
                "error": str(exc),
                "supported": False,
            }
            status = "unsupported_strategy_profile"
        except Exception as exc:
            error_text = str(exc)
            if "read-only" in error_text.lower() or "readonly" in error_text.lower():
                research_run = {
                    "error": error_text,
                    "supported": True,
                    "persistence_blocked": True,
                }
                status = "read_only_existing_evidence_only"
            else:
                raise
        self._clear_runtime_caches()
        after_report = (
            self._targeted_diagnostic_follow_up(
                selected=selected,
                after_evidence=self._evidence_snapshot(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                ),
            )
            if explicit_target
            else self.build_report()
        )
        after_evidence = (
            dict(after_report.get("after_evidence", {}) or {})
            if explicit_target
            else self._evidence_snapshot(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
            )
        )
        return {
            "title": "Selected Strategy Diagnostics",
            "status": status,
            "selected_next_strategy": selected,
            "selected_next_experiment_type_before": before.get("selected_next_experiment_type"),
            "research_run": research_run,
            "research_persistence_mode": "write_enabled_research_only",
            "before": before_evidence,
            "after": after_evidence,
            "planner_before": before,
            "planner_after": after_report,
            "diagnosis_summary": self._diagnosis_summary(
                selected=selected,
                after=after_evidence,
                planner_after=after_report,
                status=status,
                research_run=research_run,
            ),
            "safety_statement": SAFETY_STATEMENT,
        }

    def _explicit_diagnostic_target(
        self,
        *,
        base_strategy_id: str | None,
        profile_id: str | None,
        timeframe: str | None,
    ) -> dict[str, Any]:
        target = {
            "base_strategy_id": str(base_strategy_id or ""),
            "profile_id": str(profile_id or ""),
            "timeframe": str(timeframe or ""),
        }
        return target if all(target.values()) else {}

    def _diagnostic_target(
        self,
        *,
        before: dict[str, Any],
        base_strategy_id: str | None,
        profile_id: str | None,
        timeframe: str | None,
    ) -> dict[str, Any]:
        if not any((base_strategy_id, profile_id, timeframe)):
            return dict(before.get("selected_next_strategy") or {})
        target = {
            "base_strategy_id": str(base_strategy_id or ""),
            "profile_id": str(profile_id or ""),
            "timeframe": str(timeframe or ""),
        }
        ranked = list(before.get("ranked_strategies", []) or [])
        for item in ranked:
            if self._is_same_candidate(item, target):
                return {
                    "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                    "profile_id": str(item.get("profile_id", "") or ""),
                    "timeframe": str(item.get("timeframe", "") or ""),
                }
        return target if all(target.values()) else {}

    def _diagnosis_summary(
        self,
        *,
        selected: dict[str, Any],
        after: dict[str, Any],
        planner_after: dict[str, Any],
        status: str,
        research_run: dict[str, Any],
    ) -> dict[str, Any]:
        next_command = str(planner_after.get("next_actionable_research_command", "") or "")
        if not next_command:
            next_command = str(after.get("strategy_planner_command", "") or "")
        next_action = str(planner_after.get("next_portfolio_action", "") or "")
        verdict = self._diagnosis_verdict_from_after(
            after=after,
            status=status,
        )
        runtime_blocked = self._after_is_runtime_blocked(after)
        paper_blocker = self._diagnosis_paper_candidate_blocker(
            selected=selected,
            after=after,
            planner_after=planner_after,
            status=status,
        )
        return {
            "strategy": str(selected.get("base_strategy_id", "") or ""),
            "profile_id": str(selected.get("profile_id", "") or ""),
            "timeframe": str(selected.get("timeframe", "") or ""),
            "sample_size": int(after.get("sample_size", 0) or 0),
            "net_return_after_costs": float(after.get("net_return_after_costs", 0.0) or 0.0),
            "win_rate": float(after.get("win_rate", 0.0) or 0.0),
            "drawdown": after.get("drawdown"),
            "diagnosis_verdict": verdict,
            "planner_recommendation": str(after.get("strategy_planner_recommendation", "") or next_action or "review_portfolio_research"),
            "next_required_action": (
                "optimise_or_precompute_replay_dataset"
                if runtime_blocked
                else next_action or (
                "unsupported_research_profile"
                if status == "unsupported_strategy_profile"
                else "collect_more_research_evidence"
                )
            ),
            "next_recommended_command": next_command or ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            "paper_candidate_path": paper_blocker,
            "can_become_paper_candidate": "yes" if paper_blocker == "eligible_for_read_only_paper_candidate_audit" else "no",
            "diagnosis_status": "runtime_blocked" if runtime_blocked else "completed",
            "runtime_blocker": (
                str(((after.get("data_adequacy", {}) or {}).get("zero_decision_reason", "")) or "")
                if runtime_blocked
                else ""
            ),
            "data_or_runtime_action": (
                "optimise_or_precompute_crypto_replay_dataset"
                if runtime_blocked
                else ""
            ),
            "support_status": (
                "supported"
                if status == "executed_research_only"
                else (
                    "read_only_existing_evidence_only"
                    if status == "read_only_existing_evidence_only"
                    else str(research_run.get("error", "") or status)
                )
            ),
        }

    def _diagnosis_verdict_from_after(
        self,
        *,
        after: dict[str, Any],
        status: str,
    ) -> str:
        verdict = str(after.get("loss_diagnosis_verdict", "") or "")
        if verdict:
            return verdict
        if status == "unsupported_strategy_profile":
            return "unsupported_strategy_profile"
        if self._after_is_runtime_blocked(after):
            return "runtime_blocked"
        sample_size = int(after.get("sample_size", 0) or 0)
        planner_recommendation = str(after.get("strategy_planner_recommendation", "") or "")
        net_return = float(after.get("net_return_after_costs", 0.0) or 0.0)
        if planner_recommendation == "retire_or_deprioritise_strategy" and sample_size >= 30 and net_return <= 0.05:
            return "deprioritise"
        if sample_size > 0 and sample_size < 30 and net_return <= -0.5:
            return "insufficient_but_negative"
        if sample_size > 0:
            if status == "read_only_existing_evidence_only":
                return "existing_evidence_only"
            return "insufficient_data"
        return "insufficient_data"

    def _targeted_diagnostic_follow_up(
        self,
        *,
        selected: dict[str, Any],
        after_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = str(selected.get("base_strategy_id", "") or "")
        sample_size = int(after_evidence.get("sample_size", 0) or 0)
        net_return = float(after_evidence.get("net_return_after_costs", 0.0) or 0.0)
        planner_recommendation = str(after_evidence.get("strategy_planner_recommendation", "") or "")
        paper_path = self._diagnosis_paper_candidate_blocker(
            selected=selected,
            after=after_evidence,
            planner_after={},
            status="executed_research_only",
        )
        if paper_path == "eligible_for_read_only_paper_candidate_audit":
            next_portfolio_action = "audit_paper_candidate"
        elif self._after_is_runtime_blocked(after_evidence):
            next_portfolio_action = "optimise_or_precompute_replay_dataset"
        elif sample_size <= 0:
            next_portfolio_action = "collect_more_research_evidence"
        elif sample_size < 30 and net_return <= -0.5:
            next_portfolio_action = "return_to_portfolio_planner"
        elif planner_recommendation == "retire_or_deprioritise_strategy" and sample_size >= 30 and net_return <= 0.05:
            next_portfolio_action = "return_to_portfolio_planner"
        elif net_return <= 0.0:
            next_portfolio_action = f"continue_research_for_{strategy}"
        else:
            next_portfolio_action = f"continue_research_for_{strategy}"
        next_command = str(after_evidence.get("strategy_planner_command", "") or "")
        if next_portfolio_action == "return_to_portfolio_planner":
            next_command = ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        return {
            "selected_next_strategy": dict(selected),
            "selected_next_experiment_type": planner_recommendation,
            "next_actionable_research_command": next_command,
            "next_portfolio_action": next_portfolio_action,
            "after_evidence": dict(after_evidence),
        }

    def _diagnosis_paper_candidate_blocker(
        self,
        *,
        selected: dict[str, Any],
        after: dict[str, Any],
        planner_after: dict[str, Any],
        status: str,
    ) -> str:
        if status == "unsupported_strategy_profile":
            return "unsupported_strategy_profile"
        if str(selected.get("base_strategy_id", "") or "").startswith("liquidity_probe."):
            return "research_only_profile_not_approved_for_paper"
        next_action = str(planner_after.get("next_portfolio_action", "") or "")
        if next_action == "audit_paper_candidate":
            return "eligible_for_read_only_paper_candidate_audit"
        if int(after.get("sample_size", 0) or 0) <= 0:
            if self._after_is_runtime_blocked(after):
                return "runtime_blocked"
            return "insufficient_data"
        if float(after.get("net_return_after_costs", 0.0) or 0.0) <= 0.0:
            return "negative_replay_edge"
        return "needs_more_research_before_paper_audit"

    def _after_is_runtime_blocked(self, after: dict[str, Any]) -> bool:
        data_adequacy = dict(after.get("data_adequacy", {}) or {})
        return str(data_adequacy.get("zero_decision_reason", "") or "") == "historical_bar_read_timeout"

    def _evidence_snapshot(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> dict[str, Any]:
        identity = _StrategyIdentity(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        variant_report = self._safe_variant_report(identity)
        baseline = dict(variant_report.get("baseline", {}) or {})
        baseline_metrics = dict(baseline.get("metrics", {}) or {})
        baseline_data_adequacy = dict(baseline.get("data_adequacy", {}) or {})
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        evaluations = self.usage_ledger.list_strategy_variant_evaluations(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            limit=500,
        )
        loss_report = self._safe_loss_report(identity)
        strategy_planner = self._safe_strategy_planner(identity)
        return {
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "sample_size": int(baseline_metrics.get("sample_size", 0) or 0),
            "net_return_after_costs": float(baseline_metrics.get("net_return_after_costs", 0.0) or 0.0),
            "win_rate": float(baseline_metrics.get("win_rate", 0.0) or 0.0),
            "drawdown": baseline_metrics.get("drawdown"),
            "data_adequacy": baseline_data_adequacy,
            "zero_decision_reason": str(baseline_data_adequacy.get("zero_decision_reason", "") or ""),
            "baseline_evaluation_exists": bool(baseline.get("variant_id")) and bool(baseline_metrics),
            "variant_definitions_exist": bool(definitions),
            "variant_evaluations_exist": bool(evaluations),
            "diagnostics_exist": bool(loss_report) or bool(strategy_planner),
            "baseline_variant_id": str(baseline.get("variant_id", "") or ""),
            "variants_generated": int(variant_report.get("variants_generated", 0) or 0),
            "variants_evaluated": int(variant_report.get("variants_evaluated", 0) or 0),
            "loss_diagnosis_verdict": str(loss_report.get("verdict", "") or ""),
            "profitability_verdict": str(
                ((loss_report.get("profitability_requirement_diagnosis", {}) or {}).get("profitability_verdict", "")) or ""
            ),
            "exit_verdict": str(
                ((loss_report.get("time_exit_and_target_achievement_diagnosis", {}) or {}).get("exit_verdict", "")) or ""
            ),
            "strategy_planner_recommendation": str(strategy_planner.get("selected_experiment_type", "") or ""),
            "strategy_planner_command": str(strategy_planner.get("proposed_next_command", "") or ""),
        }

    def _identities(self) -> list[_StrategyIdentity]:
        identities: dict[tuple[str, str, str], _StrategyIdentity] = {}
        for row in self._definitions():
            identity = _StrategyIdentity(
                base_strategy_id=str(row.get("base_strategy_id", "") or ""),
                profile_id=str(row.get("profile_id", "") or ""),
                timeframe=str(row.get("timeframe", "") or ""),
            )
            if all((identity.base_strategy_id, identity.profile_id, identity.timeframe)):
                identities[(identity.base_strategy_id, identity.profile_id, identity.timeframe)] = identity
        for row in self._latest_decisions():
            strategy_id = str(row.get("strategy_id", "") or "")
            profile_id = str(row.get("profile_id", "") or "")
            timeframe = str(row.get("timeframe", "") or "")
            if strategy_id and profile_id and timeframe:
                base_strategy_id = "crypto_pullback" if strategy_id.startswith("crypto_pullback.") else strategy_id
                identities[(base_strategy_id, profile_id, timeframe)] = _StrategyIdentity(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                )
        return sorted(identities.values(), key=lambda item: (item.base_strategy_id, item.profile_id, item.timeframe))

    def _build_strategy_row(self, identity: _StrategyIdentity) -> dict[str, Any]:
        variant_report = self._safe_variant_report(identity)
        baseline_metrics = dict((variant_report.get("baseline", {}) or {}).get("metrics", {}) or {})
        variants = list(variant_report.get("variants", []) or [])
        best_variant = self._best_variant(variants)
        diagnosis_report = self._safe_loss_report(identity)
        planner_report = self._safe_strategy_planner(identity)
        promotion = self._promotion(identity)
        latest_cycle = self._matching_research_cycle_decision(identity)
        latest_sample_size = self._coalesce_int(
            baseline_metrics.get("sample_size"),
            latest_cycle.get("outcomes_recorded"),
            latest_cycle.get("raw_json", {}).get("sample_size") if isinstance(latest_cycle.get("raw_json"), dict) else None,
        )
        latest_net = self._coalesce_float(
            baseline_metrics.get("net_return_after_costs"),
            latest_cycle.get("net_return_summary_json", {}).get("avg_pct") if isinstance(latest_cycle.get("net_return_summary_json"), dict) else None,
        )
        selected_symbol = self._selected_symbol_from_command(str(planner_report.get("proposed_next_command", "") or ""))
        wide_symbol_stability = self._latest_wide_symbol_stability(
            base_strategy_id=identity.base_strategy_id,
            profile_id=identity.profile_id,
            timeframe=identity.timeframe,
            variant_id=self._selected_variant_id(variants),
            symbol=selected_symbol,
        )
        latest_win_rate = self._coalesce_float(
            baseline_metrics.get("win_rate"),
            latest_cycle.get("win_rate_summary_json", {}).get("avg") if isinstance(latest_cycle.get("win_rate_summary_json"), dict) else None,
        )
        strategy_evaluations = self._strategy_evaluations(identity)
        latest_autopilot_no_progress = self._latest_autopilot_no_progress_summary(identity)
        latest_strategy_evidence_timestamp = self._latest_strategy_evidence_timestamp(
            latest_cycle=latest_cycle,
            strategy_evaluations=strategy_evaluations,
        )
        latest_variant_evaluation_timestamp = self._latest_variant_evaluation_timestamp(strategy_evaluations)
        latest_diagnosis_timestamp = self._latest_diagnosis_timestamp(strategy_evaluations)
        latest_symbol_stability_timestamp = self._latest_symbol_stability_timestamp(strategy_evaluations)
        latest_replay_evidence_timestamp = self._latest_replay_evidence_timestamp(strategy_evaluations)
        latest_replay_preparation_timestamp = self._latest_replay_preparation_timestamp(strategy_evaluations)
        latest_signal_generation_diagnosis = self._latest_signal_generation_diagnosis_summary(identity)
        latest_signal_generation_diagnosis_timestamp = self._timestamp_to_iso(
            self._to_datetime(latest_signal_generation_diagnosis.get("evaluated_at"))
        )
        latest_data_backfill_timestamp = self._latest_data_backfill_timestamp(
            latest_cycle=latest_cycle,
            strategy_evaluations=strategy_evaluations,
        )
        data_adequacy = dict(
            ((variant_report.get("baseline", {}) or {}).get("data_adequacy", {}) or {})
        )
        latest_data_readiness = self._latest_historical_data_readiness_summary(
            strategy_evaluations
        )
        if self._data_gap_resolved_by_newer_readiness(
            data_adequacy=data_adequacy,
            latest_data_readiness=latest_data_readiness,
            latest_replay_preparation_timestamp=latest_replay_preparation_timestamp,
        ):
            data_adequacy["zero_decision_reason"] = ""
            data_adequacy["total_bars"] = int(
                latest_data_readiness.get("bars_generated", 0)
                or latest_data_readiness.get("bars_available", 0)
                or 0
            )
            data_adequacy["days_covered"] = float(
                latest_data_readiness.get("days_covered", 0) or 0
            )
            data_adequacy["symbols_covered"] = list(
                latest_data_readiness.get("symbols_tested", [])
                or latest_data_readiness.get("symbols_covered_list", [])
                or []
            )
        autopilot_classification_timestamp = self._timestamp_to_iso(
            self._to_datetime(
                latest_autopilot_no_progress.get("autopilot_classification_timestamp")
                or latest_autopilot_no_progress.get("recorded_at")
            )
        )
        latest_relevant_evidence_timestamp = self._latest_relevant_evidence_timestamp(
            latest_strategy_evidence_timestamp=latest_strategy_evidence_timestamp,
            latest_variant_evaluation_timestamp=latest_variant_evaluation_timestamp,
            latest_diagnosis_timestamp=latest_diagnosis_timestamp,
            latest_symbol_stability_timestamp=latest_symbol_stability_timestamp,
            latest_replay_evidence_timestamp=latest_replay_evidence_timestamp,
            latest_replay_preparation_timestamp=latest_replay_preparation_timestamp,
            latest_signal_generation_diagnosis_timestamp=latest_signal_generation_diagnosis_timestamp,
            latest_data_backfill_timestamp=latest_data_backfill_timestamp,
        )
        generated_candidate_lifecycle_status = self._generated_candidate_lifecycle_status(
            identity=identity,
            variant_report=variant_report,
            latest_sample_size=latest_sample_size,
            latest_net=latest_net,
            latest_planner_recommendation=str(planner_report.get("selected_experiment_type", "") or ""),
            latest_diagnosis_verdict=str(diagnosis_report.get("verdict", "") or ""),
            latest_autopilot_no_progress=latest_autopilot_no_progress,
            latest_variant_evaluation_timestamp=latest_variant_evaluation_timestamp,
        )
        generated_zero_sample = self._generated_zero_sample_outcome(
            identity=identity,
            variant_report=variant_report,
            generated_candidate_lifecycle_status=generated_candidate_lifecycle_status,
        )
        row = {
            "base_strategy_id": identity.base_strategy_id,
            "profile_id": identity.profile_id,
            "timeframe": identity.timeframe,
            "generated_candidate_metadata": self._generated_candidate_metadata(identity),
            "generated_candidate_runtime_summary": {
                "baseline_sample_size": int(variant_report.get("baseline_sample_size", 0) or 0),
                "best_variant_sample_size": int(variant_report.get("best_variant_sample_size", 0) or 0),
                "runtime_status": str(variant_report.get("runtime_status", "") or ""),
                "runtime_blocker": str(variant_report.get("runtime_blocker", "") or ""),
            },
            "latest_sample_size": latest_sample_size,
            "latest_net_return_after_costs": latest_net,
            "win_rate": latest_win_rate,
            "drawdown": baseline_metrics.get("drawdown"),
            "best_variant_net_return_after_costs": None if not best_variant else float(best_variant.get("net_return_after_costs", 0.0) or 0.0),
            "any_variant_beat_baseline": any(bool(item.get("beats_baseline")) for item in variants),
            "any_variant_beat_thresholds": any(bool(item.get("beats_thresholds")) for item in variants),
            "latest_diagnosis_verdict": str(diagnosis_report.get("verdict", "") or ""),
            "latest_planner_recommendation": str(planner_report.get("selected_experiment_type", "") or ""),
            "latest_planner_command": str(planner_report.get("proposed_next_command", "") or ""),
            "planner_reason": str(planner_report.get("reason", "") or ""),
            "data_adequacy": data_adequacy,
            "zero_decision_reason": str(data_adequacy.get("zero_decision_reason", "") or ""),
            "data_gap_action": self._data_gap_action(
                identity=identity,
                data_adequacy=data_adequacy,
            ),
            "selected_variant_id": self._selected_variant_id(variants),
            "selected_symbol": selected_symbol,
            "latest_replay_preparation": self._latest_replay_preparation_summary(strategy_evaluations),
            "latest_signal_generation_diagnosis": latest_signal_generation_diagnosis,
            "paper_candidate_path": self._paper_candidate_path_for_row(
                latest_sample_size=latest_sample_size,
                latest_net=latest_net,
                win_rate=latest_win_rate,
                drawdown=baseline_metrics.get("drawdown"),
            ),
            "wide_symbol_stability": wide_symbol_stability,
            "audit_report": self._safe_audit_report(identity) if any(bool(item.get("beats_thresholds")) for item in variants) else {},
            "branch_stopped": self._branch_stopped(wide_symbol_stability),
            "stopped_branch_name": self._stopped_branch_name(identity=identity, symbol=selected_symbol),
            "latest_autopilot_no_progress": latest_autopilot_no_progress,
            "autopilot_classification_timestamp": autopilot_classification_timestamp,
            "latest_strategy_evidence_timestamp": latest_strategy_evidence_timestamp,
            "latest_variant_evaluation_timestamp": latest_variant_evaluation_timestamp,
            "latest_diagnosis_timestamp": latest_diagnosis_timestamp,
            "latest_symbol_stability_timestamp": latest_symbol_stability_timestamp,
            "latest_replay_evidence_timestamp": latest_replay_evidence_timestamp,
            "latest_replay_preparation_timestamp": latest_replay_preparation_timestamp,
            "latest_signal_generation_diagnosis_timestamp": latest_signal_generation_diagnosis_timestamp,
            "latest_data_backfill_timestamp": latest_data_backfill_timestamp,
            "latest_relevant_evidence_timestamp": latest_relevant_evidence_timestamp,
            "generated_candidate_pending": generated_candidate_lifecycle_status in {
                "generated_not_evaluated",
                "variant_research_pending",
            },
            "generated_candidate_lifecycle_status": generated_candidate_lifecycle_status,
            "generated_candidate_zero_sample_outcome": generated_zero_sample,
            "recent_zero_evidence_attempted": self._recent_zero_evidence_attempted(
                latest_sample_size=latest_sample_size,
                planner_report=planner_report,
                latest_cycle=latest_cycle,
                variant_report=variant_report,
                generated_candidate_pending=generated_candidate_lifecycle_status in {
                    "generated_not_evaluated",
                    "variant_research_pending",
                },
            ),
            "research_status": self._research_status(
                latest_sample_size=latest_sample_size,
                latest_net=latest_net,
                diagnosis_verdict=str(diagnosis_report.get("verdict", "") or ""),
                planner_experiment=str(planner_report.get("selected_experiment_type", "") or ""),
                any_variant_beat_baseline=any(bool(item.get("beats_baseline")) for item in variants),
                any_variant_beat_thresholds=any(bool(item.get("beats_thresholds")) for item in variants),
                evidence_generated=bool(variant_report.get("variants_generated")) or bool(variant_report.get("variants_evaluated")),
                zero_decision_reason=str(data_adequacy.get("zero_decision_reason", "") or ""),
                promotion=promotion,
                wide_symbol_stability=wide_symbol_stability,
                audit_report=self._safe_audit_report(identity) if any(bool(item.get("beats_thresholds")) for item in variants) else {},
            ),
            "priority_rank": self._priority_rank(
                latest_sample_size=latest_sample_size,
                latest_net=latest_net,
                diagnosis_verdict=str(diagnosis_report.get("verdict", "") or ""),
                planner_experiment=str(planner_report.get("selected_experiment_type", "") or ""),
                any_variant_beat_baseline=any(bool(item.get("beats_baseline")) for item in variants),
                any_variant_beat_thresholds=any(bool(item.get("beats_thresholds")) for item in variants),
                evidence_generated=bool(variant_report.get("variants_generated")) or bool(variant_report.get("variants_evaluated")),
                zero_decision_reason=str(
                    (((variant_report.get("baseline", {}) or {}).get("data_adequacy", {}) or {}).get("zero_decision_reason", "")) or ""
                ),
                promotion=promotion,
                wide_symbol_stability=wide_symbol_stability,
                audit_report=self._safe_audit_report(identity) if any(bool(item.get("beats_thresholds")) for item in variants) else {},
            ),
            "priority_score": self._priority_score(
                latest_sample_size=latest_sample_size,
                latest_net=latest_net,
                best_variant_net=float(best_variant.get("net_return_after_costs", 0.0) or 0.0) if best_variant else None,
                any_variant_beat_baseline=any(bool(item.get("beats_baseline")) for item in variants),
                any_variant_beat_thresholds=any(bool(item.get("beats_thresholds")) for item in variants),
                wide_symbol_stability=wide_symbol_stability,
            ),
        }
        post_precompute_status = self._post_precompute_research_status(row)
        if post_precompute_status:
            row["research_status"] = post_precompute_status
        return row

    def _safe_variant_report(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if not hasattr(self, "_cached_variant_reports"):
            self._cached_variant_reports = {}
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_variant_reports.get(cache_key)
        if cached is not None:
            return dict(cached)
        try:
            report = self.variant_reporter.build_report(
                base_strategy_id=identity.base_strategy_id,
                profile_id=identity.profile_id,
                timeframe=identity.timeframe,
            )
            self._cached_variant_reports[cache_key] = dict(report)
            return report
        except Exception:
            return {}

    def _safe_loss_report(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if getattr(self, "operator_mode", False) and isinstance(self.loss_reporter, StrategyLossDiagnosisReport):
            return {}
        if not hasattr(self, "_cached_loss_reports"):
            self._cached_loss_reports = {}
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_loss_reports.get(cache_key)
        if cached is not None:
            return dict(cached)
        try:
            report = self.loss_reporter.build_report(
                base_strategy_id=identity.base_strategy_id,
                profile_id=identity.profile_id,
                timeframe=identity.timeframe,
            )
            self._cached_loss_reports[cache_key] = dict(report)
            return report
        except Exception:
            return {}

    def _safe_strategy_planner(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if getattr(self, "operator_mode", False) and isinstance(self.strategy_planner, StrategyResearchPlannerReport):
            return self._lightweight_strategy_plan(identity)
        if not hasattr(self, "_cached_strategy_plans"):
            self._cached_strategy_plans = {}
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_strategy_plans.get(cache_key)
        if cached is not None:
            return dict(cached)
        try:
            report = self.strategy_planner.build_report(
                base_strategy_id=identity.base_strategy_id,
                profile_id=identity.profile_id,
                timeframe=identity.timeframe,
            )
            self._cached_strategy_plans[cache_key] = dict(report)
            return report
        except Exception:
            return {}

    def _safe_audit_report(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if not hasattr(self, "_cached_audit_reports"):
            self._cached_audit_reports = {}
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_audit_reports.get(cache_key)
        if cached is not None:
            return dict(cached)
        try:
            report = self.audit_reporter.build_report(
                base_strategy_id=identity.base_strategy_id,
                profile_id=identity.profile_id,
                timeframe=identity.timeframe,
            )
            self._cached_audit_reports[cache_key] = dict(report)
            return report
        except Exception:
            return {}

    def _matching_research_cycle_decision(self, identity: _StrategyIdentity) -> dict[str, Any]:
        for row in self._latest_decisions():
            strategy_id = str(row.get("strategy_id", "") or "")
            mapped_strategy_id = "crypto_pullback" if strategy_id.startswith("crypto_pullback.") else strategy_id
            if (
                mapped_strategy_id == identity.base_strategy_id
                and str(row.get("profile_id", "") or "") == identity.profile_id
                and str(row.get("timeframe", "") or "") == identity.timeframe
            ):
                return row
        return {}

    def _best_variant(self, variants: list[dict[str, Any]]) -> dict[str, Any] | None:
        non_baseline = [item for item in variants if str(item.get("variant_id", "") or "") != "baseline"]
        if not non_baseline:
            return None
        return max(
            non_baseline,
            key=lambda item: (
                bool(item.get("beats_baseline")),
                float(item.get("net_return_after_costs", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
            ),
        )

    def _selected_variant_id(self, variants: list[dict[str, Any]]) -> str:
        best_variant = self._best_variant(variants)
        return str((best_variant or {}).get("variant_id", "") or "")

    def _selected_symbol_from_command(self, command: str) -> str:
        parts = str(command or "").split()
        for index, token in enumerate(parts):
            if token == "--symbol" and index + 1 < len(parts):
                return str(parts[index + 1] or "").strip().upper()
        return ""

    def _research_status(
        self,
        *,
        latest_sample_size: int,
        latest_net: float,
        diagnosis_verdict: str,
        planner_experiment: str,
        any_variant_beat_baseline: bool,
        any_variant_beat_thresholds: bool,
        evidence_generated: bool,
        zero_decision_reason: str,
        promotion: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
        audit_report: dict[str, Any],
    ) -> str:
        audit_verdict = str((audit_report or {}).get("audit_verdict", "") or "")
        audit_status = str((audit_report or {}).get("audit_status", "") or "")
        if zero_decision_reason == "no_bars_for_timeframe":
            return "data_gap"
        if zero_decision_reason == "historical_bar_read_timeout":
            return "runtime_blocked"
        if self._branch_stopped(wide_symbol_stability):
            return "deprioritise"
        if bool(promotion.get("paper_approved")):
            return "paper_candidate_requires_manual_approval"
        if audit_status == "approved_for_paper":
            return "paper_candidate_requires_manual_approval"
        if audit_status == "blocked_pending_more_data":
            return "promising_but_failed_audit"
        if audit_status == "parked_until_new_data":
            return "promising_but_failed_audit"
        if audit_status in {"deprioritised", "failed_audit"}:
            return "deprioritise"
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "promising_but_failed_audit"
        if audit_verdict == "paper_candidate_reject_due_to_drawdown":
            return "deprioritise"
        if audit_verdict == "paper_candidate_audit_pass":
            return "paper_candidate_requires_manual_approval"
        if audit_verdict in {"paper_candidate_promising_but_fragile", "paper_candidate_needs_more_replay"}:
            return "audit_required"
        if any_variant_beat_thresholds:
            return "audit_required"
        if latest_sample_size <= 0:
            if evidence_generated:
                # Zero-sample outcomes are evidence gaps unless a separate
                # adequate-sample failure path has already been established.
                if zero_decision_reason == "no_bars_for_timeframe":
                    return "data_gap"
                if zero_decision_reason == "historical_bar_read_timeout":
                    return "runtime_blocked"
                return "insufficient_data"
            return "untested_strategy"
        if latest_sample_size < 30:
            if self._materially_negative_evidence(
                latest_sample_size=latest_sample_size,
                latest_net=latest_net,
                win_rate=0.0 if latest_net <= -0.5 else 1.0,
                drawdown=3.0 if latest_net <= -0.5 else 0.0,
                paper_candidate_path="negative_replay_edge" if latest_net <= 0.0 else "",
            ) and planner_experiment == "retire_or_deprioritise_strategy":
                return "deprioritise"
            return "insufficient_data"
        if planner_experiment == "retire_or_deprioritise_strategy":
            return "deprioritise"
        if any_variant_beat_baseline and latest_net > -0.25:
            return "active_research"
        if planner_experiment in {"validate_symbol_subset_stability", "test_holding_window_variants"}:
            return "active_research"
        if latest_sample_size >= 30 and latest_net <= -0.5 and not any_variant_beat_baseline:
            if diagnosis_verdict in {"snapback_no_edge_detected", "snapback_entry_quality_problem", "no_edge_detected", "entry_quality_problem"}:
                return "retire_candidate"
            return "deprioritise"
        if latest_net <= 0.05:
            return "deprioritise" if diagnosis_verdict else "insufficient_data"
        return "active_research"

    def _generated_zero_sample_outcome(
        self,
        *,
        identity: _StrategyIdentity,
        variant_report: dict[str, Any],
        generated_candidate_lifecycle_status: str,
    ) -> dict[str, Any]:
        if generated_candidate_lifecycle_status not in {
            "variant_research_completed",
            "no_viable_signal_after_variant_research",
            "insufficient_history_after_variant_research",
        }:
            return {}
        if not self._generated_candidate_metadata(identity):
            return {}
        baseline_sample_size = int(variant_report.get("baseline_sample_size", 0) or 0)
        best_variant_sample_size = int(variant_report.get("best_variant_sample_size", 0) or 0)
        runtime_status = str(variant_report.get("runtime_status", "") or "")
        runtime_blocker = str(variant_report.get("runtime_blocker", "") or "")
        if baseline_sample_size > 0 or best_variant_sample_size > 0 or runtime_status != "completed":
            return {}
        zero_sample_status = self._generated_zero_sample_research_status(variant_report)
        if not zero_sample_status:
            return {}
        research_status = str(generated_candidate_lifecycle_status or "")
        if research_status == "variant_research_completed":
            research_status = zero_sample_status
        next_required_action = str(variant_report.get("next_required_action", "") or "")
        if not next_required_action:
            next_required_action = (
            "generate_next_research_candidate"
            if research_status == "insufficient_history_after_variant_research"
            else "expand_signal_generation_research_only"
            )
        return {
            "research_status": research_status,
            "reason": "variant_research_completed_but_zero_samples",
            "next_required_action": next_required_action,
            "baseline_sample_size": baseline_sample_size,
            "best_variant_sample_size": best_variant_sample_size,
            "coverage_symbols_seen": int(variant_report.get("coverage_symbols_seen", 0) or 0),
            "eligible_symbols_after_filters": int(variant_report.get("eligible_symbols_after_filters", 0) or 0),
            "symbols_processed_for_strategy": int(variant_report.get("symbols_processed_for_strategy", 0) or 0),
            "zero_sample_reason": str(variant_report.get("zero_sample_reason", "") or ""),
            "history_coverage_reason": str(variant_report.get("history_coverage_reason", "") or ""),
            "bars_read": int(variant_report.get("bars_read", 0) or 0),
            "runtime_blocker": runtime_blocker,
            "no_progress_classification": str(variant_report.get("no_progress_classification", "") or ""),
            "no_progress_reason": str(variant_report.get("no_progress_reason", "") or ""),
            "missing_required_fields": list(variant_report.get("missing_required_fields", []) or []),
        }

    def _generated_zero_sample_research_status(self, variant_report: dict[str, Any]) -> str:
        baseline_sample_size = int(variant_report.get("baseline_sample_size", 0) or 0)
        best_variant_sample_size = int(variant_report.get("best_variant_sample_size", 0) or 0)
        runtime_status = str(variant_report.get("runtime_status", "") or "")
        if baseline_sample_size > 0 or best_variant_sample_size > 0 or runtime_status != "completed":
            return ""
        runtime_blocker = str(variant_report.get("runtime_blocker", "") or "")
        zero_sample_reason = str(variant_report.get("zero_sample_reason", "") or "").lower()
        history_coverage_reason = str(variant_report.get("history_coverage_reason", "") or "").lower()
        insufficient_history_markers = (
            "insufficient_history",
            "history_window",
            "history remained insufficient",
            "history remained too thin",
            "coverage_scan_loaded_bars",
            "bars_but_requested_history_window_remained_insufficient",
        )
        if (
            runtime_blocker in {"insufficient_crypto_history", "insufficient_history", "insufficient_market_history"}
            or any(marker in zero_sample_reason for marker in insufficient_history_markers)
            or any(marker in history_coverage_reason for marker in insufficient_history_markers)
        ):
            return "insufficient_history_after_variant_research"
        return "no_viable_signal_after_variant_research"

    def _post_precompute_research_status(self, item: dict[str, Any]) -> str:
        generated_zero_sample = dict(item.get("generated_candidate_zero_sample_outcome") or {})
        if generated_zero_sample:
            return str(generated_zero_sample.get("research_status", "") or "")
        latest_no_progress = dict(item.get("latest_autopilot_no_progress") or {})
        if not latest_no_progress or not self._autopilot_exclusion_active(item):
            return ""
        latest_prep = dict(item.get("latest_replay_preparation") or {})
        if str(latest_prep.get("runtime_status", "") or "") != "precomputed":
            return ""
        if str(latest_prep.get("cache_status", "") or "").lower() != "fresh":
            return ""
        classification_reason = str(latest_no_progress.get("classification_reason", "") or "")
        if classification_reason == "insufficient_data_after_precompute":
            return "insufficient_data_after_precompute"
        if classification_reason.startswith("precompute_completed_but_only_"):
            return "deprioritise_until_new_data"
        if classification_reason == "no_viable_signal_after_precompute":
            return "no_viable_signal_after_precompute"
        return ""

    def _priority_rank(
        self,
        *,
        latest_sample_size: int,
        latest_net: float,
        diagnosis_verdict: str,
        planner_experiment: str,
        any_variant_beat_baseline: bool,
        any_variant_beat_thresholds: bool,
        evidence_generated: bool,
        zero_decision_reason: str,
        promotion: dict[str, Any],
        wide_symbol_stability: dict[str, Any],
        audit_report: dict[str, Any],
    ) -> int:
        status = self._research_status(
            latest_sample_size=latest_sample_size,
            latest_net=latest_net,
            diagnosis_verdict=diagnosis_verdict,
            planner_experiment=planner_experiment,
            any_variant_beat_baseline=any_variant_beat_baseline,
            any_variant_beat_thresholds=any_variant_beat_thresholds,
            evidence_generated=evidence_generated,
            zero_decision_reason=zero_decision_reason,
            promotion=promotion,
            wide_symbol_stability=wide_symbol_stability,
            audit_report=audit_report,
        )
        return {
            "promising_but_failed_audit": 1,
            "audit_required": 2,
            "active_research": 3,
            "insufficient_data_after_precompute": 4,
            "insufficient_data": 4,
            "runtime_blocked": 5,
            "untested_strategy": 6,
            "data_gap": 7,
            "insufficient_history_after_variant_research": 8,
            "no_viable_signal_after_variant_research": 8,
            "deprioritise_until_new_data": 8,
            "no_viable_signal_after_precompute": 8,
            "deprioritise": 8,
            "retire_candidate": 9,
            "paper_candidate_requires_manual_approval": 10,
        }.get(status, 10)

    def _priority_score(
        self,
        *,
        latest_sample_size: int,
        latest_net: float,
        best_variant_net: float | None,
        any_variant_beat_baseline: bool,
        any_variant_beat_thresholds: bool,
        wide_symbol_stability: dict[str, Any],
    ) -> float:
        score = float(latest_net)
        if self._branch_stopped(wide_symbol_stability):
            score -= 1.0
        score += min(latest_sample_size, 100) / 1000.0
        if any_variant_beat_baseline:
            score += 0.5
        if any_variant_beat_thresholds:
            score += 0.25
        if best_variant_net is not None:
            score += best_variant_net / 10.0
        return score

    def _portfolio_reason(self, selected: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
        research_expansion = self._research_expansion_state(
            ranked=ranked,
            next_data_runtime_action=self._next_data_runtime_action(ranked, selected),
        )
        failed_audit_candidate = next(
            (item for item in ranked if item.get("research_status") == "promising_but_failed_audit"),
            {},
        )
        if selected.get("research_status") == "untested_strategy" and failed_audit_candidate:
            return (
                "Selected because the existing promising candidate failed audit and this strategy has not yet been evaluated. "
                "Keep the failed-audit branch in research-only follow-up until more out-of-sample evidence is available."
            )
        stopped = self._latest_stopped_branch(ranked)
        if stopped:
            if selected and not selected.get("branch_stopped"):
                return (
                    f"{stopped.get('branch_name', 'snapback_WDC')} stopped after wider replay failed "
                    f"({stopped.get('stability_verdict', '-')}); shifting to the next best research candidate."
                )
            return (
                f"{stopped.get('branch_name', 'snapback_WDC')} stopped after wider replay failed "
                f"({stopped.get('stability_verdict', '-')}); no stronger remaining candidate is available."
            )
        if not selected:
            if research_expansion.get("research_universe_status") == "exhausted_current_strategy_set":
                return str(
                    research_expansion.get("reason", "")
                    or "The current strategy set is exhausted, so the next safe move is research-only expansion planning."
                )
            runtime_action = self._next_data_runtime_action(ranked, {})
            if runtime_action:
                return str(runtime_action.get("reason", "") or "No strategy is currently research-actionable until runtime/data preparation is completed.")
            return "No persisted strategy research evidence was available to rank safely."
        if selected.get("research_status") == "promising_but_failed_audit":
            status = self._symbol_follow_up_status(selected)
            if status == "symbol_subset_follow_up":
                return (
                    "Selected a symbol-subset stability follow-up for the blocked best candidate before considering paper."
                )
            if status == "data_gap_action":
                return (
                    "Selected a data-gap follow-up for the blocked best candidate before considering paper."
                )
            if status == "same_strategy_follow_up":
                return (
                    "Selected a same-strategy research follow-up for the blocked best candidate before considering paper."
                )
            return (
                "Selected a new untested strategy because the strongest known candidate failed its paper-candidate audit; "
                "keep the failed-audit branch in research-only follow-up until more out-of-sample evidence is available."
            )
        if selected.get("research_status") == "untested_strategy":
            return (
                "Selected because the existing promising candidate failed audit and this strategy has not yet been evaluated."
            )
        if selected.get("research_status") == "data_gap":
            action = dict(selected.get("data_gap_action") or {})
            return str(
                action.get("reason")
                or "This strategy is blocked by a historical data gap, so the next safe move is research-only data planning rather than treating it as a failed strategy."
            )
        if selected.get("research_status") == "runtime_blocked":
            return "This strategy is blocked by runtime or replay-dataset access, so the next safe move is data/runtime preparation rather than treating it as a failed strategy."
        if selected.get("research_status") == "no_viable_signal_after_variant_research":
            return (
                "Generated variant research completed after reading coverage/history, but no symbols produced executable "
                "samples, so diagnosis is skipped and research should rotate to a fresh candidate or signal-expansion path."
            )
        if selected.get("research_status") == "insufficient_history_after_variant_research":
            return (
                "Generated variant research completed after scanning available bars, but history remained too thin to "
                "produce usable samples, so diagnosis is skipped until a fresh candidate or new data path is chosen."
            )
        if selected.get("research_status") in {"active_research", "insufficient_data"}:
            return str(selected.get("planner_reason", "") or "This strategy has the strongest positive or improving replay evidence that still needs validation.")
        if selected.get("research_status") == "audit_required":
            return "A replay-only candidate beat the current thresholds, so the next safe step is a read-only paper candidate audit before any manual approval decision."
        if all(item.get("research_status") in {"deprioritise", "retire_candidate"} for item in ranked):
            return "All tracked strategies remain negative or exhausted, so portfolio-level effort should shift toward new family discovery instead of overfitting weak variants."
        return "The selected strategy has the best conservative research priority among currently persisted evidence."

    def _proposed_next_command(self, selected: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
        if not selected:
            runtime_action = self._next_data_runtime_action(ranked, {})
            research_expansion = self._research_expansion_state(
                ranked=ranked,
                next_data_runtime_action=runtime_action,
            )
            if (
                research_expansion.get("research_universe_status") == "exhausted_current_strategy_set"
                and str(runtime_action.get("action", "") or "") != "adjust_signal_generation_research_only"
            ):
                return str(research_expansion.get("next_recommended_command", "") or DEFAULT_RESEARCH_EXPANSION_COMMAND)
            if runtime_action:
                if str(runtime_action.get("action", "") or "") == "adjust_signal_generation_research_only":
                    target = self._find_ranked_item(
                        ranked=ranked,
                        base_strategy_id=str(runtime_action.get("base_strategy_id", "") or ""),
                        profile_id=str(runtime_action.get("profile_id", "") or ""),
                        timeframe=str(runtime_action.get("timeframe", "") or ""),
                    )
                    if target:
                        follow_up = self._signal_generation_follow_up_command(target)
                        if follow_up:
                            return follow_up
                        return self._signal_generation_diagnosis_command(target)
                mapped = self._data_gap_command(str(runtime_action.get("data_or_runtime_action", "") or ""))
                if mapped:
                    return mapped
                return self._runtime_action_command(runtime_action)
            return ".venv-mac/bin/python main.py --research-status"
        if self._next_portfolio_action(selected, ranked) == "run_generated_variant_research":
            return (
                ".venv-mac/bin/python main.py --run-strategy-variant-research "
                f"--base-strategy {selected.get('base_strategy_id', '')} "
                f"--profile-id {selected.get('profile_id', '')} "
                f"--timeframe {selected.get('timeframe', '')}"
            ).strip()
        wide = dict(selected.get("wide_symbol_stability", {}) or {})
        if wide:
            verdict = normalize_symbol_subset_verdict(str(wide.get("stability_verdict", "") or ""))
            if verdict == "symbol_promising_and_stable":
                return ".venv-mac/bin/python main.py --strategy-research-planner --base-strategy mean_reversion.snapback --profile-id snapback"
            if verdict in {"symbol_unstable", "symbol_not_promising"}:
                return ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        if self._next_portfolio_action(selected, ranked) == "collect_more_data_for_snapback_WDC":
            variant_id = str(selected.get("selected_variant_id", "") or "")
            symbol = str(selected.get("selected_symbol", "") or "WDC")
            if variant_id:
                return (
                    ".venv-mac/bin/python main.py --collect-symbol-replay-evidence "
                    f"--base-strategy {selected.get('base_strategy_id', '')} "
                    f"--profile-id {selected.get('profile_id', '')} "
                    f"--timeframe {selected.get('timeframe', '')} "
                    f"--variant-id {variant_id} --symbol {symbol}"
                ).strip()
        if self._next_portfolio_action(selected, ranked) == "diagnose_next_best_strategy":
            return (
                ".venv-mac/bin/python main.py --diagnose-next-best-strategy "
                f"--base-strategy {selected.get('base_strategy_id', '')} "
                f"--profile-id {selected.get('profile_id', '')} "
                f"--timeframe {selected.get('timeframe', '')}"
            ).strip()
        if self._next_portfolio_action(selected, ranked) == "audit_paper_candidate":
            variant_id = str(selected.get("selected_variant_id", "") or "")
            base = str(selected.get("base_strategy_id", "") or "")
            profile = str(selected.get("profile_id", "") or "")
            timeframe = str(selected.get("timeframe", "") or "")
            variant_clause = f" --variant-id {variant_id}" if variant_id else ""
            return (
                ".venv-mac/bin/python main.py --paper-candidate-audit "
                f"--base-strategy {base} --profile-id {profile} --timeframe {timeframe}{variant_clause}"
            ).strip()
        if self._next_portfolio_action(selected, ranked) == "retest_across_additional_periods":
            return (
                ".venv-mac/bin/python main.py --strategy-research-planner "
                f"--base-strategy {selected.get('base_strategy_id', '')} "
                f"--profile-id {selected.get('profile_id', '')} "
                f"--timeframe {selected.get('timeframe', '')}"
            ).strip()
        if self._next_portfolio_action(selected, ranked) == "plan_data_backfill_or_resample":
            action = dict(selected.get("data_gap_action") or {})
            mapped = self._data_gap_command(str(action.get("data_gap_action", "") or ""))
            if mapped:
                return mapped
            return ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        if self._next_portfolio_action(selected, ranked) == "optimise_or_precompute_replay_dataset":
            return ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset"
        if self._next_portfolio_action(selected, ranked) == "precompute_bounded_dip_rebound_15Min_outcomes":
            return ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes"
        if self._next_portfolio_action(selected, ranked) == "return_to_portfolio_planner":
            return ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        if selected.get("research_status") in {"deprioritise", "retire_candidate"} and all(
            item.get("research_status") in {"deprioritise", "retire_candidate"} for item in ranked
        ):
            return ".venv-mac/bin/python main.py --research-cycle-status"
        if self._next_portfolio_action(selected, ranked) in {"deprioritise_snapback", "search_new_strategy_family"}:
            return ".venv-mac/bin/python main.py --research-cycle-status"
        command = str(selected.get("latest_planner_command", "") or "")
        if command:
            return command
        return (
            ".venv-mac/bin/python main.py --strategy-research-planner "
            f"--base-strategy {selected.get('base_strategy_id', '')} "
            f"--profile-id {selected.get('profile_id', '')} "
            f"--timeframe {selected.get('timeframe', '')}"
        ).strip()

    def _data_gap_command(self, action_name: str) -> str:
        normalized = str(action_name or "").strip()
        if normalized == "backfill_or_resample_crypto_1Day_bars":
            return ".venv-mac/bin/python main.py --backfill-or-resample-crypto-1day-bars"
        if normalized == "backfill_or_resample_crypto_15Min_bars":
            return ".venv-mac/bin/python main.py --backfill-or-resample-crypto-15min-bars"
        return ""

    def _runtime_action_command(self, runtime_action: dict[str, Any]) -> str:
        action_name = str(
            runtime_action.get("data_or_runtime_action", "")
            or runtime_action.get("action", "")
            or ""
        ).strip()
        if action_name in {
            "precompute_specific_replay_cache",
            "precompute_bounded_dip_rebound_15Min_outcomes",
        }:
            return self._specific_precompute_command_for_target(runtime_action)
        if action_name in {
            "optimise_or_precompute_replay_dataset",
            "optimise_or_precompute_crypto_replay_dataset",
            "optimise_specific_crypto_15Min_replay_cache",
        }:
            return ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset"
        return self._data_gap_command(action_name)

    def _specific_precompute_command_for_target(self, runtime_action: dict[str, Any]) -> str:
        base_strategy_id = str(runtime_action.get("base_strategy_id", "") or "")
        profile_id = str(runtime_action.get("profile_id", "") or "")
        timeframe = str(runtime_action.get("timeframe", "") or "")
        if (
            base_strategy_id == "crypto_research.dip_rebound"
            and profile_id == "dip_rebound"
            and timeframe == "15Min"
        ):
            return ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes"
        if not base_strategy_id or not profile_id or not timeframe:
            return ""
        return SpecificReplayCachePrecomputeReport.command_for_target(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )

    def _runtime_prep_action_name(self, item: dict[str, Any], latest_prep: dict[str, Any]) -> str:
        explicit = str(latest_prep.get("prep_action", "") or "").strip()
        if explicit:
            return explicit
        prep_status = str(latest_prep.get("prep_status", "") or "")
        if prep_status != "replay_prepared_but_still_slow":
            return ""
        base_strategy_id = str(item.get("base_strategy_id", "") or "")
        profile_id = str(item.get("profile_id", "") or "")
        timeframe = str(item.get("timeframe", "") or "")
        if (
            base_strategy_id == "crypto_research.dip_rebound"
            and profile_id == "dip_rebound"
            and timeframe == "15Min"
        ):
            return "precompute_bounded_dip_rebound_15Min_outcomes"
        if base_strategy_id.startswith("crypto_") and timeframe == "15Min":
            return "optimise_specific_crypto_15Min_replay_cache"
        return "precompute_specific_replay_cache"

    def _signal_generation_diagnosis_command(self, item: dict[str, Any]) -> str:
        return (
            ".venv-mac/bin/python main.py --signal-generation-diagnosis "
            f"--base-strategy {item.get('base_strategy_id', '')} "
            f"--profile-id {item.get('profile_id', '')} "
            f"--timeframe {item.get('timeframe', '')}"
        ).strip()

    def _signal_generation_follow_up_command(self, item: dict[str, Any]) -> str:
        diagnosis = dict(item.get("latest_signal_generation_diagnosis") or {})
        command = self._normalized_signal_generation_follow_up_command(
            item=item,
            diagnosis=diagnosis,
        )
        if not command:
            return ""
        diagnosis_dt = self._to_datetime(diagnosis.get("evaluated_at"))
        replay_prep_dt = self._to_datetime(item.get("latest_replay_preparation_timestamp"))
        if diagnosis_dt is None:
            return ""
        if replay_prep_dt is not None and diagnosis_dt <= replay_prep_dt:
            return ""
        return command

    def _normalized_signal_generation_follow_up_command(
        self,
        *,
        item: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> str:
        command = str(diagnosis.get("next_recommended_command", "") or "")
        if not command:
            return ""
        base_strategy_id = str(item.get("base_strategy_id", "") or "")
        profile_id = str(item.get("profile_id", "") or "")
        timeframe = str(item.get("timeframe", "") or "")
        if (
            base_strategy_id == "crypto_research.range_breakout"
            and "--strategy-variant-research-report" in command
        ):
            return (
                ".venv-mac/bin/python main.py --run-strategy-variant-research "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
            )
        return command

    def _find_ranked_item(
        self,
        *,
        ranked: list[dict[str, Any]],
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> dict[str, Any]:
        for item in ranked:
            if (
                str(item.get("base_strategy_id", "") or "") == base_strategy_id
                and str(item.get("profile_id", "") or "") == profile_id
                and str(item.get("timeframe", "") or "") == timeframe
            ):
                return item
        return {}

    def _next_portfolio_action(self, selected: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
        if not selected:
            runtime_action = self._next_data_runtime_action(ranked, {})
            if runtime_action:
                return str(runtime_action.get("action", "") or "no_actionable_candidate")
            return "no_actionable_candidate"
        generated_lifecycle_status = str(selected.get("generated_candidate_lifecycle_status", "") or "")
        if generated_lifecycle_status in {"generated_not_evaluated", "variant_research_pending"}:
            return "run_generated_variant_research"
        if generated_lifecycle_status == "diagnosis_pending":
            return "diagnose_next_best_strategy"
        generated_zero_sample = dict(selected.get("generated_candidate_zero_sample_outcome") or {})
        if generated_zero_sample:
            return str(generated_zero_sample.get("next_required_action", "") or "return_to_portfolio_planner")
        if generated_lifecycle_status == "variant_research_completed":
            return "diagnose_next_best_strategy"
        if generated_lifecycle_status in {
            "no_viable_signal_after_variant_research",
            "insufficient_history_after_variant_research",
        }:
            return "return_to_portfolio_planner"
        if generated_lifecycle_status in {
            "diagnosis_completed",
            "insufficient_data",
            "deprioritise_until_new_data",
            "eligible_for_paper_candidate_audit",
            "no_viable_signal",
        }:
            return "return_to_portfolio_planner"
        if selected.get("research_status") == "audit_required":
            return "audit_paper_candidate"
        if selected.get("research_status") == "promising_but_failed_audit":
            return self._failed_audit_follow_up(selected)
        if selected.get("research_status") == "data_gap":
            return "plan_data_backfill_or_resample"
        if selected.get("research_status") == "runtime_blocked":
            return "optimise_or_precompute_replay_dataset"
        wide = dict(selected.get("wide_symbol_stability", {}) or {})
        verdict = normalize_symbol_subset_verdict(str(wide.get("stability_verdict", "") or ""))
        if verdict == "symbol_promising_and_stable":
            return "research_symbol_filter_variant"
        if verdict in {"symbol_unstable", "symbol_not_promising"}:
            return "return_to_portfolio_planner"
        stopped = self._latest_stopped_branch(ranked)
        if stopped:
            if selected.get("branch_stopped"):
                return "search_new_strategy_family"
            if (
                selected.get("base_strategy_id") != stopped.get("base_strategy_id")
                or selected.get("timeframe") != stopped.get("timeframe")
            ):
                if self._selected_candidate_should_skip_repeat_diagnosis(selected):
                    return f"continue_research_for_{selected.get('base_strategy_id', 'strategy')}"
                return "diagnose_next_best_strategy"
            if float(selected.get("latest_net_return_after_costs", 0.0) or 0.0) <= 0.0:
                return "deprioritise_snapback"
            return "insufficient_edge_continue_observation"
        if selected.get("base_strategy_id") == "mean_reversion.snapback" and selected.get("research_status") in {
            "active_research",
            "insufficient_data",
        }:
            return "collect_more_data_for_snapback_WDC"
        if all(item.get("research_status") in {"deprioritise", "retire_candidate"} for item in ranked):
            return "search_create_new_strategy_family"
        return f"continue_research_for_{selected.get('base_strategy_id', 'strategy')}"

    def _default_experiment_type(self, selected: dict[str, Any]) -> str:
        status = str(selected.get("research_status", "") or "")
        if status == "promising_but_failed_audit":
            return self._failed_audit_follow_up(selected)
        if status == "active_research":
            return "validate_promising_subset"
        if status == "audit_required":
            return "audit_paper_candidate"
        if status == "untested_strategy":
            return "diagnose_next_best_strategy"
        if status == "data_gap":
            return "plan_data_backfill_or_resample"
        if status == "runtime_blocked":
            return "optimise_or_precompute_replay_dataset"
        if status in {"deprioritise", "retire_candidate"}:
            return "search_create_new_strategy_family"
        return "insufficient_data_collect_more"

    def _research_expansion_state(
        self,
        *,
        ranked: list[dict[str, Any]],
        next_data_runtime_action: dict[str, Any],
    ) -> dict[str, Any]:
        if ranked and any(
            self._is_actionable_research_candidate(
                item,
                blocked_or_parked_candidate={},
                ranked=ranked,
            )
            for item in ranked
        ):
            return {
                "portfolio_research_status": "research_in_progress",
                "research_universe_status": "active_current_strategy_set",
            }
        if not ranked:
            return {
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "no_persisted_strategy_evidence",
                "next_required_operator_action": "generate_new_research_candidates",
                "next_research_expansion_action": "generate_new_strategy_family_research_only",
                "next_recommended_command": DEFAULT_RESEARCH_EXPANSION_COMMAND,
                "reason": "No persisted strategy evidence was available, so the next safe move is research-only expansion planning.",
            }
        runtime_action = str(next_data_runtime_action.get("action", "") or "")
        runtime_follow_up = str(next_data_runtime_action.get("data_or_runtime_action", "") or "")
        if runtime_action and runtime_action != "adjust_signal_generation_research_only":
            return {
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "blocked_on_data_or_runtime",
            }
        if runtime_action == "adjust_signal_generation_research_only" and runtime_follow_up == "deprioritise_until_new_data":
            return {
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "next_required_operator_action": "expand_signal_generation_research_only",
                "next_research_expansion_action": "widen_range_breakout_signal_search_research_only",
                "next_recommended_command": DEFAULT_RESEARCH_EXPANSION_COMMAND,
                "reason": "Current signal-generation follow-ups no longer produce actionable candidates, so the safe next move is research-only expansion instead of repeating deprioritise_until_new_data.",
            }
        exhausted_statuses = {
            "deprioritise_until_new_data",
            "no_viable_signal_after_precompute",
            "no_viable_signal_after_variant_research",
            "insufficient_history_after_variant_research",
            "deprioritise",
            "retire_candidate",
            "insufficient_data_after_precompute",
        }
        if ranked and all(str(item.get("research_status", "") or "") in exhausted_statuses for item in ranked):
            return {
                "portfolio_research_status": "no_actionable_candidate",
                "research_universe_status": "exhausted_current_strategy_set",
                "next_required_operator_action": (
                    "expand_signal_generation_research_only"
                    if runtime_action == "adjust_signal_generation_research_only"
                    else "generate_new_research_candidates"
                ),
                "next_research_expansion_action": (
                    "widen_range_breakout_signal_search_research_only"
                    if runtime_action == "adjust_signal_generation_research_only"
                    else "generate_new_strategy_family_research_only"
                ),
                "next_recommended_command": DEFAULT_RESEARCH_EXPANSION_COMMAND,
                "reason": "No current candidate is actionable and the remaining work is research-only expansion rather than more retries on the same strategy set.",
            }
        return {
            "portfolio_research_status": "no_actionable_candidate",
            "research_universe_status": "waiting_for_new_data",
        }

    def _no_actionable_candidate_plan(
        self,
        *,
        ranked: list[dict[str, Any]],
        research_expansion: dict[str, Any],
        next_data_runtime_action: dict[str, Any],
    ) -> dict[str, Any]:
        portfolio_status = str(research_expansion.get("portfolio_research_status", "") or "")
        if portfolio_status != "no_actionable_candidate":
            return {}
        universe_status = str(research_expansion.get("research_universe_status", "") or "")
        if universe_status == "blocked_on_data_or_runtime":
            next_safe_operator_command = self._runtime_action_command(next_data_runtime_action)
            return {
                "terminal_research_state": "collect_more_historical_data",
                "no_actionable_reason": str(
                    next_data_runtime_action.get("reason", "")
                    or "Current candidates remain blocked by data or runtime preparation requirements."
                ),
                "waiting_for": str(
                    next_data_runtime_action.get("data_or_runtime_action", "")
                    or next_data_runtime_action.get("action", "")
                    or "data_or_runtime_preparation"
                ),
                "minimum_new_data_required": "bounded replay-ready historical bars for the blocked strategy/timeframe",
                "data_sources_needed": ["persisted_historical_bars", "replay_dataset_preparation"],
                "research_universe_expansion_options": [],
                "next_safe_operator_action": str(
                    research_expansion.get("next_required_operator_action", "")
                    or next_data_runtime_action.get("data_or_runtime_action", "")
                    or next_data_runtime_action.get("action", "")
                    or "collect_more_historical_data"
                ),
                "next_safe_operator_command": next_safe_operator_command,
                "next_check_command": str(
                    research_expansion.get("next_recommended_command", "")
                    or DEFAULT_NO_ACTIONABLE_CHECK_COMMAND
                ),
            }
        if universe_status == "exhausted_current_strategy_set":
            return {
                "terminal_research_state": "generate_new_strategy_family",
                "no_actionable_reason": str(
                    research_expansion.get("reason", "")
                    or "All current candidates are exhausted, blocked, or no longer produce viable research follow-ups."
                ),
                "waiting_for": "new_strategy_family_or_research_universe_expansion",
                "minimum_new_data_required": "",
                "data_sources_needed": [],
                "research_universe_expansion_options": [
                    "generate_new_strategy_family",
                    "widen_research_universe",
                ],
                "next_safe_operator_action": str(
                    research_expansion.get("next_required_operator_action", "")
                    or "generate_new_research_candidates"
                ),
                "next_safe_operator_command": str(
                    research_expansion.get("next_recommended_command", "")
                    or DEFAULT_RESEARCH_EXPANSION_COMMAND
                ),
                "next_check_command": str(
                    research_expansion.get("next_recommended_command", "")
                    or DEFAULT_RESEARCH_EXPANSION_COMMAND
                ),
            }
        if universe_status != "waiting_for_new_data":
            return {}
        generated_zero_sample_candidates = [
            item for item in ranked
            if dict(item.get("generated_candidate_zero_sample_outcome") or {})
        ]
        data_gap_candidates = [
            item for item in ranked
            if str(item.get("research_status", "") or "") == "data_gap"
        ]
        if data_gap_candidates and len(data_gap_candidates) == len(ranked):
            return {
                "terminal_research_state": "collect_more_historical_data",
                "no_actionable_reason": "All remaining research candidates are blocked by historical data gaps.",
                "waiting_for": "additional_historical_market_data",
                "minimum_new_data_required": "historical bars covering the blocked strategy timeframes with enough replay coverage",
                "data_sources_needed": ["persisted_historical_bars"],
                "research_universe_expansion_options": ["widen_research_universe"],
                "next_safe_operator_action": "collect_more_historical_data",
                "next_safe_operator_command": "",
                "next_check_command": DEFAULT_NO_ACTIONABLE_CHECK_COMMAND,
            }
        if generated_zero_sample_candidates:
            return {
                "terminal_research_state": "generate_new_strategy_family_or_wait_for_new_market_data",
                "no_actionable_reason": "All current and generated candidates are exhausted, blocked, or zero-sample.",
                "waiting_for": "new_market_data_or_new_strategy_family",
                "minimum_new_data_required": "additional crypto bars covering enough replay windows for zero-sample candidates",
                "data_sources_needed": ["persisted_historical_bars", "generated_candidate_variant_research"],
                "research_universe_expansion_options": [
                    "generate_new_strategy_family",
                    "widen_research_universe",
                    "wait_for_new_market_data",
                ],
                "next_safe_operator_action": "wait_for_new_market_data_or_generate_new_strategy_family",
                "next_safe_operator_command": "",
                "next_check_command": DEFAULT_NO_ACTIONABLE_CHECK_COMMAND,
            }
        if not ranked:
            return {
                "terminal_research_state": "generate_new_strategy_family",
                "no_actionable_reason": "No persisted strategy evidence is available for safe portfolio research selection.",
                "waiting_for": "new_strategy_family",
                "minimum_new_data_required": "",
                "data_sources_needed": [],
                "research_universe_expansion_options": ["generate_new_strategy_family", "widen_research_universe"],
                "next_safe_operator_action": "generate_new_strategy_family",
                "next_safe_operator_command": "",
                "next_check_command": DEFAULT_NO_ACTIONABLE_CHECK_COMMAND,
            }
        return {
            "terminal_research_state": "no_safe_research_action",
            "no_actionable_reason": "No safe research action remains within the current candidate set.",
            "waiting_for": "explicit_operator_review",
            "minimum_new_data_required": "",
            "data_sources_needed": [],
            "research_universe_expansion_options": [],
            "next_safe_operator_action": "explicitly_stop_because_no_safe_research_path_remains",
            "next_safe_operator_command": "",
            "next_check_command": DEFAULT_NO_ACTIONABLE_CHECK_COMMAND,
        }

    def _execution_available(self, selected: dict[str, Any], ranked: list[dict[str, Any]]) -> bool:
        if not selected:
            return False
        if self._next_portfolio_action(selected, ranked) == "collect_more_data_for_snapback_WDC":
            return bool(selected.get("selected_variant_id")) and bool(selected.get("selected_symbol") or "WDC")
        return False

    def _select_next_strategy(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        selected, _diagnostics = self._select_next_actionable_research_candidate(
            ranked,
            blocked_or_parked_candidate={},
            parked_candidate_keys_this_run=(),
        )
        return selected

    def _select_current_known_best_candidate(self, strategies: list[dict[str, Any]]) -> dict[str, Any]:
        if not strategies:
            return {}
        return sorted(
            strategies,
            key=lambda item: (
                self._known_best_priority(item),
                -int(item.get("latest_sample_size", 0) or 0),
                -float(item.get("latest_net_return_after_costs", 0.0) or 0.0),
                str(item.get("base_strategy_id", "") or ""),
                str(item.get("profile_id", "") or ""),
                str(item.get("timeframe", "") or ""),
            ),
        )[0]

    def _select_next_actionable_research_candidate(
        self,
        ranked: list[dict[str, Any]],
        *,
        blocked_or_parked_candidate: dict[str, Any],
        parked_candidate_keys_this_run: list[str] | tuple[str, ...],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        parked_key_set = set(parked_candidate_keys_this_run)
        actionable: list[dict[str, Any]] = []
        alternatives_considered: list[dict[str, Any]] = []
        for item in ranked:
            candidate_key = self._candidate_key_from_item(item)
            rejection_reason = self._actionable_research_rejection_reason(
                item,
                blocked_or_parked_candidate=blocked_or_parked_candidate,
                ranked=ranked,
                parked_candidate_keys_this_run=parked_key_set,
            )
            alternatives_considered.append(
                {
                    "candidate_key": candidate_key,
                    "priority_rank": int(item.get("priority_rank", 99) or 99),
                    "priority_score": float(item.get("priority_score", 0.0) or 0.0),
                    "research_status": str(item.get("research_status", "") or ""),
                    "selected": rejection_reason == "",
                    "rejection_reason": rejection_reason,
                }
            )
            if rejection_reason == "":
                actionable.append(item)
        if not actionable:
            return {}, {
                "candidate_key": "",
                "parked_candidates_received": list(parked_candidate_keys_this_run),
                "ranked_alternatives_considered": alternatives_considered,
                "parked_candidate_returned": False,
                "returned_parked_candidate_reason": "",
            }
        selected = sorted(
            actionable,
            key=lambda item: (
                self._actionable_research_priority(item),
                int(item.get("priority_rank", 99) or 99),
                -float(item.get("priority_score", 0.0) or 0.0),
                -int(item.get("latest_sample_size", 0) or 0),
            ),
        )[0]
        selected_key = self._candidate_key_from_item(selected)
        returned_parked = selected_key in parked_key_set
        return selected, {
            "candidate_key": selected_key,
            "parked_candidates_received": list(parked_candidate_keys_this_run),
            "ranked_alternatives_considered": alternatives_considered,
            "parked_candidate_returned": returned_parked,
            "returned_parked_candidate_reason": (
                "selected_candidate_key_was_present_in_run_scoped_parked_candidates"
                if returned_parked
                else ""
            ),
        }

    def _select_next_paper_candidate(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        for item in ranked:
            if item.get("branch_stopped"):
                continue
            status = str(item.get("research_status", "") or "")
            if status in {
                "data_gap",
                "insufficient_data",
                "runtime_blocked",
                "deprioritise",
                "retire_candidate",
                "untested_strategy",
            }:
                continue
            if status == "promising_but_failed_audit" and self._follow_up_remains_unresolved(item):
                continue
            return item
        return {}

    def _follow_up_remains_unresolved(self, item: dict[str, Any]) -> bool:
        if str(item.get("research_status", "") or "") != "promising_but_failed_audit":
            return False
        wide = dict(item.get("wide_symbol_stability", {}) or {})
        wide_verdict = str(wide.get("stability_verdict", "") or "")
        if not wide_verdict:
            return False
        if normalize_symbol_subset_verdict(wide_verdict) in {
            "symbol_promising_but_insufficient",
            "no_usable_subset_data",
        }:
            return True
        return False

    def _blocked_or_parked_candidate(self, current_known_best: dict[str, Any]) -> dict[str, Any]:
        if not current_known_best:
            return {}
        status = str(current_known_best.get("research_status", "") or "")
        if status in {
            "promising_but_failed_audit",
            "data_gap",
            "insufficient_data_after_precompute",
            "insufficient_data",
            "runtime_blocked",
            "deprioritise_until_new_data",
            "no_viable_signal_after_precompute",
            "deprioritise",
            "retire_candidate",
            "audit_required",
        }:
            return current_known_best
        if current_known_best.get("branch_stopped"):
            return current_known_best
        return {}

    def _is_actionable_research_candidate(
        self,
        item: dict[str, Any],
        *,
        blocked_or_parked_candidate: dict[str, Any],
        ranked: list[dict[str, Any]],
    ) -> bool:
        return (
            self._actionable_research_rejection_reason(
                item,
                blocked_or_parked_candidate=blocked_or_parked_candidate,
                ranked=ranked,
                parked_candidate_keys_this_run=set(),
            )
            == ""
        )

    def _actionable_research_rejection_reason(
        self,
        item: dict[str, Any],
        *,
        blocked_or_parked_candidate: dict[str, Any],
        ranked: list[dict[str, Any]],
        parked_candidate_keys_this_run: set[str],
    ) -> str:
        if not item:
            return "missing_candidate"
        if self._candidate_key_from_item(item) in parked_candidate_keys_this_run:
            return "parked_for_current_autopilot_run"
        if item.get("branch_stopped"):
            return "branch_stopped"
        if not self._generated_candidate_eligible_for_diagnosis(item):
            return self._generated_candidate_ineligible_reason(item)
        if self._is_same_candidate(item, blocked_or_parked_candidate) and self._is_parked_candidate(item):
            return "matches_current_globally_blocked_or_parked_candidate"
        if self._candidate_blocked_by_recent_autopilot_no_progress(item, ranked=ranked):
            return "blocked_by_recent_autopilot_no_progress"
        status = str(item.get("research_status", "") or "")
        if status in {
            "deprioritise",
            "deprioritise_until_new_data",
            "no_viable_signal_after_precompute",
            "no_viable_signal_after_variant_research",
            "insufficient_history_after_variant_research",
            "retire_candidate",
            "paper_candidate_requires_manual_approval",
        }:
            return f"research_status_{status}"
        if status in {"data_gap", "runtime_blocked"}:
            return f"research_status_{status}"
        if status == "audit_required":
            return ""
        if status == "promising_but_failed_audit":
            return "" if self._has_pending_failed_audit_follow_up(item) else "failed_audit_follow_up_already_resolved"
        if status == "insufficient_data_after_precompute":
            return "research_status_insufficient_data_after_precompute"
        if status == "insufficient_data":
            generated_lifecycle = str(item.get("generated_candidate_lifecycle_status", "") or "")
            if generated_lifecycle in {
                "generated_not_evaluated",
                "variant_research_pending",
                "diagnosis_pending",
            }:
                return ""
            return "" if int(item.get("latest_sample_size", 0) or 0) > 0 else "insufficient_data_without_samples"
        if status == "untested_strategy":
            if item.get("recent_zero_evidence_attempted"):
                return "recent_zero_evidence_attempted"
            if self._requires_minimal_support(item):
                return "unsupported_strategy_profile"
            return ""
        return "" if status == "active_research" else f"research_status_{status or 'unknown'}"

    def _normalise_parked_candidate_keys(self, parked_candidate_keys_this_run: list[str] | None) -> list[str]:
        normalised: list[str] = []
        for key in list(parked_candidate_keys_this_run or []):
            candidate_key = str(key or "").strip()
            if candidate_key and candidate_key not in normalised:
                normalised.append(candidate_key)
        return normalised

    def _candidate_key_from_item(self, item: dict[str, Any]) -> str:
        if not item:
            return ""
        return (
            f"{str(item.get('base_strategy_id', '') or '')}/"
            f"{str(item.get('profile_id', '') or '')}/"
            f"{str(item.get('timeframe', '') or '')}"
        )

    def _actionable_research_priority(self, item: dict[str, Any]) -> int:
        status = str(item.get("research_status", "") or "")
        generated_lifecycle = str(item.get("generated_candidate_lifecycle_status", "") or "")
        if generated_lifecycle in {
            "generated_not_evaluated",
            "variant_research_pending",
            "diagnosis_pending",
        }:
            return 1
        if status == "promising_but_failed_audit" and self._has_pending_failed_audit_follow_up(item):
            return 2
        if status == "audit_required":
            return 3
        if status == "insufficient_data_after_precompute":
            return 4
        if status == "insufficient_data":
            return 4
        if status == "runtime_blocked":
            return 5
        if status == "untested_strategy":
            return 6
        if status == "active_research":
            return 7
        if status == "data_gap":
            return 8
        return 9

    def _generated_candidate_eligible_for_diagnosis(self, item: dict[str, Any]) -> bool:
        return not bool(self._generated_candidate_ineligible_reason(item))

    def _generated_candidate_ineligible_reason(self, item: dict[str, Any]) -> str:
        if not item:
            return ""
        metadata = dict(item.get("generated_candidate_metadata") or {})
        if not metadata:
            return ""
        lifecycle_status = str(
            item.get("generated_candidate_lifecycle_status")
            or metadata.get("lifecycle_status")
            or ""
        )
        evaluation_status = str(metadata.get("evaluation_status", "") or "")
        latest_variant_at = self._to_datetime(item.get("latest_variant_evaluation_timestamp"))
        generated_evidence_at = self._to_datetime(
            metadata.get("generated_candidate_evidence_at") or metadata.get("generated_at")
        )
        if latest_variant_at is None or generated_evidence_at is None or latest_variant_at < generated_evidence_at:
            return ""
        baseline_sample_size = int(item.get("latest_sample_size", 0) or 0)
        best_variant_sample_size = self._coalesce_int(
            metadata.get("best_variant_sample_size"),
            ((item.get("generated_candidate_zero_sample_outcome") or {}).get("best_variant_sample_size")),
            ((item.get("generated_candidate_runtime_summary") or {}).get("best_variant_sample_size")),
            0,
        )
        if baseline_sample_size > 0 or best_variant_sample_size > 0:
            return ""
        if self._generated_candidate_has_newer_nonzero_variant_evidence(item):
            return ""
        if lifecycle_status == "variant_research_completed" and evaluation_status == "evaluated_no_samples":
            return "generated_candidate_latest_variant_evidence_is_zero_sample"
        if lifecycle_status in {"variant_research_completed", "diagnosis_pending", "insufficient_data"}:
            return "generated_candidate_latest_variant_evidence_is_zero_sample"
        return "generated_candidate_latest_variant_evidence_is_zero_sample"

    def _generated_candidate_has_newer_nonzero_variant_evidence(self, item: dict[str, Any]) -> bool:
        metadata = dict(item.get("generated_candidate_metadata") or {})
        if not metadata:
            return False
        latest_variant_at = self._to_datetime(item.get("latest_variant_evaluation_timestamp"))
        generated_evidence_at = self._to_datetime(
            metadata.get("generated_candidate_evidence_at") or metadata.get("generated_at")
        )
        if latest_variant_at is None or generated_evidence_at is None or latest_variant_at <= generated_evidence_at:
            return False
        baseline_sample_size = int(item.get("latest_sample_size", 0) or 0)
        best_variant_sample_size = self._coalesce_int(
            metadata.get("best_variant_sample_size"),
            ((item.get("generated_candidate_runtime_summary") or {}).get("best_variant_sample_size")),
            0,
        )
        return baseline_sample_size > 0 or best_variant_sample_size > 0

    def _known_best_priority(self, item: dict[str, Any]) -> int:
        status = str(item.get("research_status", "") or "")
        if item.get("branch_stopped"):
            return 1
        if bool((item.get("audit_report", {}) or {}).get("audit_verdict")):
            return 2
        if bool(item.get("any_variant_beat_thresholds")):
            return 3
        if status == "audit_required":
            return 4
        if status == "active_research":
            return 5
        if status == "insufficient_data":
            return 6
        if status == "untested_strategy":
            return 7
        if status == "data_gap":
            return 8
        return 9

    def _has_pending_failed_audit_follow_up(self, item: dict[str, Any]) -> bool:
        if str(item.get("research_status", "") or "") != "promising_but_failed_audit":
            return False
        if self._is_parked_candidate(item):
            return False
        return True

    def _is_parked_candidate(self, item: dict[str, Any]) -> bool:
        if not item:
            return False
        if item.get("branch_stopped"):
            return True
        status = str(item.get("research_status", "") or "")
        if status == "deprioritise":
            return True
        if status in {"deprioritise_until_new_data", "no_viable_signal_after_precompute"}:
            return True
        if status in {"no_viable_signal_after_variant_research", "insufficient_history_after_variant_research"}:
            return True
        if status == "runtime_blocked":
            return True
        if status == "promising_but_failed_audit" and self._follow_up_remains_unresolved(item):
            return True
        if status == "promising_but_failed_audit" and self._failed_audit_follow_up(item) == "deprioritise_until_more_data":
            return True
        return False

    def _is_same_candidate(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if not left or not right:
            return False
        return (
            str(left.get("base_strategy_id", "") or "") == str(right.get("base_strategy_id", "") or "")
            and str(left.get("profile_id", "") or "") == str(right.get("profile_id", "") or "")
            and str(left.get("timeframe", "") or "") == str(right.get("timeframe", "") or "")
        )

    def _requires_minimal_support(self, item: dict[str, Any]) -> bool:
        return str(item.get("zero_decision_reason", "") or "") == "unsupported_strategy_profile"

    def _runtime_blocked_action(self, item: dict[str, Any]) -> dict[str, Any]:
        if str(item.get("research_status", "") or "") != "runtime_blocked":
            return {}
        latest_prep = dict(item.get("latest_replay_preparation") or {})
        if self._precompute_already_completed(item):
            return {}
        prep_status = str(latest_prep.get("prep_status", "") or "")
        prep_action = self._runtime_prep_action_name(item, latest_prep)
        prep_reason = str(latest_prep.get("blocker_reason", "") or latest_prep.get("reason", "") or "")
        if prep_status == "replay_prepared_but_still_slow":
            return {
                "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                "profile_id": str(item.get("profile_id", "") or ""),
                "timeframe": str(item.get("timeframe", "") or ""),
                "action": prep_action or "precompute_specific_replay_cache",
                "data_or_runtime_action": prep_action or "precompute_specific_replay_cache",
                "runtime_blocker": str(item.get("zero_decision_reason", "") or ""),
                "reason": prep_reason or "Replay preparation completed, but runtime reads are still too slow for a bounded replay step.",
            }
        return {
            "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
            "profile_id": str(item.get("profile_id", "") or ""),
            "timeframe": str(item.get("timeframe", "") or ""),
            "action": "optimise_or_precompute_replay_dataset",
            "data_or_runtime_action": "optimise_or_precompute_crypto_replay_dataset",
            "runtime_blocker": str(item.get("zero_decision_reason", "") or ""),
            "reason": "Replay diagnosis is blocked by runtime/data access, so the next safe move is dataset/runtime preparation instead of re-diagnosing already weak evidence.",
        }

    def _next_data_runtime_action(
        self,
        ranked: list[dict[str, Any]],
        selected: dict[str, Any],
    ) -> dict[str, Any]:
        if selected:
            return {}
        for item in ranked:
            runtime_action = self._runtime_blocked_action(item)
            if runtime_action:
                return runtime_action
        for item in ranked:
            if str(item.get("research_status", "") or "") != "data_gap":
                continue
            latest_prep = dict(item.get("latest_replay_preparation") or {})
            action = dict(item.get("data_gap_action") or {})
            return {
                "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                "profile_id": str(item.get("profile_id", "") or ""),
                "timeframe": str(item.get("timeframe", "") or ""),
                "action": "backfill_or_resample_data",
                "data_or_runtime_action": str(
                    latest_prep.get("prep_action")
                    or action.get("data_gap_action", "")
                    or "backfill_or_resample_missing_bars"
                ),
                "runtime_blocker": "",
                "reason": str(latest_prep.get("blocker_reason", "") or action.get("reason", "") or ""),
            }
        for item in ranked:
            latest_prep = dict(item.get("latest_replay_preparation") or {})
            if str(latest_prep.get("prep_status", "") or "") != "replay_prepared_but_no_signals":
                continue
            return {
                "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                "profile_id": str(item.get("profile_id", "") or ""),
                "timeframe": str(item.get("timeframe", "") or ""),
                "action": "adjust_signal_generation_research_only",
                "data_or_runtime_action": str(latest_prep.get("prep_action", "") or "deprioritise_until_new_data"),
                "runtime_blocker": "",
                "reason": str(latest_prep.get("blocker_reason", "") or "Replay preparation found usable bars but no actionable signals."),
            }
        return {}

    def _runtime_action_diagnostics(
        self,
        *,
        ranked: list[dict[str, Any]],
        next_data_runtime_action: dict[str, Any],
    ) -> dict[str, str]:
        action_name = str(
            next_data_runtime_action.get("data_or_runtime_action", "")
            or next_data_runtime_action.get("action", "")
            or ""
        ).strip()
        mapping_relevant_actions = {
            "precompute_specific_replay_cache",
            "precompute_bounded_dip_rebound_15Min_outcomes",
            "optimise_specific_crypto_15Min_replay_cache",
        }
        mapped_command = self._runtime_action_command(next_data_runtime_action)
        target = self._find_ranked_item(
            ranked=ranked,
            base_strategy_id=str(next_data_runtime_action.get("base_strategy_id", "") or ""),
            profile_id=str(next_data_runtime_action.get("profile_id", "") or ""),
            timeframe=str(next_data_runtime_action.get("timeframe", "") or ""),
        )
        precompute_already_completed = self._precompute_already_completed(target)
        why_blank = ""
        if action_name in mapping_relevant_actions and not mapped_command:
            if not target:
                why_blank = "no_matching_runtime_action_candidate"
            else:
                why_blank = "no_safe_command_mapping_for_runtime_action"
        elif action_name in mapping_relevant_actions and precompute_already_completed:
            why_blank = "candidate_precompute_already_completed"
        return {
            "precompute_mapping_attempted": "yes" if action_name in mapping_relevant_actions else "no",
            "mapped_precompute_command": mapped_command,
            "precompute_already_completed": "yes" if precompute_already_completed else "no",
            "why_next_safe_operator_command_blank": why_blank,
        }

    def _precompute_already_completed(self, item: dict[str, Any] | None) -> bool:
        if not item:
            return False
        latest_prep = dict(item.get("latest_replay_preparation") or {})
        if str(latest_prep.get("runtime_status", "") or "") != "precomputed":
            return False
        if str(latest_prep.get("cache_status", "") or "").lower() != "fresh":
            return False
        classification_reason = str(((item.get("latest_autopilot_no_progress") or {}).get("classification_reason", "")) or "")
        return (
            classification_reason == "insufficient_data_after_precompute"
            or classification_reason == "no_viable_signal_after_precompute"
            or classification_reason.startswith("precompute_completed_but_only_")
        )

    def _failed_audit_follow_up(self, selected: dict[str, Any]) -> str:
        audit_status = str(((selected.get("audit_report", {}) or {}).get("audit_status", "")) or "")
        audit_verdict = str(((selected.get("audit_report", {}) or {}).get("audit_verdict", "")) or "")
        sample_size = int(selected.get("latest_sample_size", 0) or 0)
        if audit_status == "parked_until_new_data":
            if sample_size < 200:
                return "collect_more_out_of_sample_data"
            return "deprioritise_until_more_data"
        if audit_status == "blocked_pending_more_data":
            return "collect_more_out_of_sample_data"
        if audit_status in {"deprioritised", "failed_audit"}:
            return "deprioritise_until_more_data"
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            if sample_size < 200:
                return "collect_more_out_of_sample_data"
            return "retest_across_additional_periods"
        return "deprioritise_until_more_data"

    def _recent_zero_evidence_attempted(
        self,
        *,
        latest_sample_size: int,
        planner_report: dict[str, Any],
        latest_cycle: dict[str, Any],
        variant_report: dict[str, Any],
        generated_candidate_pending: bool = False,
    ) -> bool:
        if latest_sample_size > 0:
            return False
        if int(latest_cycle.get("outcomes_recorded", 0) or 0) > 0:
            return False
        if generated_candidate_pending:
            return False
        if str(planner_report.get("selected_experiment_type", "") or ""):
            return True
        if int(variant_report.get("variants_generated", 0) or 0) > 0:
            return True
        return False

    def _candidate_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        if not item:
            return {}
        data_gap_action = dict(item.get("data_gap_action") or {})
        latest_no_progress = dict(item.get("latest_autopilot_no_progress") or {})
        reason = str(
            latest_no_progress.get("classification_reason", "")
            or data_gap_action.get("reason", "")
            or ""
        )
        summary = {
            "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
            "profile_id": str(item.get("profile_id", "") or ""),
            "timeframe": str(item.get("timeframe", "") or ""),
            "research_status": str(item.get("research_status", "") or ""),
            "data_gap_action": str(data_gap_action.get("data_gap_action", "") or ""),
            "reason": reason,
        }
        generated_zero_sample = dict(item.get("generated_candidate_zero_sample_outcome") or {})
        if generated_zero_sample:
            summary["reason"] = str(generated_zero_sample.get("reason", "") or summary["reason"])
            summary["next_required_action"] = str(generated_zero_sample.get("next_required_action", "") or "")
            summary["coverage_symbols_seen"] = int(generated_zero_sample.get("coverage_symbols_seen", 0) or 0)
            summary["eligible_symbols_after_filters"] = int(generated_zero_sample.get("eligible_symbols_after_filters", 0) or 0)
            summary["symbols_processed_for_strategy"] = int(generated_zero_sample.get("symbols_processed_for_strategy", 0) or 0)
            summary["zero_sample_reason"] = str(generated_zero_sample.get("zero_sample_reason", "") or "")
            summary["history_coverage_reason"] = str(generated_zero_sample.get("history_coverage_reason", "") or "")
            summary["no_progress_classification"] = str(generated_zero_sample.get("no_progress_classification", "") or "")
            summary["no_progress_reason"] = str(generated_zero_sample.get("no_progress_reason", "") or "")
            summary["missing_required_fields"] = list(generated_zero_sample.get("missing_required_fields", []) or [])
        lifecycle_status = str(item.get("generated_candidate_lifecycle_status", "") or "")
        if lifecycle_status:
            summary["lifecycle_status"] = lifecycle_status
        metadata = dict(item.get("generated_candidate_metadata") or {})
        evaluation_status = str(metadata.get("evaluation_status", "") or "")
        if evaluation_status:
            summary["evaluation_status"] = evaluation_status
        return summary

    def _why_not_selected_for_paper(self, item: dict[str, Any]) -> str:
        if not item:
            return "No known candidate."
        audit_status = str(((item.get("audit_report", {}) or {}).get("audit_status", "")) or "")
        audit_verdict = str(((item.get("audit_report", {}) or {}).get("audit_verdict", "")) or "")
        if audit_status == "parked_until_new_data":
            return "Parked by paper-candidate audit until fresh evidence arrives; remain research-only."
        if audit_status == "blocked_pending_more_data":
            return "Blocked by paper-candidate audit pending more evidence; remain research-only."
        if audit_status in {"deprioritised", "failed_audit"}:
            return "Rejected by paper-candidate audit; remain research-only."
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "Rejected by paper-candidate audit due to concentration fragility; remain research-only."
        if item.get("research_status") == "audit_required":
            return "Audit still required before any manual paper approval decision."
        if item.get("research_status") == "paper_candidate_requires_manual_approval":
            return "Manual paper approval has not been granted."
        return "No paper approval path is active from this portfolio planner output."

    def _is_stopped_or_failed_branch(self, item: dict[str, Any]) -> bool:
        return bool(item.get("branch_stopped")) or item.get("research_status") == "promising_but_failed_audit"

    def _stopped_or_failed_branch_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        summary = self._candidate_summary(item)
        summary["reason"] = str(
            ((item.get("audit_report", {}) or {}).get("audit_verdict", ""))
            or ((item.get("wide_symbol_stability", {}) or {}).get("stability_verdict", ""))
            or ""
        )
        return summary

    def _branch_stopped(self, wide_symbol_stability: dict[str, Any]) -> bool:
        verdict = normalize_symbol_subset_verdict(str((wide_symbol_stability or {}).get("stability_verdict", "") or ""))
        return verdict in {"symbol_unstable", "symbol_not_promising"}

    def _stopped_branch_name(self, *, identity: _StrategyIdentity, symbol: str) -> str:
        if identity.base_strategy_id == "mean_reversion.snapback" and symbol:
            return f"snapback_{symbol}"
        if symbol:
            return f"{identity.base_strategy_id}_{symbol}"
        return identity.base_strategy_id

    def _latest_stopped_branch(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        for item in ranked:
            wide = dict(item.get("wide_symbol_stability", {}) or {})
            if not self._branch_stopped(wide):
                continue
            summary = dict(wide.get("selected_symbol_summary", {}) or {})
            return {
                "branch_name": str(item.get("stopped_branch_name", "") or ""),
                "stability_verdict": normalize_symbol_subset_verdict(str(wide.get("stability_verdict", "") or "")),
                "wide_sample_size": int(summary.get("sample_size", 0) or 0),
                "wide_net_return_after_costs": float(summary.get("net_return_after_costs", 0.0) or 0.0),
                "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                "timeframe": str(item.get("timeframe", "") or ""),
            }
        return {}

    def _latest_wide_symbol_stability(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
    ) -> dict[str, Any]:
        if not variant_id or not symbol:
            return {}
        if not hasattr(self, "_cached_wide_stability"):
            self._cached_wide_stability = {}
        cache_key = (base_strategy_id, profile_id, timeframe, variant_id, symbol)
        cached = self._cached_wide_stability.get(cache_key)
        if cached is not None:
            return dict(cached)
        for item in self.usage_ledger.list_strategy_variant_evaluations(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            limit=50,
        ):
            raw = dict(item.get("raw_json", {}) or {})
            if raw.get("report_type") != "symbol_subset_stability":
                continue
            if not bool(raw.get("wider_period")):
                continue
            if str(raw.get("symbol", "")).upper() != str(symbol).upper():
                continue
            raw["stability_verdict"] = normalize_symbol_subset_verdict(str(raw.get("stability_verdict", "") or ""))
            self._cached_wide_stability[cache_key] = dict(raw)
            return raw
        latest_current: dict[str, Any] = {}
        if variant_id:
            for item in self.usage_ledger.list_strategy_variant_evaluations(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                limit=100,
            ):
                raw = dict(item.get("raw_json", {}) or {})
                if raw.get("report_type") != "symbol_subset_stability":
                    continue
                if str(raw.get("symbol", "")).upper() != str(symbol).upper():
                    continue
                raw["stability_verdict"] = normalize_symbol_subset_verdict(str(raw.get("stability_verdict", "") or ""))
                if not bool(raw.get("wider_period")):
                    if not latest_current:
                        latest_current = dict(raw)
                    continue
                raw["stability_verdict"] = normalize_symbol_subset_verdict(str(raw.get("stability_verdict", "") or ""))
                self._cached_wide_stability[cache_key] = dict(raw)
                return raw
        if latest_current:
            self._cached_wide_stability[cache_key] = dict(latest_current)
            return latest_current
        self._cached_wide_stability[cache_key] = {}
        return {}

    def _symbol_follow_up_status(self, selected: dict[str, Any]) -> str:
        command = str(selected.get("latest_planner_command", "") or self._proposed_next_command(selected, []))
        if "--symbol-subset-stability-report" in command:
            return "symbol_subset_follow_up"
        if "--collect-symbol-replay-evidence" in command:
            return "same_strategy_follow_up"
        if str(selected.get("research_status", "") or "") == "data_gap":
            return "data_gap_action"
        return "new_strategy_selected"

    def _data_gap_action(self, *, identity: _StrategyIdentity, data_adequacy: dict[str, Any]) -> dict[str, Any]:
        zero_decision_reason = str((data_adequacy or {}).get("zero_decision_reason", "") or "")
        if zero_decision_reason != "no_bars_for_timeframe":
            return {}
        timeframe = str(identity.timeframe or "")
        reason = f"no {timeframe} crypto bars available" if timeframe else "no bars available for requested timeframe"
        action = {
            "research_status": "insufficient_data",
            "data_gap_action": f"backfill_or_resample_crypto_{timeframe}_bars" if timeframe else "backfill_or_resample_missing_bars",
            "reason": reason,
        }
        if str(identity.base_strategy_id or "").startswith("crypto_") and timeframe == "1Day" and self._crypto_15min_bars_available():
            action["action_candidates"] = [
                "resample_15Min_bars_into_1Day_bars_research_only_if_provenance_is_auditable",
                "request_or_load_1Day_crypto_historical_backfill",
            ]
        return action

    def _latest_replay_preparation_summary(self, strategy_evaluations: list[dict[str, Any]]) -> dict[str, Any]:
        matched: list[dict[str, Any]] = []
        for item in strategy_evaluations:
            raw = dict(item.get("raw_json", {}) or {})
            if str(raw.get("report_type", "") or "") != "replay_dataset_preparation":
                continue
            raw["evaluated_at"] = self._timestamp_to_iso(self._to_datetime(item.get("evaluated_at")))
            matched.append(raw)
        if not matched:
            return {}
        return max(
            matched,
            key=lambda row: self._to_datetime(row.get("evaluated_at")) or self._epoch(),
        )

    def _latest_signal_generation_diagnosis_summary(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if not hasattr(self, "_cached_latest_signal_generation_diagnosis"):
            self._cached_latest_signal_generation_diagnosis = {}
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_latest_signal_generation_diagnosis.get(cache_key)
        if cached is not None:
            return dict(cached)
        matched: list[dict[str, Any]] = []
        for item in self._strategy_evaluations(identity):
            raw = dict(item.get("raw_json", {}) or {})
            if str(raw.get("report_type", "") or "") != "signal_generation_diagnosis":
                continue
            raw["evaluated_at"] = self._timestamp_to_iso(self._to_datetime(item.get("evaluated_at")))
            matched.append(raw)
        if not matched:
            self._cached_latest_signal_generation_diagnosis[cache_key] = {}
            return {}
        latest = max(
            matched,
            key=lambda row: self._to_datetime(row.get("evaluated_at")) or self._epoch(),
        )
        self._cached_latest_signal_generation_diagnosis[cache_key] = dict(latest)
        return latest

    def _latest_historical_data_readiness_summary(
        self,
        strategy_evaluations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        matched: list[dict[str, Any]] = []
        for item in strategy_evaluations:
            raw = dict(item.get("raw_json", {}) or {})
            report_type = str(raw.get("report_type", "") or "")
            if report_type not in {
                "historical_crypto_1day_backfill_or_resample",
                "historical_crypto_15min_backfill_or_resample",
            }:
                continue
            row = dict(raw)
            row["evaluated_at"] = self._timestamp_to_iso(
                self._to_datetime(item.get("evaluated_at"))
            )
            row["symbols_covered_list"] = list(item.get("symbols_tested") or [])
            matched.append(row)
        if not matched:
            return {}
        return max(
            matched,
            key=lambda row: self._to_datetime(row.get("evaluated_at")) or self._epoch(),
        )

    def _data_gap_resolved_by_newer_readiness(
        self,
        *,
        data_adequacy: dict[str, Any],
        latest_data_readiness: dict[str, Any],
        latest_replay_preparation_timestamp: str,
    ) -> bool:
        zero_reason = str(data_adequacy.get("zero_decision_reason", "") or "")
        if zero_reason not in {"no_bars_for_timeframe", "insufficient_crypto_history"}:
            return False
        if str(latest_data_readiness.get("data_gap_resolved", "") or "") != "yes":
            return False
        readiness_dt = self._to_datetime(latest_data_readiness.get("evaluated_at"))
        replay_prep_dt = self._to_datetime(latest_replay_preparation_timestamp)
        if readiness_dt is None:
            return False
        if replay_prep_dt is not None and readiness_dt <= replay_prep_dt:
            return False
        return True


    def _crypto_15min_bars_available(self) -> bool:
        for row in self._definitions():
            if str(row.get("timeframe", "") or "") != "15Min":
                continue
            base_strategy_id = str(row.get("base_strategy_id", "") or "")
            if base_strategy_id.startswith("crypto_"):
                return True
        for row in self._latest_decisions():
            timeframe = str(row.get("timeframe", "") or "")
            strategy_id = str(row.get("strategy_id", "") or "")
            if timeframe == "15Min" and strategy_id.startswith("crypto_"):
                return True
        return False

    def _coalesce_int(self, *values: Any) -> int:
        for value in values:
            if value is None or value == "":
                continue
            return int(value or 0)
        return 0

    def _coalesce_float(self, *values: Any) -> float:
        for value in values:
            if value is None or value == "":
                continue
            return float(value or 0.0)
        return 0.0

    def _definitions(self) -> list[dict[str, Any]]:
        if getattr(self, "_cached_definitions", None) is None:
            self._cached_definitions = list(self.usage_ledger.list_strategy_variant_definitions())
        return list(self._cached_definitions)

    def _generated_candidate_pending(self, identity: _StrategyIdentity) -> bool:
        metadata = self._generated_candidate_metadata(identity)
        if not metadata:
            return False
        return str(metadata.get("evaluation_status", "") or "") == "pending"

    def _generated_candidate_metadata(self, identity: _StrategyIdentity) -> dict[str, Any]:
        for row in reversed(self._definitions()):
            if (
                str(row.get("base_strategy_id", "") or "") != identity.base_strategy_id
                or str(row.get("profile_id", "") or "") != identity.profile_id
                or str(row.get("timeframe", "") or "") != identity.timeframe
            ):
                continue
            params = dict(row.get("params_json", {}) or {})
            metadata = dict(params.get(_GENERATED_CANDIDATE_METADATA_KEY, {}) or {})
            if metadata or str(row.get("generation_reason", "") or "") == "research_expansion_candidate":
                notes_payload = self._variant_definition_notes_payload(row.get("notes"))
                if row.get("created_at") and not metadata.get("generated_at"):
                    metadata["generated_at"] = self._timestamp_to_iso(self._to_datetime(row.get("created_at")))
                if row.get("variant_id") and not metadata.get("candidate_id"):
                    metadata["candidate_id"] = str(row.get("variant_id", "") or "")
                metadata["evaluation_status"] = str(
                    row.get("evaluation_status", "")
                    or notes_payload.get("evaluation_status", "")
                    or metadata.get("evaluation_status", "")
                    or ""
                )
                metadata["generation_reason"] = str(row.get("generation_reason", "") or metadata.get("generation_reason", "") or "")
                for key in (
                    "lifecycle_status",
                    "research_status",
                    "runtime_status",
                    "runtime_blocker",
                    "variants_generated",
                    "variants_evaluated",
                    "baseline_sample_size",
                    "best_variant_sample_size",
                    "generated_candidate_evidence_at",
                ):
                    if notes_payload.get(key) not in (None, ""):
                        metadata[key] = notes_payload.get(key)
                return metadata
        return {}

    def _generated_candidate_lifecycle_status(
        self,
        *,
        identity: _StrategyIdentity,
        variant_report: dict[str, Any],
        latest_sample_size: int,
        latest_net: float,
        latest_planner_recommendation: str,
        latest_diagnosis_verdict: str,
        latest_autopilot_no_progress: dict[str, Any],
        latest_variant_evaluation_timestamp: str,
    ) -> str:
        metadata = self._generated_candidate_metadata(identity)
        if not metadata:
            return ""
        evaluation_status = str(metadata.get("evaluation_status", "") or "")
        persisted_lifecycle_status = str(metadata.get("lifecycle_status", "") or "")
        newer_variant_evidence = self._generated_candidate_has_newer_variant_evidence(
            metadata=metadata,
            latest_variant_evaluation_timestamp=latest_variant_evaluation_timestamp,
        )
        if persisted_lifecycle_status and (evaluation_status != "pending" or newer_variant_evidence):
            return persisted_lifecycle_status
        if evaluation_status == "pending" and not newer_variant_evidence:
            classification_reason = str(latest_autopilot_no_progress.get("classification_reason", "") or "")
            if classification_reason in {
                "generated_candidate_had_no_usable_samples",
                "generated_candidate_was_classified_deprioritised",
            }:
                return (
                    "insufficient_history_after_variant_research"
                    if classification_reason == "generated_candidate_had_no_usable_samples"
                    else "no_viable_signal_after_variant_research"
                )
            return "generated_not_evaluated"
        variants_generated = int(variant_report.get("variants_generated", 0) or 0)
        variants_evaluated = int(variant_report.get("variants_evaluated", 0) or 0)
        if variants_generated <= 0 and variants_evaluated <= 0:
            return "generated_not_evaluated"
        if variants_evaluated <= 0:
            return "variant_research_pending"
        baseline_sample_size = int(
            metadata.get("baseline_sample_size", variant_report.get("baseline_sample_size", 0)) or 0
        )
        best_variant_sample_size = int(
            metadata.get("best_variant_sample_size", variant_report.get("best_variant_sample_size", 0)) or 0
        )
        runtime_status = str(metadata.get("runtime_status", variant_report.get("runtime_status", "")) or "")
        if runtime_status == "runtime_blocked" or evaluation_status == "runtime_blocked":
            return "runtime_blocked"
        zero_sample_status = self._generated_zero_sample_research_status(variant_report)
        if zero_sample_status:
            return zero_sample_status
        if baseline_sample_size > 0 or best_variant_sample_size > 0:
            return "variant_research_completed"
        if not latest_diagnosis_verdict and not latest_planner_recommendation:
            return "variant_research_completed"
        if latest_sample_size <= 0:
            classification_reason = str(latest_autopilot_no_progress.get("classification_reason", "") or "")
            if classification_reason in {"insufficient_data_after_precompute", "generated_candidate_had_no_usable_samples"}:
                return "insufficient_data"
            if classification_reason in {"no_viable_signal_after_precompute", "generated_candidate_was_classified_deprioritised"}:
                return "no_viable_signal"
            return "diagnosis_pending"
        if latest_planner_recommendation == "retire_or_deprioritise_strategy" or latest_net <= 0.0:
            return "deprioritise_until_new_data"
        if latest_diagnosis_verdict:
            if latest_net > 0.0 and latest_sample_size >= 30:
                return "eligible_for_paper_candidate_audit"
            return "diagnosis_completed"
        return "diagnosis_pending"

    def _variant_definition_notes_payload(self, raw_notes: Any) -> dict[str, Any]:
        text = str(raw_notes or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _generated_candidate_has_newer_variant_evidence(
        self,
        *,
        metadata: dict[str, Any],
        latest_variant_evaluation_timestamp: str,
    ) -> bool:
        generated_at = self._to_datetime(metadata.get("generated_at"))
        latest_variant_at = self._to_datetime(
            metadata.get("generated_candidate_evidence_at") or latest_variant_evaluation_timestamp
        )
        if generated_at is None or latest_variant_at is None:
            return False
        return latest_variant_at >= generated_at

    def _latest_decisions(self) -> list[dict[str, Any]]:
        if getattr(self, "_cached_latest_decisions", None) is None:
            self._cached_latest_decisions = list(self.usage_ledger.list_latest_research_cycle_decisions())
        return list(self._cached_latest_decisions)

    def _promotion(self, identity: _StrategyIdentity) -> dict[str, Any]:
        if not hasattr(self, "_cached_promotions"):
            self._cached_promotions = {}
        key = (identity.base_strategy_id, identity.profile_id)
        if key not in self._cached_promotions:
            self._cached_promotions[key] = (
                self.usage_ledger.get_strategy_promotion(
                    strategy_id=identity.base_strategy_id,
                    profile_id=identity.profile_id,
                )
                or {}
            )
        return dict(self._cached_promotions[key])

    def _lightweight_strategy_plan(self, identity: _StrategyIdentity) -> dict[str, Any]:
        variant_report = self._safe_variant_report(identity)
        baseline_metrics = dict((variant_report.get("baseline", {}) or {}).get("metrics", {}) or {})
        variants = list(variant_report.get("variants", []) or [])
        best_variant = self._best_variant(variants) or {}
        sample_size = int(baseline_metrics.get("sample_size", 0) or 0)
        net = float(baseline_metrics.get("net_return_after_costs", 0.0) or 0.0)
        best_variant_id = str(best_variant.get("variant_id", "") or "")
        symbols_tested = list(best_variant.get("symbols_tested", []) or [])
        selected_symbol = str((symbols_tested[0] if symbols_tested else "") or "").upper()
        if sample_size <= 0:
            experiment = "insufficient_data_collect_more"
            reason = "No persisted baseline replay decisions were available, so the next safe move is to collect more research evidence."
        elif sample_size < 30 and net <= -0.5 and not bool(best_variant.get("beats_baseline")):
            experiment = "retire_or_deprioritise_strategy"
            reason = "Persisted replay evidence is already materially negative despite a thin sample, so this strategy should be deprioritised until fresh evidence changes the picture."
        elif sample_size < 30 or (bool(best_variant.get("beats_baseline")) and net > -0.25):
            experiment = "validate_symbol_subset_stability"
            reason = "Persisted replay evidence is promising but still thin, so the next safe step is to validate stability before any broader promotion decision."
        elif net <= 0.05 and not bool(best_variant.get("beats_baseline")):
            experiment = "retire_or_deprioritise_strategy"
            reason = "Persisted replay evidence remains weak, so this strategy should stay deprioritised until stronger evidence appears."
        else:
            experiment = "test_cost_expected_move_variants"
            reason = "Persisted replay evidence shows enough activity to justify the next bounded replay-only refinement."
        command = (
            ".venv-mac/bin/python main.py --strategy-research-planner "
            f"--base-strategy {identity.base_strategy_id} --profile-id {identity.profile_id} --timeframe {identity.timeframe}"
        )
        if experiment == "validate_symbol_subset_stability" and best_variant_id and selected_symbol:
            command = (
                ".venv-mac/bin/python main.py --symbol-subset-stability-report "
                f"--base-strategy {identity.base_strategy_id} --profile-id {identity.profile_id} "
                f"--timeframe {identity.timeframe} --variant-id {best_variant_id} --symbol {selected_symbol}"
            )
        report = {
            "selected_experiment_type": experiment,
            "proposed_next_command": command,
            "reason": reason,
        }
        if not hasattr(self, "_cached_strategy_plans"):
            self._cached_strategy_plans = {}
        self._cached_strategy_plans[(identity.base_strategy_id, identity.profile_id, identity.timeframe)] = dict(report)
        return report

    def _selected_candidate_should_skip_repeat_diagnosis(self, selected: dict[str, Any]) -> bool:
        if not selected:
            return False
        latest_sample_size = int(selected.get("latest_sample_size", 0) or 0)
        latest_net = float(selected.get("latest_net_return_after_costs", 0.0) or 0.0)
        latest_recommendation = str(selected.get("latest_planner_recommendation", "") or "")
        return (
            latest_sample_size > 0
            and latest_net <= -0.5
            and latest_recommendation == "retire_or_deprioritise_strategy"
        )

    def _paper_candidate_path_for_row(
        self,
        *,
        latest_sample_size: int,
        latest_net: float,
        win_rate: float,
        drawdown: Any,
    ) -> str:
        if latest_sample_size <= 0:
            return "insufficient_data"
        if self._materially_negative_evidence(
            latest_sample_size=latest_sample_size,
            latest_net=latest_net,
            win_rate=win_rate,
            drawdown=drawdown,
            paper_candidate_path="negative_replay_edge" if latest_net <= 0.0 else "",
        ):
            return "negative_replay_edge"
        if latest_net <= 0.0:
            return "negative_replay_edge"
        return "needs_more_research_before_paper_audit"

    def _materially_negative_evidence(
        self,
        *,
        latest_sample_size: int,
        latest_net: float,
        win_rate: float,
        drawdown: Any,
        paper_candidate_path: str,
    ) -> bool:
        drawdown_value = float(drawdown or 0.0)
        return bool(
            latest_sample_size > 0
            and (
                latest_net <= -0.5
                or win_rate <= 0.0
                or drawdown_value >= 3.0
                or paper_candidate_path == "negative_replay_edge"
            )
        )

    def _latest_autopilot_no_progress_summary(self, identity: _StrategyIdentity) -> dict[str, Any]:
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_latest_autopilot_no_progress.get(cache_key)
        if cached is not None:
            return dict(cached)
        matched: list[dict[str, Any]] = []
        for item in self._strategy_evaluations(identity):
            raw = dict(item.get("raw_json", {}) or {})
            if raw.get("report_type") != "research_autopilot_step_summary":
                continue
            classification_applied = str(raw.get("classification_applied", "") or "")
            classification_reason = str(raw.get("classification_reason", "") or "")
            if not (
                classification_applied in {"deprioritise_until_new_data", "deprioritise"}
                or classification_reason in {
                    "no_progress_after_research_step_with_negative_replay_edge",
                    "insufficient_data_after_precompute",
                    "no_viable_signal_after_precompute",
                }
                or classification_reason.startswith("precompute_completed_but_only_")
            ):
                if str(raw.get("step_advanced", "") or "") != "no":
                    continue
                if str(raw.get("evidence_changed", "") or "") != "no":
                    continue
                if str(raw.get("candidate_status_changed", "") or "") != "no":
                    continue
                if str(raw.get("before_candidate", "") or "") != str(raw.get("after_candidate", "") or ""):
                    continue
                if str(raw.get("before_action", "") or "") != str(raw.get("after_action", "") or ""):
                    continue
                classification_applied = "deprioritise_until_new_data"
                classification_reason = "no_progress_after_research_step_with_negative_replay_edge"
            raw["classification_applied"] = classification_applied
            raw["classification_reason"] = classification_reason
            raw["autopilot_classification_timestamp"] = (
                raw.get("recorded_at")
                or self._timestamp_to_iso(self._to_datetime(item.get("evaluated_at")))
                or ""
            )
            matched.append(raw)
        if matched:
            latest = max(
                matched,
                key=lambda item: self._to_datetime(item.get("autopilot_classification_timestamp"))
                or self._epoch(),
            )
            self._cached_latest_autopilot_no_progress[cache_key] = dict(latest)
            return latest
        self._cached_latest_autopilot_no_progress[cache_key] = {}
        return {}

    def _candidate_blocked_by_recent_autopilot_no_progress(self, item: dict[str, Any], *, ranked: list[dict[str, Any]]) -> bool:
        if not item:
            return False
        generated_lifecycle_status = str(item.get("generated_candidate_lifecycle_status", "") or "")
        if generated_lifecycle_status in {
            "generated_not_evaluated",
            "variant_research_pending",
            "diagnosis_pending",
        }:
            return False
        summary = dict(item.get("latest_autopilot_no_progress") or {})
        if not summary:
            return False
        classification_applied = str(summary.get("classification_applied", "") or "")
        classification_reason = str(summary.get("classification_reason", "") or "")
        if not (
            classification_applied in {"deprioritise_until_new_data", "deprioritise"}
            or classification_reason in {
                "no_progress_after_research_step_with_negative_replay_edge",
                "insufficient_data_after_precompute",
                "no_viable_signal_after_precompute",
            }
            or classification_reason.startswith("precompute_completed_but_only_")
        ):
            return False
        if not self._autopilot_exclusion_active(item):
            return False
        current_identity = self._autopilot_action_identity_for_item(item, ranked=ranked)
        persisted_identity = self._autopilot_action_identity_from_summary(summary)
        return persisted_identity == current_identity

    def _autopilot_exclusion_active(self, item: dict[str, Any]) -> bool:
        classification_dt = self._to_datetime(item.get("autopilot_classification_timestamp"))
        if classification_dt is None:
            return False
        latest_evidence_dt = self._to_datetime(item.get("latest_relevant_evidence_timestamp"))
        if latest_evidence_dt is None:
            latest_evidence_dt = self._to_datetime(
                ((item.get("generated_candidate_metadata", {}) or {}).get("generated_candidate_evidence_at"))
            )
        if latest_evidence_dt is None:
            return True
        return latest_evidence_dt <= classification_dt

    def _strategy_evaluations(self, identity: _StrategyIdentity) -> list[dict[str, Any]]:
        cache_key = (identity.base_strategy_id, identity.profile_id, identity.timeframe)
        cached = self._cached_strategy_evaluations.get(cache_key)
        if cached is not None:
            return [dict(item) for item in cached]
        rows = list(
            self.usage_ledger.list_strategy_variant_evaluations(
                base_strategy_id=identity.base_strategy_id,
                profile_id=identity.profile_id,
                timeframe=identity.timeframe,
                limit=200,
            )
        )
        self._cached_strategy_evaluations[cache_key] = [dict(item) for item in rows]
        return [dict(item) for item in rows]

    def _latest_strategy_evidence_timestamp(
        self,
        *,
        latest_cycle: dict[str, Any],
        strategy_evaluations: list[dict[str, Any]],
    ) -> str:
        cycle_dt = self._to_datetime(
            latest_cycle.get("evaluated_at")
            or latest_cycle.get("recorded_at")
            or (latest_cycle.get("raw_json", {}) or {}).get("latest_strategy_evidence_timestamp")
        )
        evaluation_dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: str(row.get("variant_id", "") or "") != "research-autopilot",
        )
        return self._timestamp_to_iso(max(filter(None, [cycle_dt, evaluation_dt]), default=None))

    def _latest_variant_evaluation_timestamp(self, strategy_evaluations: list[dict[str, Any]]) -> str:
        dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: (
                str(row.get("variant_id", "") or "") != "research-autopilot"
                and str((row.get("raw_json", {}) or {}).get("report_type", "") or "") != "symbol_subset_stability"
            ),
        )
        return self._timestamp_to_iso(dt)

    def _latest_diagnosis_timestamp(self, strategy_evaluations: list[dict[str, Any]]) -> str:
        dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: str((row.get("raw_json", {}) or {}).get("report_type", "") or "") in {
                "strategy_loss_diagnosis",
                "diagnose_next_best_strategy",
            },
        )
        return self._timestamp_to_iso(dt)

    def _latest_symbol_stability_timestamp(self, strategy_evaluations: list[dict[str, Any]]) -> str:
        dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: str((row.get("raw_json", {}) or {}).get("report_type", "") or "") == "symbol_subset_stability",
        )
        return self._timestamp_to_iso(dt)

    def _latest_replay_evidence_timestamp(self, strategy_evaluations: list[dict[str, Any]]) -> str:
        dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: str((row.get("raw_json", {}) or {}).get("report_type", "") or "") == "symbol_replay_evidence_plan",
        )
        return self._timestamp_to_iso(dt)

    def _latest_replay_preparation_timestamp(self, strategy_evaluations: list[dict[str, Any]]) -> str:
        dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: str((row.get("raw_json", {}) or {}).get("report_type", "") or "") == "replay_dataset_preparation",
        )
        return self._timestamp_to_iso(dt)

    def _latest_data_backfill_timestamp(
        self,
        *,
        latest_cycle: dict[str, Any],
        strategy_evaluations: list[dict[str, Any]],
    ) -> str:
        cycle_raw = dict(latest_cycle.get("raw_json", {}) or {})
        cycle_dt = self._to_datetime(cycle_raw.get("latest_data_backfill_timestamp"))
        evaluation_dt = self._max_evaluated_at(
            strategy_evaluations,
            include=lambda row: "backfill" in str((row.get("raw_json", {}) or {}).get("report_type", "") or "").lower(),
        )
        return self._timestamp_to_iso(max(filter(None, [cycle_dt, evaluation_dt]), default=None))

    def _latest_relevant_evidence_timestamp(
        self,
        *,
        latest_strategy_evidence_timestamp: str,
        latest_variant_evaluation_timestamp: str,
        latest_diagnosis_timestamp: str,
        latest_symbol_stability_timestamp: str,
        latest_replay_evidence_timestamp: str,
        latest_replay_preparation_timestamp: str,
        latest_signal_generation_diagnosis_timestamp: str,
        latest_data_backfill_timestamp: str,
    ) -> str:
        dt = max(
            filter(
                None,
                [
                    self._to_datetime(latest_strategy_evidence_timestamp),
                    self._to_datetime(latest_variant_evaluation_timestamp),
                    self._to_datetime(latest_diagnosis_timestamp),
                    self._to_datetime(latest_symbol_stability_timestamp),
                    self._to_datetime(latest_replay_evidence_timestamp),
                    self._to_datetime(latest_replay_preparation_timestamp),
                    self._to_datetime(latest_signal_generation_diagnosis_timestamp),
                    self._to_datetime(latest_data_backfill_timestamp),
                ],
            ),
            default=None,
        )
        return self._timestamp_to_iso(dt)

    def _autopilot_action_identity_for_item(self, item: dict[str, Any], *, ranked: list[dict[str, Any]]) -> _AutopilotActionIdentity:
        action_type = self._next_portfolio_action(item, ranked)
        command_text = self._proposed_next_command(item, ranked)
        return _AutopilotActionIdentity(
            base_strategy_id=str(item.get("base_strategy_id", "") or ""),
            profile_id=str(item.get("profile_id", "") or ""),
            timeframe=str(item.get("timeframe", "") or ""),
            variant_id=self._command_flag_value(command_text, "--variant-id"),
            action_type=action_type,
            command_type=self._command_type(command_text),
        )

    def _autopilot_action_identity_from_summary(self, summary: dict[str, Any]) -> _AutopilotActionIdentity:
        identity = dict(summary.get("after_action_identity") or summary.get("before_action_identity") or {})
        if identity:
            return _AutopilotActionIdentity(
                base_strategy_id=str(identity.get("base_strategy_id", "") or ""),
                profile_id=str(identity.get("profile_id", "") or ""),
                timeframe=str(identity.get("timeframe", "") or ""),
                variant_id=str(identity.get("variant_id", "") or ""),
                action_type=str(identity.get("action_type", "") or ""),
                command_type=str(identity.get("command_type", "") or ""),
            )
        return _AutopilotActionIdentity(
            base_strategy_id=str(summary.get("base_strategy_id", "") or self._identity_part(summary.get("after_candidate"), 0)),
            profile_id=str(summary.get("profile_id", "") or self._identity_part(summary.get("after_candidate"), 1)),
            timeframe=str(summary.get("timeframe", "") or self._identity_part(summary.get("after_candidate"), 2)),
            variant_id=self._command_flag_value(str(summary.get("after_command", "") or ""), "--variant-id"),
            action_type=str(summary.get("after_action", "") or ""),
            command_type=self._command_type(str(summary.get("after_command", "") or "")),
        )

    def _identity_part(self, value: Any, index: int) -> str:
        parts = str(value or "").split("/")
        if index >= len(parts):
            return ""
        return str(parts[index] or "")

    def _command_type(self, command_text: str) -> str:
        argv = str(command_text or "").split()
        for token in argv:
            if token.startswith("--"):
                return token.removeprefix("--")
        return ""

    def _command_flag_value(self, command_text: str, flag: str) -> str:
        argv = str(command_text or "").split()
        if flag not in argv:
            return ""
        index = argv.index(flag)
        if index + 1 >= len(argv):
            return ""
        return str(argv[index + 1] or "")

    def _max_evaluated_at(
        self,
        rows: list[dict[str, Any]],
        *,
        include: Any,
    ) -> datetime | None:
        matched: list[datetime] = []
        for row in rows:
            if not include(row):
                continue
            evaluated_at = self._to_datetime(row.get("evaluated_at"))
            if evaluated_at is not None:
                matched.append(evaluated_at)
        return max(matched) if matched else None

    def _to_datetime(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.astimezone()
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _timestamp_to_iso(self, value: datetime | None) -> str:
        return value.isoformat() if isinstance(value, datetime) else ""

    def _epoch(self) -> datetime:
        return datetime.fromtimestamp(0).astimezone()

    def _summary_identity(self, summary: dict[str, Any] | None) -> str:
        item = dict(summary or {})
        base = str(item.get("base_strategy_id", "") or "")
        profile = str(item.get("profile_id", "") or "")
        timeframe = str(item.get("timeframe", "") or "")
        return f"{base}/{profile}/{timeframe}" if any((base, profile, timeframe)) else ""

    def _clear_runtime_caches(self) -> None:
        self._cached_variant_reports = {}
        self._cached_loss_reports = {}
        self._cached_strategy_plans = {}
        self._cached_audit_reports = {}
        self._cached_wide_stability = {}
        self._cached_strategy_evaluations = {}
        self._cached_latest_autopilot_no_progress = {}
