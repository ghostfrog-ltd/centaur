from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport
from app.framework.reporting.strategy_variant_research import (
    StrategyVariantResearchReport,
    StrategyVariantResearchService,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = "Research-only paper candidate audit. No paper or live approval has been changed."
MANUAL_APPROVAL_REMINDER = "This report does not approve paper. Manual approval is still required."
ALLOWED_VERDICTS = {
    "paper_candidate_audit_pass",
    "paper_candidate_promising_but_fragile",
    "paper_candidate_needs_more_replay",
    "paper_candidate_reject_due_to_concentration",
    "paper_candidate_reject_due_to_drawdown",
    "insufficient_candidate_data",
}
VERDICT_TO_AUDIT_STATUS = {
    "paper_candidate_audit_pass": "approved_for_paper",
    "paper_candidate_promising_but_fragile": "blocked_pending_more_data",
    "paper_candidate_needs_more_replay": "blocked_pending_more_data",
    "paper_candidate_reject_due_to_concentration": "parked_until_new_data",
    "paper_candidate_reject_due_to_drawdown": "deprioritised",
    "insufficient_candidate_data": "blocked_pending_more_data",
}


class PaperCandidateAuditReport:
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
        self.variant_reporter = StrategyVariantResearchReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.variant_service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.loss_reporter = StrategyLossDiagnosisReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "1Hour",
        variant_id: str | None = None,
    ) -> dict[str, Any]:
        variant_report = self.variant_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
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
        baseline = dict(variant_report.get("baseline", {}) or {})
        baseline_metrics = dict(baseline.get("metrics", {}) or {})
        candidate_definition, candidate_evaluation = self._select_candidate(
            definitions=definitions,
            evaluations=evaluations,
            variant_id=variant_id,
        )
        if not candidate_definition or not candidate_evaluation:
            audit_status = self._audit_status("insufficient_candidate_data")
            return {
                "title": "Paper Candidate Audit",
                "base_strategy_id": base_strategy_id,
                "profile_id": profile_id,
                "timeframe": timeframe,
                "candidate_strategy": f"{base_strategy_id}/{profile_id}/{timeframe}",
                "variant_id": str(variant_id or ""),
                "candidate_variant": {},
                "baseline_variant": baseline,
                "baseline_metrics": baseline_metrics,
                "candidate_metrics": {},
                "candidate_vs_baseline": {},
                "robustness_breakdown": {},
                "fragility_flags": ["insufficient_candidate_data"],
                "audit_status": audit_status,
                "paper_trading_allowed": "no",
                "paper_block_reason": "insufficient_candidate_data",
                "sample_size": 0,
                "net_return_after_costs": 0.0,
                "win_rate": 0.0,
                "drawdown": None,
                "symbol_concentration": "unknown",
                "wider_replay_status": "not_run",
                "required_next_action": "collect_more_replay_data",
                "next_recommended_command": self._next_recommended_command(
                    audit_status=audit_status,
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                    variant_id=str(variant_id or ""),
                    candidate_metrics={},
                ),
                "unblock_condition": "record enough replay outcomes to rerun the paper-candidate audit with adequate sample size",
                "stop_condition": "candidate still lacks adequate replay evidence after the next planned data collection step",
                "audit_verdict": "insufficient_candidate_data",
                "manual_approval_reminder": MANUAL_APPROVAL_REMINDER,
                "safety_statement": SAFETY_STATEMENT,
            }
        profile = self.variant_service._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        outcomes_payload = self.variant_service.collect_variant_outcomes(
            profile=self.variant_service._profile_from_variant(profile=profile, variant=candidate_definition),
            variant=candidate_definition,
            timeframe=timeframe,
            replay_id=f"paper-candidate-audit:{candidate_definition['variant_id']}",
        )
        outcomes = list(outcomes_payload.get("outcomes", []) or [])
        candidate_metrics = self._candidate_metrics(
            candidate_definition=candidate_definition,
            candidate_evaluation=candidate_evaluation,
            outcomes=outcomes,
        )
        candidate_vs_baseline = self._candidate_vs_baseline(
            candidate_metrics=candidate_metrics,
            baseline_metrics=baseline_metrics,
        )
        robustness_breakdown = self._robustness_breakdown(outcomes)
        fragility_flags = self._fragility_flags(
            candidate_metrics=candidate_metrics,
            candidate_vs_baseline=candidate_vs_baseline,
            robustness_breakdown=robustness_breakdown,
        )
        audit_verdict = self._audit_verdict(
            candidate_metrics=candidate_metrics,
            fragility_flags=fragility_flags,
        )
        if audit_verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"Unsupported paper candidate audit verdict: {audit_verdict}")
        audit_status = self._audit_status(audit_verdict)
        paper_block_reason = self._paper_block_reason(
            audit_verdict=audit_verdict,
            fragility_flags=fragility_flags,
        )
        symbol_concentration = self._symbol_concentration(robustness_breakdown)
        wider_replay_status = self._wider_replay_status(audit_status)
        required_next_action = self._required_next_action(
            audit_status=audit_status,
            audit_verdict=audit_verdict,
            sample_size=int(candidate_metrics.get("sample_size", 0) or 0),
        )
        next_recommended_command = self._next_recommended_command(
            audit_status=audit_status,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=str(candidate_definition.get("variant_id", "") or ""),
            candidate_metrics=candidate_metrics,
        )
        return {
            "title": "Paper Candidate Audit",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "candidate_strategy": f"{base_strategy_id}/{profile_id}/{timeframe}",
            "variant_id": str(candidate_definition.get("variant_id", "") or ""),
            "candidate_variant": {
                "variant_id": str(candidate_definition.get("variant_id", "") or ""),
                "base_strategy_id": str(candidate_definition.get("base_strategy_id", "") or ""),
                "profile_id": str(candidate_definition.get("profile_id", "") or ""),
                "timeframe": str(candidate_definition.get("timeframe", "") or ""),
                "params_json": dict(candidate_definition.get("params_json", {}) or {}),
                "created_at": candidate_definition.get("created_at"),
                "latest_evaluation_at": candidate_definition.get("latest_evaluation_at") or candidate_evaluation.get("evaluated_at"),
                "recommended_status": str(candidate_evaluation.get("recommended_status", "") or ""),
            },
            "baseline_variant": baseline,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "candidate_vs_baseline": candidate_vs_baseline,
            "robustness_breakdown": robustness_breakdown,
            "fragility_flags": fragility_flags,
            "audit_status": audit_status,
            "paper_trading_allowed": "yes" if audit_status == "approved_for_paper" else "no",
            "paper_block_reason": paper_block_reason,
            "sample_size": int(candidate_metrics.get("sample_size", 0) or 0),
            "net_return_after_costs": float(candidate_metrics.get("net_return_after_costs", 0.0) or 0.0),
            "win_rate": float(candidate_metrics.get("win_rate", 0.0) or 0.0),
            "drawdown": candidate_metrics.get("drawdown"),
            "symbol_concentration": symbol_concentration,
            "wider_replay_status": wider_replay_status,
            "required_next_action": required_next_action,
            "next_recommended_command": next_recommended_command,
            "unblock_condition": self._unblock_condition(
                audit_status=audit_status,
                audit_verdict=audit_verdict,
            ),
            "stop_condition": self._stop_condition(
                audit_status=audit_status,
                audit_verdict=audit_verdict,
            ),
            "audit_verdict": audit_verdict,
            "manual_approval_reminder": MANUAL_APPROVAL_REMINDER,
            "safety_statement": SAFETY_STATEMENT,
        }

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "1Hour",
        variant_id: str | None = None,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
        )
        candidate = dict(report.get("candidate_variant", {}) or {})
        metrics = dict(report.get("candidate_metrics", {}) or {})
        comparison = dict(report.get("candidate_vs_baseline", {}) or {})
        lines = [
            str(report.get("title", "Paper Candidate Audit")),
            f"base_strategy={report.get('base_strategy_id', '-')}"
            f" | profile={report.get('profile_id', '-')}"
            f" | timeframe={report.get('timeframe', '-')}",
            f"candidate_strategy={report.get('candidate_strategy', '-')}",
            f"variant_id={report.get('variant_id', '-')}",
            f"candidate_variant_id={candidate.get('variant_id', '-')}"
            f" | created_at={candidate.get('created_at') or '-'}"
            f" | latest_evaluation_at={candidate.get('latest_evaluation_at') or '-'}",
            f"params_json={candidate.get('params_json', {})}",
            f"audit_status={report.get('audit_status', '-')}",
            f"paper_trading_allowed={report.get('paper_trading_allowed', 'no')}",
            f"paper_block_reason={report.get('paper_block_reason', '')}",
            f"sample_size={report.get('sample_size', 0)}",
            f"net_return_after_costs={report.get('net_return_after_costs', 0.0)}",
            f"win_rate={report.get('win_rate', 0.0)}",
            f"drawdown={report.get('drawdown')}",
            f"symbol_concentration={report.get('symbol_concentration', 'unknown')}",
            f"wider_replay_status={report.get('wider_replay_status', 'not_run')}",
            (
                "candidate_metrics="
                f"sample_size={metrics.get('sample_size', 0)}"
                f" | gross_return_before_costs={metrics.get('gross_return_before_costs', 0.0)}"
                f" | net_return_after_costs={metrics.get('net_return_after_costs', 0.0)}"
                f" | win_rate={metrics.get('win_rate', 0.0)}"
                f" | drawdown={metrics.get('drawdown')}"
                f" | average_winner={metrics.get('average_winner', 0.0)}"
                f" | average_loser={metrics.get('average_loser', 0.0)}"
                f" | profit_factor={metrics.get('profit_factor', 0.0)}"
                f" | target_hit_count={metrics.get('target_hit_count', 0)}"
                f" | stop_hit_count={metrics.get('stop_hit_count', 0)}"
                f" | time_exit_count={metrics.get('time_exit_count', 0)}"
                f" | costs_included={'yes' if metrics.get('costs_included') else 'no'}"
            ),
            (
                "candidate_vs_baseline="
                f"net_improvement={comparison.get('net_return_after_costs_improvement', 0.0)}"
                f" | win_rate_improvement={comparison.get('win_rate_improvement', 0.0)}"
                f" | drawdown_change={comparison.get('drawdown_change')}"
                f" | sample_size_change={comparison.get('sample_size_change', 0)}"
                f" | beats_baseline={'yes' if comparison.get('beats_baseline') else 'no'}"
                f" | beats_thresholds={'yes' if comparison.get('beats_thresholds') else 'no'}"
            ),
            f"fragility_flags={report.get('fragility_flags', [])}",
            f"audit_verdict={report.get('audit_verdict', '-')}",
            f"required_next_action={report.get('required_next_action', '')}",
            f"next_recommended_command={report.get('next_recommended_command', '')}",
            f"unblock_condition={report.get('unblock_condition', '')}",
            f"stop_condition={report.get('stop_condition', '')}",
            str(report.get("manual_approval_reminder", "")),
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def _audit_status(self, audit_verdict: str) -> str:
        return VERDICT_TO_AUDIT_STATUS.get(audit_verdict, "failed_audit")

    def _paper_block_reason(self, *, audit_verdict: str, fragility_flags: list[str]) -> str:
        if audit_verdict == "paper_candidate_audit_pass":
            return ""
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "concentration_fragility"
        if audit_verdict == "paper_candidate_reject_due_to_drawdown":
            return "drawdown_limit"
        if audit_verdict == "paper_candidate_needs_more_replay":
            return "insufficient_sample_size"
        if audit_verdict == "insufficient_candidate_data":
            return "insufficient_candidate_data"
        if "high_drawdown_despite_positive_return" in fragility_flags:
            return "high_drawdown_fragility"
        return "fragility_flags_present"

    def _symbol_concentration(self, robustness_breakdown: dict[str, Any]) -> str:
        rows = list((robustness_breakdown.get("by_symbol", []) or []))
        if not rows:
            return "unknown"
        weighted_total = sum(
            float(item.get("net_return_after_costs", 0.0) or 0.0) * int(item.get("sample_size", 0) or 0)
            for item in rows
        )
        if weighted_total <= 0:
            return "not_positive"
        leader = rows[0]
        leader_weighted = float(leader.get("net_return_after_costs", 0.0) or 0.0) * int(leader.get("sample_size", 0) or 0)
        share = leader_weighted / weighted_total if weighted_total else 0.0
        return f"{str(leader.get('symbol', '') or 'unknown').upper()}:{share:.3f}"

    def _wider_replay_status(self, audit_status: str) -> str:
        if audit_status in {"blocked_pending_more_data", "parked_until_new_data"}:
            return "needs_new_evidence"
        return "not_required"

    def _required_next_action(self, *, audit_status: str, audit_verdict: str, sample_size: int) -> str:
        if audit_status == "approved_for_paper":
            return "manual_paper_approval_review"
        if audit_status == "parked_until_new_data":
            return "collect_wider_replay_evidence" if sample_size < 200 else "review_other_candidates"
        if audit_status == "deprioritised":
            return "review_other_candidates"
        if audit_verdict == "insufficient_candidate_data":
            return "collect_more_replay_data"
        return "collect_more_replay_data"

    def _next_recommended_command(
        self,
        *,
        audit_status: str,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        candidate_metrics: dict[str, Any],
    ) -> str:
        if audit_status == "approved_for_paper":
            return (
                ".venv-mac/bin/python main.py --promotion-evaluate "
                f"--strategy-id {base_strategy_id} --profile-id {profile_id}"
            ).strip()
        if audit_status == "deprioritised":
            return ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        symbol = "WDC"
        symbols = list(candidate_metrics.get("symbols_tested", []) or [])
        if symbols:
            symbol = str(symbols[0] or "WDC").upper()
        variant_clause = f" --variant-id {variant_id}" if variant_id else ""
        return (
            ".venv-mac/bin/python main.py --collect-symbol-replay-evidence "
            f"--base-strategy {base_strategy_id} "
            f"--profile-id {profile_id} "
            f"--timeframe {timeframe}{variant_clause} --symbol {symbol}"
        ).strip()

    def _unblock_condition(self, *, audit_status: str, audit_verdict: str) -> str:
        if audit_status == "approved_for_paper":
            return "manual paper approval is still required before any broker paper trading can be allowed"
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "fresh wider replay evidence shows adequate sample size, acceptable drawdown, and no concentration fragility"
        if audit_verdict == "paper_candidate_reject_due_to_drawdown":
            return "future evidence would need materially lower drawdown and a fresh audit review"
        return "fresh replay evidence passes the paper-candidate audit thresholds and fragility checks"

    def _stop_condition(self, *, audit_status: str, audit_verdict: str) -> str:
        if audit_status == "approved_for_paper":
            return "manual approval is denied or later evidence invalidates the candidate"
        if audit_verdict == "paper_candidate_reject_due_to_drawdown":
            return "candidate remains below drawdown policy after future replay review"
        if audit_verdict == "paper_candidate_reject_due_to_concentration":
            return "wider replay remains concentrated, unstable, or net negative after fresh evidence"
        return "candidate still fails paper-candidate audit after the next evidence collection step"

    def _select_candidate(
        self,
        *,
        definitions: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        variant_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        latest_by_variant: dict[str, dict[str, Any]] = {}
        for evaluation in evaluations:
            key = str(evaluation.get("variant_id", "") or "")
            if key and key not in latest_by_variant:
                latest_by_variant[key] = evaluation
        by_id = {str(item.get("variant_id", "") or ""): dict(item) for item in definitions}
        if variant_id:
            return by_id.get(variant_id, {}), latest_by_variant.get(variant_id, {})
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for key, evaluation in latest_by_variant.items():
            if str(evaluation.get("recommended_status", "") or "") != "paper_candidate_requires_manual_approval":
                continue
            definition = by_id.get(key)
            if not definition:
                continue
            candidates.append((definition, evaluation))
        if not candidates:
            return {}, {}
        return max(
            candidates,
            key=lambda item: (
                float(item[1].get("net_return_after_costs", 0.0) or 0.0),
                float(item[1].get("win_rate", 0.0) or 0.0),
                int(item[1].get("sample_size", 0) or 0),
            ),
        )

    def _candidate_metrics(
        self,
        *,
        candidate_definition: dict[str, Any],
        candidate_evaluation: dict[str, Any],
        outcomes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        distribution = self.loss_reporter._return_distribution(outcomes)
        cost_drag = self.loss_reporter._cost_drag(outcomes)
        return {
            "sample_size": int(candidate_evaluation.get("sample_size", 0) or 0),
            "gross_return_before_costs": float(candidate_evaluation.get("gross_return", distribution.get("gross_return_before_costs", 0.0)) or 0.0),
            "net_return_after_costs": float(candidate_evaluation.get("net_return_after_costs", distribution.get("net_return_after_costs", 0.0)) or 0.0),
            "win_rate": float(candidate_evaluation.get("win_rate", distribution.get("win_rate", 0.0)) or 0.0),
            "drawdown": candidate_evaluation.get("drawdown"),
            "average_winner": float(candidate_evaluation.get("average_winner", distribution.get("average_winner", 0.0)) or 0.0),
            "average_loser": float(candidate_evaluation.get("average_loser", distribution.get("average_loser", 0.0)) or 0.0),
            "profit_factor": float(distribution.get("profit_factor", 0.0) or 0.0),
            "target_hit_count": int((dict(candidate_evaluation.get("raw_json", {}) or {}).get("target_hit_count", 0)) or 0),
            "stop_hit_count": int((dict(candidate_evaluation.get("raw_json", {}) or {}).get("stop_hit_count", 0)) or 0),
            "time_exit_count": int((dict(candidate_evaluation.get("raw_json", {}) or {}).get("time_exit_count", 0)) or 0),
            "symbols_tested": list(candidate_evaluation.get("symbols_tested", []) or []),
            "costs_included": bool(outcomes) or float(cost_drag.get("average_cost_per_decision", 0.0) or 0.0) > 0.0,
            "gross_positive_net_negative_count": int(
                candidate_evaluation.get("gross_positive_net_negative_count")
                or cost_drag.get("gross_positive_net_negative_count", 0)
                or 0
            ),
            "beats_baseline": bool(candidate_evaluation.get("beats_baseline")),
            "beats_thresholds": bool(candidate_evaluation.get("beats_thresholds")),
            "params_json": dict(candidate_definition.get("params_json", {}) or {}),
        }

    def _candidate_vs_baseline(
        self,
        *,
        candidate_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "net_return_after_costs_improvement": round(
                float(candidate_metrics.get("net_return_after_costs", 0.0) or 0.0)
                - float(baseline_metrics.get("net_return_after_costs", 0.0) or 0.0),
                6,
            ),
            "win_rate_improvement": round(
                float(candidate_metrics.get("win_rate", 0.0) or 0.0)
                - float(baseline_metrics.get("win_rate", 0.0) or 0.0),
                6,
            ),
            "drawdown_change": round(
                float(candidate_metrics.get("drawdown", 0.0) or 0.0)
                - float(baseline_metrics.get("drawdown", 0.0) or 0.0),
                6,
            ) if baseline_metrics.get("drawdown") is not None and candidate_metrics.get("drawdown") is not None else None,
            "sample_size_change": int(candidate_metrics.get("sample_size", 0) or 0) - int(baseline_metrics.get("sample_size", 0) or 0),
            "exit_mix_change": {
                "target_hit_count_change": int(candidate_metrics.get("target_hit_count", 0) or 0) - int((dict(baseline_metrics.get("raw_json", {}) or {}).get("target_hit_count", 0)) or 0),
                "stop_hit_count_change": int(candidate_metrics.get("stop_hit_count", 0) or 0) - int((dict(baseline_metrics.get("raw_json", {}) or {}).get("stop_hit_count", 0)) or 0),
                "time_exit_count_change": int(candidate_metrics.get("time_exit_count", 0) or 0) - int((dict(baseline_metrics.get("raw_json", {}) or {}).get("time_exit_count", 0)) or 0),
            },
            "beats_baseline": bool(candidate_metrics.get("beats_baseline")),
            "beats_thresholds": bool(candidate_metrics.get("beats_thresholds")),
        }

    def _robustness_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "by_month": self.loss_reporter._bucket_breakdown(outcomes).get("by_month", []),
            "by_week": self._group_by_week(outcomes),
            "by_symbol": self._symbol_rows(outcomes),
            "by_trade_count_bucket": self.loss_reporter._bucket_breakdown(outcomes).get("by_trade_count_bucket", []),
            "by_pullback_bucket": self.loss_reporter._bucket_breakdown(outcomes).get("by_pullback_depth_bucket", []),
            "by_discovery_score_bucket": self.loss_reporter._bucket_breakdown(outcomes).get("by_discovery_score_bucket", []),
        }

    def _group_by_week(self, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in outcomes:
            dt = self.loss_reporter._to_datetime(item.get("evaluated_at"))
            if dt is None:
                continue
            iso_year, iso_week, _ = dt.isocalendar()
            grouped[f"{iso_year}-W{iso_week:02d}"].append(item)
        return [
            self.loss_reporter._group_row("period", period, rows, label_key="period")
            for period, rows in sorted(grouped.items())
        ]

    def _symbol_rows(self, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in outcomes:
            symbol = str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "")
            if symbol:
                grouped[symbol].append(item)
        return sorted(
            [self.loss_reporter._group_row("symbol", symbol, rows) for symbol, rows in grouped.items()],
            key=lambda item: (item["net_return_after_costs"], item["sample_size"]),
            reverse=True,
        )

    def _fragility_flags(
        self,
        *,
        candidate_metrics: dict[str, Any],
        candidate_vs_baseline: dict[str, Any],
        robustness_breakdown: dict[str, Any],
    ) -> list[str]:
        flags: list[str] = []
        sample_size = int(candidate_metrics.get("sample_size", 0) or 0)
        if sample_size < 150:
            flags.append("too_few_samples")
        by_symbol = list(robustness_breakdown.get("by_symbol", []) or [])
        if by_symbol:
            total_net = sum(float(item.get("net_return_after_costs", 0.0) or 0.0) * int(item.get("sample_size", 0) or 0) for item in by_symbol)
            best_symbol = by_symbol[0]
            best_symbol_contribution = float(best_symbol.get("net_return_after_costs", 0.0) or 0.0) * int(best_symbol.get("sample_size", 0) or 0)
            if total_net > 0 and best_symbol_contribution / total_net >= 0.5:
                flags.append("one_symbol_dominates_profit")
        by_month = list(robustness_breakdown.get("by_month", []) or [])
        if by_month:
            total_net = sum(float(item.get("net_return_after_costs", 0.0) or 0.0) * int(item.get("sample_size", 0) or 0) for item in by_month)
            best_month = max(
                by_month,
                key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0) * int(item.get("sample_size", 0) or 0),
            )
            best_month_contribution = float(best_month.get("net_return_after_costs", 0.0) or 0.0) * int(best_month.get("sample_size", 0) or 0)
            if total_net > 0 and best_month_contribution / total_net >= 0.75:
                flags.append("one_month_dominates_profit")
        if float(candidate_metrics.get("drawdown", 0.0) or 0.0) >= 0.9:
            flags.append("high_drawdown_despite_positive_return")
        if int(candidate_metrics.get("gross_positive_net_negative_count", 0) or 0) >= max(10, sample_size // 10):
            flags.append("costs_turn_many_gross_winners_negative")
        if int(candidate_metrics.get("stop_hit_count", 0) or 0) >= int(candidate_metrics.get("target_hit_count", 0) or 0):
            flags.append("stop_losses_too_frequent")
        if by_month and sum(1 for item in by_month if float(item.get("target_hit_count", 0) or 0) > 0) <= 1:
            flags.append("target_hits_concentrated_in_one_period")
        by_week = list(robustness_breakdown.get("by_week", []) or [])
        if by_week and any(float(item.get("net_return_after_costs", 0.0) or 0.0) < 0.0 for item in by_week[-2:]):
            flags.append("poor_neighboring_period_stability")
        if float(candidate_vs_baseline.get("net_return_after_costs_improvement", 0.0) or 0.0) <= 0.0:
            flags.append("no_baseline_improvement")
        return flags

    def _audit_verdict(
        self,
        *,
        candidate_metrics: dict[str, Any],
        fragility_flags: list[str],
    ) -> str:
        sample_size = int(candidate_metrics.get("sample_size", 0) or 0)
        if sample_size <= 0:
            return "insufficient_candidate_data"
        if sample_size < int(self.config.research_min_proposals):
            return "paper_candidate_needs_more_replay"
        if "one_symbol_dominates_profit" in fragility_flags or "one_month_dominates_profit" in fragility_flags:
            return "paper_candidate_reject_due_to_concentration"
        if "high_drawdown_despite_positive_return" in fragility_flags:
            return "paper_candidate_reject_due_to_drawdown"
        if fragility_flags:
            return "paper_candidate_promising_but_fragile"
        return "paper_candidate_audit_pass"
