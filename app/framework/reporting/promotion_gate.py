from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.runtime.attention_alerts import approval_request_id
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.base import StrategyProfile
from app.framework.strategies.registry import build_strategy_registry

PROMOTION_STAGES = (
    "research_only",
    "promising_research",
    "paper_sim_candidate",
    "paper_sim_active",
    "paper_candidate",
    "paper_removal_candidate",
    "paper_approved",
    "rejected",
    "live_candidate",
    "live_approved",
)


@dataclass(frozen=True, slots=True)
class PromotionApproval:
    strategy_id: str
    profile_id: str
    stage: str
    paper_approved: bool
    live_approved: bool
    max_paper_notional_usd: float
    max_open_trades: int
    cooldown_minutes: int
    paper_execution_profile: bool
    research_only_profile: bool


class PromotionGateReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_status(self) -> dict[str, Any]:
        records = self.usage_ledger.list_strategy_promotions()
        return {
            "status": "ok",
            "records": records,
        }

    def evaluate(
        self,
        *,
        strategy_id: str | None = None,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        target_strategy_id = str(strategy_id or "").strip()
        target_profile_id = str(profile_id or "").strip()
        profile = self._resolve_profile(
            strategy_id=target_strategy_id,
            profile_id=target_profile_id,
        )
        from app.framework.reporting.proposal_pipeline_diagnostics import (
            ProposalPipelineDiagnosticsReport,
        )
        from app.framework.reporting.research_status import ResearchStatusReport

        research_report = ResearchStatusReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        ).build_report()
        diagnostics = ProposalPipelineDiagnosticsReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        ).build_report()
        promotion = self.usage_ledger.get_strategy_promotion(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
        )
        research_entry = self._latest_research_entry(
            report=research_report,
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
        )
        fitness = self.usage_ledger.get_latest_strategy_fitness_summary(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
        )
        proposal_strategy = self._diagnostic_strategy(
            diagnostics=diagnostics,
            strategy_id=profile.strategy_id,
        )
        replay_summary = {
            "classification": str(research_entry.get("classification", "research_only")),
            "recommendation": str(
                research_entry.get("promotion_recommendation", "gather_more_research")
            ),
            "net_return_after_costs_pct": float(
                research_entry.get("net_performance_pct", 0.0) or 0.0
            ),
            "win_rate": float(research_entry.get("net_win_rate", 0.0) or 0.0),
            "sample_size": int(research_entry.get("proposal_count", 0) or 0),
            "windows_with_data": int(research_entry.get("replay_windows_with_data", 0) or 0),
            "windows_required": int(research_entry.get("replay_windows_required", 0) or 0),
        }
        paper_sim_summary = {
            "composite_fitness_score": float(fitness.get("composite_fitness_score", 0.0) or 0.0)
            if fitness
            else 0.0,
            "net_return_after_costs_pct": float(fitness.get("avg_realized_return_pct", 0.0) or 0.0)
            if fitness
            else 0.0,
            "win_rate": float(fitness.get("win_rate", 0.0) or 0.0) if fitness else 0.0,
            "sample_size": int(fitness.get("evaluated_proposals", 0) or 0) if fitness else 0,
            "adverse_excursion_pct": float(
                fitness.get("avg_max_adverse_excursion_pct", 0.0) or 0.0
            )
            if fitness
            else 0.0,
            "checkpoint_code": str(fitness.get("checkpoint_code", "")) if fitness else "",
            "captured_at": self._fmt_dt(fitness.get("captured_at")) if fitness else "-",
        }
        data_integrity = {
            "status": str(
                ((diagnostics.get("proposal_data_integrity", {}) or {}).get("status", "unknown"))
            ),
            "failure_reasons": list(
                ((diagnostics.get("proposal_data_integrity", {}) or {}).get("failure_reasons", []))
                or []
            ),
        }
        blocker_reasons: list[str] = []
        if replay_summary["classification"] == "research_only":
            blocker_reasons.append("replay_research_not_yet_promising")
        if replay_summary["classification"] == "rejected_research":
            blocker_reasons.append("replay_evidence_rejected")
        if paper_sim_summary["sample_size"] < int(self.config.strategy_allocation_min_checkpoints):
            blocker_reasons.append("paper_sim_sample_below_min_checkpoints")
        if paper_sim_summary["composite_fitness_score"] <= float(
            self.config.strategy_allocation_suppress_threshold
        ):
            blocker_reasons.append("paper_sim_fitness_below_suppress_threshold")
        if data_integrity["status"] != "pass":
            blocker_reasons.extend(data_integrity["failure_reasons"])
        if promotion and bool(promotion.get("rejected")):
            blocker_reasons.append("manually_rejected")

        recommendation = "hold_research_only"
        next_stage = "research_only"
        if replay_summary["classification"] == "promising_research":
            next_stage = "promising_research"
            recommendation = "continue_research"
        if replay_summary["classification"] == "paper_sim_candidate":
            next_stage = "paper_sim_candidate"
            recommendation = "start_or_continue_paper_sim"
        if (
            paper_sim_summary["sample_size"] > 0
            and replay_summary["classification"] in {"paper_sim_candidate", "promising_research"}
        ):
            next_stage = "paper_sim_active"
            recommendation = "continue_paper_sim"
        if (
            not blocker_reasons
            and replay_summary["classification"] == "paper_sim_candidate"
            and paper_sim_summary["sample_size"] > 0
        ):
            next_stage = "paper_candidate"
            recommendation = "manual_paper_review"
        if (
            promotion
            and bool(promotion.get("paper_approved"))
            and (
                replay_summary["classification"] in {"research_only", "rejected_research"}
                or data_integrity["status"] != "pass"
            )
        ):
            next_stage = "paper_removal_candidate"
            recommendation = "manual_paper_removal_review"
            blocker_reasons = [*blocker_reasons, "manual_paper_removal_required"]
        if promotion and bool(promotion.get("paper_approved")):
            if next_stage != "paper_removal_candidate":
                next_stage = "paper_approved"
                recommendation = "paper_approved_manual"
        if promotion and bool(promotion.get("live_approved")):
            next_stage = "live_approved"
            recommendation = "live_approved_manual"
        if promotion and bool(promotion.get("rejected")):
            next_stage = "rejected"
            recommendation = "manually_rejected"

        payload = {
            "strategy_id": profile.strategy_id,
            "profile_id": profile.profile_id,
            "research_only_profile": bool(profile.parameters.get("research_only")),
            "replay_evidence_summary": replay_summary,
            "paper_sim_evidence_summary": paper_sim_summary,
            "net_return_after_costs_pct": paper_sim_summary["net_return_after_costs_pct"]
            if paper_sim_summary["sample_size"] > 0
            else replay_summary["net_return_after_costs_pct"],
            "win_rate": paper_sim_summary["win_rate"]
            if paper_sim_summary["sample_size"] > 0
            else replay_summary["win_rate"],
            "sample_size": max(replay_summary["sample_size"], paper_sim_summary["sample_size"]),
            "adverse_excursion_pct": paper_sim_summary["adverse_excursion_pct"],
            "data_integrity_status": data_integrity,
            "recommendation": recommendation,
            "blocker_reasons": blocker_reasons,
            "current_stage": next_stage,
            "current_record": promotion or {},
            "paper_execution_allowed": bool(
                proposal_strategy and proposal_strategy.get("paper_execution_allowed")
            ),
        }
        self.usage_ledger.record_strategy_promotion_evaluation(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
            stage=next_stage,
            research_only_profile=bool(profile.parameters.get("research_only")),
            recommendation=recommendation,
            blocker_reasons=blocker_reasons,
            replay_summary=replay_summary,
            paper_sim_summary=paper_sim_summary,
            data_integrity=data_integrity,
        )
        return payload

    def record_research_evidence(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        recommendation: str,
        blocker_reasons: list[str],
        replay_summary: dict[str, Any],
        paper_sim_summary: dict[str, Any],
        data_integrity: dict[str, Any],
        research_only_profile: bool,
    ) -> None:
        stage = "research_only"
        if recommendation in {
            "research_only",
            "promising_research",
            "paper_sim_candidate",
            "paper_sim_active",
            "paper_candidate",
            "rejected",
            "paper_removal_candidate",
            "live_candidate",
        }:
            stage = recommendation
        elif recommendation == "promising_research":
            stage = "promising_research"
        elif recommendation == "paper_sim_candidate":
            stage = "paper_sim_candidate"
        elif recommendation == "rejected_research":
            stage = "rejected"
        self.usage_ledger.record_strategy_promotion_evaluation(
            strategy_id=strategy_id,
            profile_id=profile_id,
            stage=stage,
            research_only_profile=research_only_profile,
            recommendation=recommendation,
            blocker_reasons=blocker_reasons,
            replay_summary=replay_summary,
            paper_sim_summary=paper_sim_summary,
            data_integrity=data_integrity,
        )

    def approve_paper(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        max_paper_notional_usd: float,
        max_open_trades: int,
        cooldown_minutes: int,
        confirmed: bool,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit_confirmation_required")
        profile = self._resolve_profile(strategy_id=strategy_id, profile_id=profile_id)
        evaluation = self.evaluate(strategy_id=profile.strategy_id, profile_id=profile.profile_id)
        self.usage_ledger.approve_strategy_for_paper(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
            research_only_profile=bool(profile.parameters.get("research_only")),
            max_paper_notional_usd=max_paper_notional_usd,
            max_open_trades=max_open_trades,
            cooldown_minutes=cooldown_minutes,
            recommendation=str(evaluation.get("recommendation", "")),
            blocker_reasons=list(evaluation.get("blocker_reasons", []) or []),
        )
        self.usage_ledger.resolve_attention_alerts_for_approval_request(
            approval_request_id=approval_request_id(
                strategy_id=profile.strategy_id,
                profile_id=profile.profile_id,
            ),
            status="resolved",
            reason="paper_approved_manually",
        )
        return self.usage_ledger.get_strategy_promotion(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
        ) or {}

    def reject(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        reason: str,
    ) -> dict[str, Any]:
        profile = self._resolve_profile(strategy_id=strategy_id, profile_id=profile_id)
        self.usage_ledger.reject_strategy_promotion(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
            research_only_profile=bool(profile.parameters.get("research_only")),
            reason=reason,
        )
        self.usage_ledger.resolve_attention_alerts_for_approval_request(
            approval_request_id=approval_request_id(
                strategy_id=profile.strategy_id,
                profile_id=profile.profile_id,
            ),
            status="rejected",
            reason=reason,
        )
        return self.usage_ledger.get_strategy_promotion(
            strategy_id=profile.strategy_id,
            profile_id=profile.profile_id,
        ) or {}

    def get_paper_approval(self, *, strategy_id: str, profile_id: str) -> PromotionApproval | None:
        get_strategy_promotion = getattr(self.usage_ledger, "get_strategy_promotion", None)
        if not callable(get_strategy_promotion):
            return None
        record = get_strategy_promotion(
            strategy_id=strategy_id,
            profile_id=profile_id,
        )
        if not record:
            return None
        return PromotionApproval(
            strategy_id=str(record.get("strategy_id", "")),
            profile_id=str(record.get("profile_id", "")),
            stage=str(record.get("stage", "research_only")),
            paper_approved=bool(record.get("paper_approved")),
            live_approved=bool(record.get("live_approved")),
            max_paper_notional_usd=float(record.get("max_paper_notional_usd", 0.0) or 0.0),
            max_open_trades=int(record.get("max_open_trades", 0) or 0),
            cooldown_minutes=int(record.get("cooldown_minutes", 0) or 0),
            paper_execution_profile=bool(record.get("paper_execution_profile")),
            research_only_profile=bool(record.get("research_only_profile")),
        )

    def render_status(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_status()
        lines = ["Strategy Promotion Status"]
        records = list(report.get("records", []) or [])
        if not records:
            lines.append("No promotion records found.")
            return "\n".join(lines)
        for item in records:
            lines.append(
                (
                    f"- {item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                    f" | stage={item.get('stage', '-')}"
                    f" | paper_approved={'yes' if item.get('paper_approved') else 'no'}"
                    f" | live_approved={'yes' if item.get('live_approved') else 'no'}"
                    f" | recommendation={item.get('recommendation', '-')}"
                    f" | max_paper_notional_usd={float(item.get('max_paper_notional_usd', 0.0) or 0.0):.2f}"
                    f" | max_open_trades={int(item.get('max_open_trades', 0) or 0)}"
                    f" | cooldown_minutes={int(item.get('cooldown_minutes', 0) or 0)}"
                )
            )
            blocker_reasons = item.get("blocker_reasons_json", []) or []
            if blocker_reasons:
                lines.append(
                    f"  blocker_reasons={','.join(str(reason) for reason in blocker_reasons)}"
                )
        return "\n".join(lines)

    def render_evaluation(self, *, report: dict[str, Any]) -> str:
        lines = [
            "Strategy Promotion Evaluation",
            f"strategy_id={report.get('strategy_id', '-')}"
            f" | profile_id={report.get('profile_id', '-')}"
            f" | current_stage={report.get('current_stage', '-')}"
            f" | recommendation={report.get('recommendation', '-')}",
            (
                f"net_return_after_costs_pct={float(report.get('net_return_after_costs_pct', 0.0) or 0.0):.6f}"
                f" | win_rate={float(report.get('win_rate', 0.0) or 0.0):.6f}"
                f" | sample_size={int(report.get('sample_size', 0) or 0)}"
                f" | adverse_excursion_pct={float(report.get('adverse_excursion_pct', 0.0) or 0.0):.6f}"
            ),
        ]
        replay = report.get("replay_evidence_summary", {}) or {}
        lines.append(
            "replay_evidence_summary="
            f"classification:{replay.get('classification', '-')}"
            f"/recommendation:{replay.get('recommendation', '-')}"
            f"/net:{float(replay.get('net_return_after_costs_pct', 0.0) or 0.0):.6f}"
            f"/win_rate:{float(replay.get('win_rate', 0.0) or 0.0):.6f}"
            f"/sample_size:{int(replay.get('sample_size', 0) or 0)}"
        )
        paper = report.get("paper_sim_evidence_summary", {}) or {}
        lines.append(
            "paper_sim_evidence_summary="
            f"fitness:{float(paper.get('composite_fitness_score', 0.0) or 0.0):.6f}"
            f"/net:{float(paper.get('net_return_after_costs_pct', 0.0) or 0.0):.6f}"
            f"/win_rate:{float(paper.get('win_rate', 0.0) or 0.0):.6f}"
            f"/sample_size:{int(paper.get('sample_size', 0) or 0)}"
            f"/adverse_excursion:{float(paper.get('adverse_excursion_pct', 0.0) or 0.0):.6f}"
        )
        integrity = report.get("data_integrity_status", {}) or {}
        lines.append(
            f"data_integrity_status={integrity.get('status', '-')}"
            f" | failure_reasons={','.join(integrity.get('failure_reasons', []) or []) or 'none'}"
        )
        lines.append(
            f"blocker_reasons={','.join(report.get('blocker_reasons', []) or []) or 'none'}"
        )
        return "\n".join(lines)

    def _resolve_profile(self, *, strategy_id: str, profile_id: str) -> StrategyProfile:
        registry: dict[tuple[str, str], StrategyProfile] = {}
        for strategy in build_strategy_registry():
            for profile in strategy.build_profiles(self.config):
                registry[(str(profile.strategy_id), str(profile.profile_id))] = profile
        if strategy_id and profile_id and (strategy_id, profile_id) in registry:
            return registry[(strategy_id, profile_id)]
        if strategy_id and not profile_id:
            matching = [profile for (sid, _), profile in registry.items() if sid == strategy_id]
            if len(matching) == 1:
                return matching[0]
        raise ValueError("strategy_profile_not_found")

    def _diagnostic_strategy(
        self,
        *,
        diagnostics: dict[str, Any],
        strategy_id: str,
    ) -> dict[str, Any] | None:
        for row in diagnostics.get("strategies", []) or []:
            item = row or {}
            if str(item.get("strategy_id", "")) == strategy_id:
                return item
        return None

    def _latest_research_entry(
        self,
        *,
        report: dict[str, Any],
        strategy_id: str,
        profile_id: str,
    ) -> dict[str, Any]:
        decisions = report.get("decisions", []) or []
        matching = [
            item
            for item in decisions
            if str(item.get("strategy_id", "")) == strategy_id
            and str(item.get("profile_id", "")) == profile_id
        ]
        if matching:
            latest = matching[0]
            return {
                "classification": latest.get("recommendation", "research_only"),
                "promotion_recommendation": latest.get("recommendation", "research_only"),
                "proposal_count": latest.get("proposals_created", 0),
                "replay_windows_with_data": latest.get("windows_tested_count", 0),
                "replay_windows_required": latest.get("windows_tested_count", 0),
                "sample_size_status": latest.get("sample_size_status", "-"),
                "gross_performance_pct": (latest.get("gross_return_summary_json", {}) or {}).get("avg_pct", 0.0),
                "net_performance_pct": (latest.get("net_return_summary_json", {}) or {}).get("avg_pct", 0.0),
                "net_win_rate": (latest.get("win_rate_summary_json", {}) or {}).get("avg", 0.0),
                "blocked_from_execution_reasons": latest.get("blocker_reasons_json", []),
                "allocation_includes_backtest_evidence": {
                    "paper": bool(latest.get("paper_fitness_includes_backtest")),
                    "live": bool(latest.get("live_fitness_includes_backtest")),
                },
            }
        return ((report.get("strategies", {}) or {}).get(strategy_id, {}) or {})

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")
