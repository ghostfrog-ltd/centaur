from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
import json
from typing import Any

from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = (
    "Research-only signal-generation diagnosis. No paper trades, live settings, "
    "thresholds, or promotion policy were changed."
)


@dataclass(frozen=True)
class _TargetIdentity:
    base_strategy_id: str
    profile_id: str
    timeframe: str


class SignalGenerationDiagnosisReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        planner: StrategyPortfolioResearchPlannerReport | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=False,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )
        self.planner = planner or StrategyPortfolioResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
            operator_mode=True,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str | None = None,
        profile_id: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        planner_report = self.planner.build_report()
        ranked = list(planner_report.get("ranked_strategies", []) or [])
        target = self._resolve_target(
            ranked=ranked,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        classifications = [self._classify_item(item) for item in ranked]
        blocker_counts = dict(
            sorted(Counter(str(item.get("blocker", "") or "unknown") for item in classifications).items())
        )
        proposals = self._proposals_for_target(target) if target else []
        next_command = str(proposals[0].get("next_recommended_command", "") or "") if proposals else ""
        report = {
            "title": "Signal Generation Diagnosis",
            "diagnosed_at": datetime.now().astimezone().isoformat(),
            "planner_next_action_before": str(planner_report.get("next_portfolio_action", "") or ""),
            "planner_next_command_before": str(planner_report.get("proposed_next_command", "") or ""),
            "selected_target": self._identity_string(target),
            "blocker_counts": blocker_counts,
            "strategy_classifications": classifications,
            "proposed_research_adjustments": proposals,
            "next_recommended_command": next_command,
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
            "safety_statement": SAFETY_STATEMENT,
        }
        report["persistence"] = self._persist_report(report=report, target=target)
        return report

    def render(
        self,
        *,
        base_strategy_id: str | None = None,
        profile_id: str | None = None,
        timeframe: str | None = None,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        lines = [
            str(report.get("title", "Signal Generation Diagnosis")),
            f"selected_target={report.get('selected_target', '')}",
            f"planner_next_action_before={report.get('planner_next_action_before', '')}",
            f"next_recommended_command={report.get('next_recommended_command', '')}",
            f"no_usable_signals_count={int((report.get('blocker_counts', {}) or {}).get('no_usable_signals', 0) or 0)}",
            "",
            "Strategy Classification",
        ]
        for item in report.get("strategy_classifications", []) or []:
            lines.append(
                f"strategy={item.get('strategy', '')}"
                f" | blocker={item.get('blocker', '')}"
                f" | reason={item.get('reason', '')}"
                f" | research_status={item.get('research_status', '')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
            )
        if report.get("proposed_research_adjustments"):
            lines.extend(["", "Proposed Research Adjustments"])
            for item in report.get("proposed_research_adjustments", []) or []:
                lines.append(
                    f"strategy={item.get('strategy', '')}"
                    f" | blocker={item.get('blocker', '')}"
                    f" | proposed_research_adjustment={item.get('proposed_research_adjustment', '')}"
                    f" | expected_effect={item.get('expected_effect', '')}"
                    f" | next_recommended_command={item.get('next_recommended_command', '')}"
                )
        lines.extend(
            [
                "",
                f"paper_trades_created={report.get('paper_trades_created', 'no')}",
                f"live_changed={report.get('live_changed', 'no')}",
                f"thresholds_changed={report.get('thresholds_changed', 'no')}",
                f"promotion_policy_changed={report.get('promotion_policy_changed', 'no')}",
                str(report.get("safety_statement", "")),
            ]
        )
        return "\n".join(lines)

    def _resolve_target(
        self,
        *,
        ranked: list[dict[str, Any]],
        base_strategy_id: str | None,
        profile_id: str | None,
        timeframe: str | None,
    ) -> dict[str, Any]:
        if base_strategy_id and profile_id and timeframe:
            for item in ranked:
                if self._matches(item, base_strategy_id=base_strategy_id, profile_id=profile_id, timeframe=timeframe):
                    return item
            return {}
        for item in ranked:
            latest_prep = dict(item.get("latest_replay_preparation") or {})
            if str(latest_prep.get("prep_status", "") or "") == "replay_prepared_but_no_signals":
                return item
        return {}

    def _matches(self, item: dict[str, Any], *, base_strategy_id: str, profile_id: str, timeframe: str) -> bool:
        return (
            str(item.get("base_strategy_id", "") or "") == str(base_strategy_id or "")
            and str(item.get("profile_id", "") or "") == str(profile_id or "")
            and str(item.get("timeframe", "") or "") == str(timeframe or "")
        )

    def _classify_item(self, item: dict[str, Any]) -> dict[str, Any]:
        latest_prep = dict(item.get("latest_replay_preparation") or {})
        audit = dict(item.get("audit_report") or {})
        blocker, reason = self._blocker_for_item(item, latest_prep=latest_prep, audit=audit)
        return {
            "strategy": self._identity_string(item),
            "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
            "profile_id": str(item.get("profile_id", "") or ""),
            "timeframe": str(item.get("timeframe", "") or ""),
            "research_status": str(item.get("research_status", "") or ""),
            "blocker": blocker,
            "reason": reason,
            "sample_size": int(item.get("latest_sample_size", 0) or 0),
            "net_return_after_costs": float(item.get("latest_net_return_after_costs", 0.0) or 0.0),
            "paper_candidate_path": str(item.get("paper_candidate_path", "") or ""),
        }

    def _blocker_for_item(
        self,
        item: dict[str, Any],
        *,
        latest_prep: dict[str, Any],
        audit: dict[str, Any],
    ) -> tuple[str, str]:
        research_status = str(item.get("research_status", "") or "")
        zero_reason = str(item.get("zero_decision_reason", "") or "")
        prep_status = str(latest_prep.get("prep_status", "") or "")
        prep_reason = str(latest_prep.get("blocker_reason", "") or latest_prep.get("reason", "") or "")
        audit_verdict = str(audit.get("audit_verdict", "") or "")
        sample_size = int(item.get("latest_sample_size", 0) or 0)
        net = float(item.get("latest_net_return_after_costs", 0.0) or 0.0)
        if prep_status == "replay_prepared_but_no_signals" or "no_usable_signals" in prep_reason:
            return "no_usable_signals", prep_reason or "Usable bars were present but replay preparation found no usable signals."
        if zero_reason == "no_bars_for_timeframe" or research_status == "data_gap":
            return "data_gap", prep_reason or "Historical bars are missing for the target timeframe."
        if zero_reason == "historical_bar_read_timeout" or research_status == "runtime_blocked":
            return "runtime_blocked", prep_reason or "Historical data reads timed out during bounded research."
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "concentration_fragility", "Paper-candidate audit rejected the branch for concentration fragility."
        if research_status == "promising_but_failed_audit":
            return "failed_paper_audit", audit_verdict or "Paper-candidate audit remains unresolved."
        if zero_reason == "unsupported_strategy_profile":
            return "unsupported_profile", "The profile is not currently approved for the paper path."
        if research_status in {"deprioritise_until_new_data", "no_viable_signal_after_precompute"}:
            return "deprioritise_until_new_data", prep_reason or "Recent evidence says to wait for fresh market data."
        if sample_size <= 0:
            return "insufficient_sample_size", "No usable replay sample has been recorded yet."
        if sample_size < 30:
            return "insufficient_sample_size", f"Only {sample_size} replay outcomes are available."
        if research_status in {"deprioritise", "retire_candidate"} or net <= 0.0:
            return "negative_replay_edge", "Persisted replay evidence remains negative after costs."
        return "deprioritise_until_new_data", "No immediate paper-safe research action is available."

    def _proposals_for_target(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        if not target:
            return []
        blocker, reason = self._blocker_for_item(
            target,
            latest_prep=dict(target.get("latest_replay_preparation") or {}),
            audit=dict(target.get("audit_report") or {}),
        )
        if blocker != "no_usable_signals":
            return []
        commands = self._proposal_templates(target)
        strategy = self._identity_string(target)
        return [
            {
                "strategy": strategy,
                "profile": str(target.get("profile_id", "") or ""),
                "timeframe": str(target.get("timeframe", "") or ""),
                "blocker": blocker,
                "proposed_research_adjustment": template["adjustment"],
                "expected_effect": template["effect"],
                "safety_notes": "Research-only variant exploration. Do not change paper thresholds, approvals, or live settings.",
                "next_recommended_command": template["command"],
            }
            for template in commands
        ]

    def _proposal_templates(self, target: dict[str, Any]) -> list[dict[str, str]]:
        base = str(target.get("base_strategy_id", "") or "")
        profile = str(target.get("profile_id", "") or "")
        timeframe = str(target.get("timeframe", "") or "")
        research_cmd = (
            ".venv-mac/bin/python main.py --run-strategy-variant-research "
            f"--base-strategy {base} --profile-id {profile} --timeframe {timeframe}"
        )
        report_cmd = (
            ".venv-mac/bin/python main.py --strategy-variant-research-report "
            f"--base-strategy {base} --profile-id {profile} --timeframe {timeframe}"
        )
        if base.startswith("crypto_pullback"):
            return [
                {
                    "adjustment": "widen pullback threshold search range",
                    "effect": "Explore whether the current downside trigger is too narrow to emit research-grade signals.",
                    "command": research_cmd,
                },
                {
                    "adjustment": "test timeframe alternative",
                    "effect": "Check whether the edge appears on a shorter or longer replay horizon before declaring the profile non-viable.",
                    "command": report_cmd,
                },
            ]
        if base.startswith("crypto_momentum"):
            return [
                {
                    "adjustment": "relax discovery score only inside research variant generation",
                    "effect": "Allow research variants to surface weak-but-structured setups without changing paper promotion gates.",
                    "command": research_cmd,
                },
                {
                    "adjustment": "test alternate target_multiple / stop_loss combinations",
                    "effect": "See whether the edge exists but is being filtered out by current reward-risk geometry.",
                    "command": research_cmd,
                },
                {
                    "adjustment": "test longer/shorter holding windows",
                    "effect": "Measure whether the current hold window is suppressing otherwise valid momentum continuations.",
                    "command": report_cmd,
                },
            ]
        if base == "crypto_research.range_breakout":
            return [
                {
                    "adjustment": "run bounded strategy variant research",
                    "effect": "Search the existing range-breakout family for research-only parameter combinations that can emit usable signals without touching paper or live gates.",
                    "command": research_cmd,
                },
                {
                    "adjustment": "adjust signal-generation search range research-only",
                    "effect": "Use persisted variant evidence to test whether the breakout range width, discovery score, or hold geometry is suppressing otherwise valid signals.",
                    "command": research_cmd,
                },
                {
                    "adjustment": "mark as no_viable_signal_until_new_data",
                    "effect": "Stop repeating the same no-signal path until fresh bars materially change the replay window.",
                    "command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
                },
            ]
        return [
            {
                "adjustment": "inspect existing variant research report",
                "effect": "Review persisted baseline and prior variant evidence before deciding whether a fresh bounded research pass is warranted.",
                "command": report_cmd,
            },
            {
                "adjustment": "mark as no_viable_signal_until_new_data",
                "effect": "Avoid re-running the same research loop until fresh data materially changes the setup.",
                "command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            },
        ]

    def _persist_report(self, *, report: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        if not target:
            return {"persisted": "no", "reason": "no_target"}
        digest = sha1(json.dumps(report, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        identity = _TargetIdentity(
            base_strategy_id=str(target.get("base_strategy_id", "") or ""),
            profile_id=str(target.get("profile_id", "") or ""),
            timeframe=str(target.get("timeframe", "") or ""),
        )
        raw = {
            "report_type": "signal_generation_diagnosis",
            "selected_target": report.get("selected_target", ""),
            "planner_next_action_before": report.get("planner_next_action_before", ""),
            "next_recommended_command": report.get("next_recommended_command", ""),
            "proposed_research_adjustments": report.get("proposed_research_adjustments", []),
            "blocker_counts": report.get("blocker_counts", {}),
            "safety_statement": SAFETY_STATEMENT,
        }
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"signal-generation-diagnosis:{digest}",
            variant_id="signal-generation-diagnosis",
            base_strategy_id=identity.base_strategy_id,
            profile_id=identity.profile_id,
            timeframe=identity.timeframe,
            replay_id=f"signal-generation-diagnosis-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}",
            dataset_id="signal_generation_diagnosis",
            asset_class="crypto" if identity.base_strategy_id.startswith("crypto_") else "equity",
            symbols_tested=[],
            sample_size=0,
            gross_return=0.0,
            net_return_after_costs=0.0,
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=0.0,
            drawdown=None,
            baseline_variant_id="",
            baseline_strategy_key=self._identity_string(target),
            baseline_net_return_after_costs=0.0,
            baseline_win_rate=0.0,
            beats_baseline=False,
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=datetime.now().astimezone(),
            notes=SAFETY_STATEMENT,
            raw=raw,
        )
        return {"persisted": "yes", "report_type": "signal_generation_diagnosis"}

    def _identity_string(self, item: dict[str, Any]) -> str:
        if not item:
            return ""
        return (
            f"{str(item.get('base_strategy_id', '') or '')}/"
            f"{str(item.get('profile_id', '') or '')}/"
            f"{str(item.get('timeframe', '') or '')}"
        )
