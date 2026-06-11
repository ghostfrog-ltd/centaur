from __future__ import annotations

from typing import Any

from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class GeneratedCandidateStateReport:
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
        self.planner = StrategyPortfolioResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
            operator_mode=True,
        )

    def build_report(self) -> dict[str, Any]:
        planner_report = self.planner.build_report()
        rows: list[dict[str, Any]] = []
        for item in list(planner_report.get("ranked_strategies", []) or []):
            metadata = dict(item.get("generated_candidate_metadata") or {})
            if not metadata:
                continue
            zero_sample = dict(item.get("generated_candidate_zero_sample_outcome") or {})
            latest_no_progress = dict(item.get("latest_autopilot_no_progress") or {})
            diagnosis_reason = self.planner._generated_candidate_ineligible_reason(item)  # noqa: SLF001
            excluded = bool(
                zero_sample
                or str(item.get("research_status", "") or "") in {
                    "deprioritise",
                    "deprioritise_until_new_data",
                    "no_viable_signal_after_variant_research",
                    "insufficient_history_after_variant_research",
                    "retire_candidate",
                }
            )
            eligible = self.planner._is_actionable_research_candidate(  # noqa: SLF001
                item,
                blocked_or_parked_candidate={},
                ranked=list(planner_report.get("ranked_strategies", []) or []),
            )
            baseline_sample_size = int(
                metadata.get("baseline_sample_size", zero_sample.get("baseline_sample_size", 0)) or 0
            )
            best_variant_sample_size = int(
                metadata.get("best_variant_sample_size", zero_sample.get("best_variant_sample_size", 0)) or 0
            )
            exclusion_reason = str(
                zero_sample.get("reason", "")
                or latest_no_progress.get("classification_reason", "")
                or ""
            )
            rows.append(
                {
                    "candidate": self.planner._summary_identity(item),  # noqa: SLF001
                    "candidate_id": str(metadata.get("candidate_id", "") or ""),
                    "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
                    "profile_id": str(item.get("profile_id", "") or ""),
                    "timeframe": str(item.get("timeframe", "") or ""),
                    "generated_at": str(metadata.get("generated_at", "") or ""),
                    "lifecycle_status": str(item.get("generated_candidate_lifecycle_status", "") or ""),
                    "evaluation_status": str(metadata.get("evaluation_status", "") or ""),
                    "baseline_sample_size": baseline_sample_size,
                    "best_variant_sample_size": best_variant_sample_size,
                    "terminal_status": str(zero_sample.get("research_status", "") or ""),
                    "terminal_reason": str(zero_sample.get("reason", "") or ""),
                    "research_status": str(item.get("research_status", "") or ""),
                    "generated_candidate_evidence_at": str(metadata.get("generated_candidate_evidence_at", "") or ""),
                    "latest_variant_evidence_at": str(item.get("latest_variant_evaluation_timestamp", "") or ""),
                    "latest_diagnosis_at": str(item.get("latest_diagnosis_timestamp", "") or ""),
                    "eligible_for_diagnosis": "yes" if not diagnosis_reason else "no",
                    "excluded_from_planner": "yes" if excluded else "no",
                    "exclusion_reason": exclusion_reason if excluded else "",
                    "eligible_for_portfolio_selection": "yes" if eligible else "no",
                    "reason_if_not_eligible": (
                        ""
                        if eligible
                        else str(
                            diagnosis_reason
                            or zero_sample.get("reason", "")
                            or latest_no_progress.get("classification_reason", "")
                            or item.get("research_status", "")
                            or "not_actionable_under_current_portfolio_filters"
                        )
                    ),
                    "reason_if_not_diagnosis_eligible": diagnosis_reason,
                }
            )
        return {
            "title": "Generated Candidate State Report",
            "generated_candidates": rows,
            "portfolio_research_status": str(planner_report.get("portfolio_research_status", "") or ""),
            "research_universe_status": str(planner_report.get("research_universe_status", "") or ""),
            "next_actionable_research_candidate": self.planner._summary_identity(  # noqa: SLF001
                planner_report.get("next_actionable_research_candidate")
            ),
            "next_actionable_research_command": str(planner_report.get("next_actionable_research_command", "") or ""),
            "next_portfolio_action": str(planner_report.get("next_portfolio_action", "") or ""),
        }

    def render(self) -> str:
        report = self.build_report()
        lines = [
            str(report.get("title", "Generated Candidate State Report")),
            f"portfolio_research_status={report.get('portfolio_research_status', '') or ''}",
            f"research_universe_status={report.get('research_universe_status', '') or ''}",
            f"next_actionable_research_candidate={report.get('next_actionable_research_candidate', '') or ''}",
            f"next_actionable_research_command={report.get('next_actionable_research_command', '') or ''}",
            f"next_portfolio_action={report.get('next_portfolio_action', '') or ''}",
        ]
        for row in list(report.get("generated_candidates", []) or []):
            lines.extend(
                [
                    f"generated_candidate={row.get('candidate', '')}",
                    f"candidate_id={row.get('candidate_id', '')}",
                    f"base_strategy_id={row.get('base_strategy_id', '')}",
                    f"profile_id={row.get('profile_id', '')}",
                    f"timeframe={row.get('timeframe', '')}",
                    f"generated_at={row.get('generated_at', '')}",
                    f"lifecycle_status={row.get('lifecycle_status', '')}",
                    f"evaluation_status={row.get('evaluation_status', '')}",
                    f"baseline_sample_size={row.get('baseline_sample_size', '')}",
                    f"best_variant_sample_size={row.get('best_variant_sample_size', '')}",
                    f"terminal_status={row.get('terminal_status', '')}",
                    f"terminal_reason={row.get('terminal_reason', '')}",
                    f"research_status={row.get('research_status', '')}",
                    f"generated_candidate_evidence_at={row.get('generated_candidate_evidence_at', '')}",
                    f"latest_variant_evidence_at={row.get('latest_variant_evidence_at', '')}",
                    f"latest_diagnosis_at={row.get('latest_diagnosis_at', '')}",
                    f"eligible_for_diagnosis={row.get('eligible_for_diagnosis', '')}",
                    f"excluded_from_planner={row.get('excluded_from_planner', '')}",
                    f"exclusion_reason={row.get('exclusion_reason', '')}",
                    f"eligible_for_portfolio_selection={row.get('eligible_for_portfolio_selection', '')}",
                    f"reason_if_not_eligible={row.get('reason_if_not_eligible', '')}",
                    f"reason_if_not_diagnosis_eligible={row.get('reason_if_not_diagnosis_eligible', '')}",
                ]
            )
        return "\n".join(lines)
