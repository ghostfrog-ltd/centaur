from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport
from app.framework.reporting.strategy_variant_research import (
    StrategyVariantDiagnosticsReport,
    StrategyVariantResearchReport,
)
from app.framework.reporting.symbol_subset_stability import SymbolSubsetStabilityReport
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


ALLOWED_EXPERIMENT_TYPES = {
    "test_holding_window_variants",
    "diagnose_symbol_regime_subset",
    "validate_symbol_subset_stability",
    "test_symbol_filter_variants",
    "test_target_multiple_variants",
    "test_stop_loss_variants",
    "test_cost_expected_move_variants",
    "retire_or_deprioritise_strategy",
    "insufficient_data_collect_more",
}

SAFETY_STATEMENT = "Research-only planner. No paper or live approval has been changed."


@dataclass(frozen=True)
class _ProposedStep:
    experiment_type: str
    reason: str
    proposed_next_command: str
    execution_mode: str
    execution_available: bool


class StrategyResearchPlannerReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.variant_reporter = StrategyVariantResearchReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.variant_diagnostics_reporter = StrategyVariantDiagnosticsReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.loss_reporter = StrategyLossDiagnosisReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.symbol_stability_reporter = SymbolSubsetStabilityReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        execute_next_research_step: bool = False,
    ) -> dict[str, Any]:
        variant_report = self.variant_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        diagnostics_report = self.variant_diagnostics_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        baseline_loss_report = self.loss_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        selected_variant = self._selected_variant(variant_report)
        selected_variant_id = str((selected_variant or {}).get("variant_id", "") or "")
        selected_variant_loss_report = None
        if selected_variant_id:
            selected_variant_loss_report = self.loss_reporter.build_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=selected_variant_id,
            )
        proposal = self._choose_next_step(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_report=variant_report,
            diagnostics_report=diagnostics_report,
            baseline_loss_report=baseline_loss_report,
            selected_variant=selected_variant,
            selected_variant_loss_report=selected_variant_loss_report,
        )
        execution = self._maybe_execute(
            proposal=proposal,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            selected_variant_id=selected_variant_id,
            execute_next_research_step=execute_next_research_step,
        )
        report = {
            "title": "Strategy Research Planner",
            "selected_experiment_type": proposal.experiment_type,
            "selected_base_strategy": base_strategy_id,
            "selected_variant_id": selected_variant_id or None,
            "reason": proposal.reason,
            "evidence_used": self._evidence_used(
                variant_report=variant_report,
                diagnostics_report=diagnostics_report,
                baseline_loss_report=baseline_loss_report,
                selected_variant=selected_variant,
                selected_variant_loss_report=selected_variant_loss_report,
            ),
            "candidate_symbols": self._candidate_symbols(selected_variant_loss_report),
            "proposed_next_command": proposal.proposed_next_command,
            "execution_mode": proposal.execution_mode,
            "execution_available": proposal.execution_available,
            "execution": execution,
            "safety_statement": SAFETY_STATEMENT,
        }
        if report["selected_experiment_type"] not in ALLOWED_EXPERIMENT_TYPES:
            raise ValueError(f"Unsupported experiment type selected: {report['selected_experiment_type']}")
        return report

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        execute_next_research_step: bool = False,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            execute_next_research_step=execute_next_research_step,
        )
        evidence = dict(report.get("evidence_used", {}) or {})
        lines = [
            str(report.get("title", "Strategy Research Planner")),
            f"selected_experiment_type={report.get('selected_experiment_type', '-')}",
            f"selected_base_strategy={report.get('selected_base_strategy', '-')}",
            f"selected_variant_id={report.get('selected_variant_id') or '-'}",
            f"reason={report.get('reason', '-')}",
            (
                "evidence_used="
                f"loss_diagnosis_verdict={evidence.get('loss_diagnosis_verdict', '-')}"
                f" | profitability_verdict={evidence.get('profitability_verdict', '-')}"
                f" | exit_verdict={evidence.get('exit_verdict', '-')}"
                f" | best_variant_vs_baseline={evidence.get('best_variant_vs_baseline', '-')}"
                f" | any_variant_beat_thresholds={'yes' if evidence.get('any_variant_beat_thresholds') else 'no'}"
            ),
            f"candidate_symbols={report.get('candidate_symbols', [])}",
            f"proposed_next_command={report.get('proposed_next_command', '-')}",
            f"execution_available={'yes' if report.get('execution_available') else 'no'}",
            f"execution_status={dict(report.get('execution', {}) or {}).get('status', '-')}",
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def _selected_variant(self, variant_report: dict[str, Any]) -> dict[str, Any] | None:
        variants = list(variant_report.get("variants", []) or [])
        baseline_variant_id = str(((variant_report.get("baseline", {}) or {}).get("variant_id", "")) or "")
        non_baseline = [
            item
            for item in variants
            if str(item.get("variant_id", "") or "") and str(item.get("variant_id", "") or "") != baseline_variant_id
        ]
        if not non_baseline:
            return None
        return max(
            non_baseline,
            key=lambda item: (
                bool(item.get("beats_baseline")),
                float(item.get("net_return_after_costs", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                -float(item.get("drawdown", 0.0) or 0.0),
            ),
        )

    def _choose_next_step(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_report: dict[str, Any],
        diagnostics_report: dict[str, Any],
        baseline_loss_report: dict[str, Any],
        selected_variant: dict[str, Any] | None,
        selected_variant_loss_report: dict[str, Any] | None,
    ) -> _ProposedStep:
        evidence = self._evidence_used(
            variant_report=variant_report,
            diagnostics_report=diagnostics_report,
            baseline_loss_report=baseline_loss_report,
            selected_variant=selected_variant,
            selected_variant_loss_report=selected_variant_loss_report,
        )
        best_variant_vs_baseline = str(evidence.get("best_variant_vs_baseline", "no_improving_variant") or "")
        any_variant_beat_thresholds = bool(evidence.get("any_variant_beat_thresholds"))
        exit_verdict = str(evidence.get("exit_verdict", "") or "")
        profitability_verdict = str(evidence.get("profitability_verdict", "") or "")
        loss_verdict = str(evidence.get("loss_diagnosis_verdict", "") or "")
        subset_verdict = str(evidence.get("subset_edge_verdict", "") or "")
        selected_variant_id = str(((selected_variant or {}).get("variant_id", "")) or "")
        holding_variants_exist = self._holding_variants_exist(diagnostics_report)
        selected_variant_net = float(((selected_variant or {}).get("net_return_after_costs", 0.0)) or 0.0)
        if int(evidence.get("baseline_sample_size", 0) or 0) <= 0:
            return _ProposedStep(
                experiment_type="insufficient_data_collect_more",
                reason="No persisted baseline replay decisions were available, so the next safe move is to collect more research evidence before selecting a new test.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --strategy-variant-research-report "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="read_only_only",
                execution_available=True,
            )
        if exit_verdict == "holding_window_too_short" and not holding_variants_exist:
            return _ProposedStep(
                experiment_type="test_holding_window_variants",
                reason="Exit diagnostics say the current holding window is too short and no persisted holding-window variants exist yet, so the next research step is to generate those variants.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --run-strategy-variant-research "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if subset_verdict == "symbol_filter_promising" and selected_variant_id:
            candidate_symbols = self._candidate_symbols(selected_variant_loss_report)
            symbol = str(((candidate_symbols[0] if candidate_symbols else {}).get("symbol", "")) or "")
            symbol_clause = f" --symbol {symbol}" if symbol else ""
            return _ProposedStep(
                experiment_type="validate_symbol_subset_stability",
                reason=(
                    "Targeted subset diagnosis already found a promising symbol pocket, but the edge still needs month-to-month stability validation "
                    "before any filter is added because the broader stop/cost economics remain weak and most other top symbols were tiny-sample noise."
                ),
                proposed_next_command=(
                    f".venv-mac/bin/python main.py --symbol-subset-stability-report --base-strategy {base_strategy_id} "
                    f"--profile-id {profile_id} --timeframe {timeframe} --variant-id {selected_variant_id}{symbol_clause}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if (
            best_variant_vs_baseline == "beats_baseline"
            and not any_variant_beat_thresholds
            and selected_variant_id
            and self._variant_has_holding_window_override(selected_variant)
            and selected_variant_net < 0.0
        ):
            return _ProposedStep(
                experiment_type="diagnose_symbol_regime_subset",
                reason="A holding-window variant improved on baseline but still stayed negative after costs, so the next useful question is whether that less-bad variant has a symbol or regime subset edge worth isolating.",
                proposed_next_command=(
                    f".venv-mac/bin/python main.py --strategy-loss-diagnosis --base-strategy {base_strategy_id} "
                    f"--profile-id {profile_id} --timeframe {timeframe} --variant-id {selected_variant_id}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if profitability_verdict in {"costs_dominate_small_edge", "winner_size_too_small"} or loss_verdict in {"snapback_cost_problem", "cost_problem"}:
            return _ProposedStep(
                experiment_type="test_cost_expected_move_variants",
                reason="The latest diagnostics point to cost drag or winner size being too weak, so the next research step is to retest cost-aware expected-move filters.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --run-strategy-variant-research "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if subset_verdict in {
            "symbol_filter_promising",
            "trade_count_filter_promising",
            "pullback_depth_filter_promising",
            "score_filter_promising",
            "regime_filter_promising",
        }:
            return _ProposedStep(
                experiment_type="test_symbol_filter_variants",
                reason="Subset diagnostics already point to a potentially stable symbol, bucket, or regime pocket, so the next research step is to validate filter variants around that subset instead of changing promotion or execution rules.",
                proposed_next_command="app.framework.reporting.strategy_loss_diagnosis.StrategyLossDiagnosisReport.build_report",
                execution_mode="function_only",
                execution_available=False,
            )
        if exit_verdict == "target_too_far":
            return _ProposedStep(
                experiment_type="test_target_multiple_variants",
                reason="Time exits remain too far from the configured target, so the next research step is to retest target multiples rather than touch paper or live behavior.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --run-strategy-variant-research "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if exit_verdict == "stop_too_tight":
            return _ProposedStep(
                experiment_type="test_stop_loss_variants",
                reason="Exit diagnostics say stops are too damaging relative to target hits, so the next research step is to compare conservative stop-loss variants in replay only.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --run-strategy-variant-research "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="research_command_available",
                execution_available=True,
            )
        if (
            best_variant_vs_baseline in {"no_improving_variant", "does_not_beat_baseline"}
            and not any_variant_beat_thresholds
            and loss_verdict in {"snapback_no_edge_detected", "snapback_entry_quality_problem", "no_edge_detected", "entry_quality_problem"}
            and subset_verdict in {"no_clear_subset_edge", "insufficient_subset_data"}
        ):
            return _ProposedStep(
                experiment_type="retire_or_deprioritise_strategy",
                reason="No persisted variant or bucket meaningfully improves on baseline and no threshold-beating edge is present, so the safest next step is to retire or deprioritise this strategy in research.",
                proposed_next_command=(
                    ".venv-mac/bin/python main.py --strategy-loss-diagnosis "
                    f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
                ),
                execution_mode="read_only_only",
                execution_available=True,
            )
        return _ProposedStep(
            experiment_type="insufficient_data_collect_more",
            reason="The current research evidence does not support a stronger next experiment choice without overreaching, so the safe default is to collect more replay evidence.",
            proposed_next_command=(
                ".venv-mac/bin/python main.py --strategy-variant-research-report "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
            ),
            execution_mode="read_only_only",
            execution_available=True,
        )

    def _maybe_execute(
        self,
        *,
        proposal: _ProposedStep,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        selected_variant_id: str,
        execute_next_research_step: bool,
    ) -> dict[str, Any]:
        if not execute_next_research_step:
            return {
                "status": "not_requested",
                "executed_command": None,
            }
        if not proposal.execution_available:
            return {
                "status": "refused_not_implemented",
                "executed_command": None,
                "message": "Next research-only command is not implemented yet; refusing safely without any paper or live action.",
            }
        if proposal.experiment_type == "diagnose_symbol_regime_subset" and selected_variant_id:
            rendered = self.loss_reporter.render(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=selected_variant_id,
            )
            return {
                "status": "executed_research_only",
                "executed_command": proposal.proposed_next_command,
                "output_preview": rendered,
            }
        if proposal.experiment_type == "validate_symbol_subset_stability" and selected_variant_id:
            candidate_symbols = self._candidate_symbols(
                self.loss_reporter.build_report(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                    variant_id=selected_variant_id,
                )
            )
            symbol = str(((candidate_symbols[0] if candidate_symbols else {}).get("symbol", "")) or "")
            rendered = self.symbol_stability_reporter.render(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=selected_variant_id,
                symbol=symbol,
            )
            return {
                "status": "executed_research_only",
                "executed_command": proposal.proposed_next_command,
                "output_preview": rendered,
            }
        if proposal.experiment_type in {
            "test_holding_window_variants",
            "test_target_multiple_variants",
            "test_stop_loss_variants",
            "test_cost_expected_move_variants",
        }:
            result = self.variant_reporter.service.run_research(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                created_by="strategy_research_planner",
                bounded_diagnosis=True,
            )
            return {
                "status": "executed_research_only",
                "executed_command": proposal.proposed_next_command,
                "result_summary": {
                    "variants_generated": int(result.get("variants_generated", 0) or 0),
                    "evaluations_persisted": len(list(result.get("evaluations", []) or [])),
                },
            }
        return {
            "status": "not_executed_no_matching_research_command",
            "executed_command": None,
        }

    def _evidence_used(
        self,
        *,
        variant_report: dict[str, Any],
        diagnostics_report: dict[str, Any],
        baseline_loss_report: dict[str, Any],
        selected_variant: dict[str, Any] | None,
        selected_variant_loss_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        baseline_metrics = dict((variant_report.get("baseline", {}) or {}).get("metrics", {}) or {})
        selected_variant = dict(selected_variant or {})
        selected_variant_loss_report = dict(selected_variant_loss_report or {})
        best_variant_vs_baseline = "no_improving_variant"
        if selected_variant:
            best_variant_vs_baseline = "beats_baseline" if bool(selected_variant.get("beats_baseline")) else "does_not_beat_baseline"
        return {
            "loss_diagnosis_verdict": str(baseline_loss_report.get("verdict", "") or ""),
            "profitability_verdict": str(
                ((baseline_loss_report.get("profitability_requirement_diagnosis", {}) or {}).get("profitability_verdict", "")) or ""
            ),
            "exit_verdict": str(
                ((baseline_loss_report.get("time_exit_and_target_achievement_diagnosis", {}) or {}).get("exit_verdict", "")) or ""
            ),
            "best_variant_vs_baseline": best_variant_vs_baseline,
            "any_variant_beat_thresholds": any(
                bool(item.get("beats_thresholds")) for item in list(variant_report.get("variants", []) or [])
            ),
            "baseline_variant_id": str(((variant_report.get("baseline", {}) or {}).get("variant_id", "")) or ""),
            "baseline_net_return_after_costs": float(baseline_metrics.get("net_return_after_costs", 0.0) or 0.0),
            "baseline_sample_size": int(baseline_metrics.get("sample_size", 0) or 0),
            "baseline_data_adequacy": dict((variant_report.get("baseline", {}) or {}).get("data_adequacy", {}) or {}),
            "zero_decision_reason": str(
                (((variant_report.get("baseline", {}) or {}).get("data_adequacy", {}) or {}).get("zero_decision_reason", "")) or ""
            ),
            "selected_variant_generation_reason": str(selected_variant.get("generation_reason", "") or self._generation_reason(selected_variant, diagnostics_report)),
            "selected_variant_net_return_after_costs": float(selected_variant.get("net_return_after_costs", 0.0) or 0.0),
            "selected_variant_win_rate": float(selected_variant.get("win_rate", 0.0) or 0.0),
            "selected_variant_beats_thresholds": bool(selected_variant.get("beats_thresholds")),
            "subset_edge_verdict": str(
                ((selected_variant_loss_report.get("subset_edge_diagnosis", {}) or {}).get("verdict", "")) or ""
            ),
        }

    def _candidate_symbols(self, selected_variant_loss_report: dict[str, Any] | None) -> list[dict[str, Any]]:
        report = dict(selected_variant_loss_report or {})
        subset = dict(report.get("subset_edge_diagnosis", {}) or {})
        if str(subset.get("verdict", "") or "") != "symbol_filter_promising":
            return []
        candidates = []
        for item in list(((report.get("symbol_breakdown", {}) or {}).get("symbols_with_enough_sample", []) or [])):
            if float(item.get("net_return_after_costs", 0.0) or 0.0) <= 0.0:
                continue
            candidates.append(
                {
                    "symbol": str(item.get("symbol", "") or ""),
                    "sample_size": int(item.get("sample_size", 0) or 0),
                    "net_return_after_costs": float(item.get("net_return_after_costs", 0.0) or 0.0),
                    "win_rate": float(item.get("win_rate", 0.0) or 0.0),
                    "target_hit_count": int(item.get("target_hit_count", 0) or 0),
                    "stop_hit_count": int(item.get("stop_hit_count", 0) or 0),
                    "time_exit_count": int(item.get("time_exit_count", 0) or 0),
                }
            )
        return sorted(
            candidates,
            key=lambda item: (
                item["net_return_after_costs"],
                item["win_rate"],
                item["sample_size"],
            ),
            reverse=True,
        )

    def _holding_variants_exist(self, diagnostics_report: dict[str, Any]) -> bool:
        for row in list(diagnostics_report.get("rows", []) or []):
            params = dict(row.get("params_json", {}) or {})
            if int(params.get("holding_window_minutes", 0) or 0) > 0:
                return True
        return False

    def _variant_has_holding_window_override(self, selected_variant: dict[str, Any] | None) -> bool:
        params = dict((selected_variant or {}).get("params_json", {}) or {})
        return int(params.get("holding_window_minutes", 0) or 0) > 0

    def _generation_reason(self, selected_variant: dict[str, Any], diagnostics_report: dict[str, Any]) -> str:
        selected_variant_id = str(selected_variant.get("variant_id", "") or "")
        for row in list(diagnostics_report.get("rows", []) or []):
            if str(row.get("variant_id", "") or "") == selected_variant_id:
                return str(row.get("generation_reason", "") or "")
        return ""
