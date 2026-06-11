from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from app.framework.reporting.strategy_variant_research import StrategyVariantResearchService
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


ALLOWED_VERDICTS = {
    "snapback_cost_problem",
    "snapback_symbol_filter_problem",
    "snapback_entry_quality_problem",
    "snapback_exit_logic_problem",
    "snapback_no_edge_detected",
    "cost_problem",
    "symbol_filter_problem",
    "entry_quality_problem",
    "exit_logic_problem",
    "no_edge_detected",
    "insufficient_diagnostics",
}

ALLOWED_PROFITABILITY_VERDICTS = {
    "winner_size_too_small",
    "win_rate_too_low",
    "both_win_rate_and_winner_size_too_weak",
    "costs_dominate_small_edge",
    "target_exit_logic_problem",
    "break_even_requirements_met",
    "insufficient_data",
}

ALLOWED_EXIT_VERDICTS = {
    "time_exit_too_frequent",
    "target_too_far",
    "stop_too_tight",
    "holding_window_too_short",
    "holding_window_too_long",
    "exit_logic_no_clear_fix",
    "insufficient_exit_diagnostics",
}

ALLOWED_SUBSET_EDGE_VERDICTS = {
    "symbol_filter_promising",
    "trade_count_filter_promising",
    "pullback_depth_filter_promising",
    "score_filter_promising",
    "regime_filter_promising",
    "no_clear_subset_edge",
    "insufficient_subset_data",
}


class StrategyLossDiagnosisReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str | None = None,
    ) -> dict[str, Any]:
        profile = self.service._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        baseline = next(
            (item for item in definitions if item.get("generation_reason") == "baseline_profile"),
            None,
        )
        if baseline is None:
            return self._empty_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                data_source="missing_baseline_definition",
            )
        diagnosed_variant = baseline
        data_source = "regenerated_read_only_baseline"
        if variant_id:
            diagnosed_variant = next(
                (item for item in definitions if str(item.get("variant_id", "") or "") == variant_id),
                None,
            )
            if diagnosed_variant is None:
                return self._empty_report(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                    data_source="missing_variant_definition",
                    diagnosed_variant_id=variant_id,
                    baseline=baseline,
                )
            data_source = "regenerated_read_only_variant"
        collected = self.service.collect_variant_outcomes(
            profile=self.service._profile_from_variant(profile=profile, variant=diagnosed_variant),
            variant=diagnosed_variant,
            timeframe=timeframe,
            replay_id=f"loss-diagnosis-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}",
        )
        outcomes = list(collected.get("outcomes", []) or [])
        diagnostics = dict(collected.get("diagnostics", {}) or {})
        data_adequacy = dict(diagnostics.get("data_adequacy", {}) or {})
        if not outcomes:
            return self._empty_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                data_source=data_source,
                diagnosed_variant_id=str(diagnosed_variant.get("variant_id", "") or ""),
                baseline=baseline,
                data_adequacy=data_adequacy,
            )
        distribution = self._return_distribution(outcomes)
        cost_drag = self._cost_drag(outcomes)
        symbol_breakdown = self._symbol_breakdown(outcomes)
        period_breakdown = self._period_breakdown(outcomes)
        entry_quality = self._entry_quality_breakdown(outcomes)
        bucket_breakdown = self._bucket_breakdown(outcomes)
        stop_target = self._stop_target_diagnosis(outcomes)
        profitability = self._profitability_requirement_diagnosis(
            distribution=distribution,
            cost_drag=cost_drag,
            stop_target=stop_target,
            baseline=diagnosed_variant,
        )
        exit_diagnosis = self._time_exit_and_target_achievement_diagnosis(
            outcomes=outcomes,
            baseline=diagnosed_variant,
        )
        verdict, next_fix, why = self._verdict(
            base_strategy_id=base_strategy_id,
            distribution=distribution,
            cost_drag=cost_drag,
            symbol_breakdown=symbol_breakdown,
            entry_quality=entry_quality,
            stop_target=stop_target,
        )
        subset_verdict = self._subset_edge_verdict(
            symbol_breakdown=symbol_breakdown,
            bucket_breakdown=bucket_breakdown,
        )
        return {
            "title": "Strategy Loss Diagnosis",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "data_source": data_source,
            "baseline_variant_id": str(baseline.get("variant_id", "") or ""),
            "baseline_params_json": dict(baseline.get("params_json", {}) or {}),
            "diagnosed_variant_id": str(diagnosed_variant.get("variant_id", "") or ""),
            "diagnosed_params_json": dict(diagnosed_variant.get("params_json", {}) or {}),
            "data_adequacy": data_adequacy,
            "return_distribution": distribution,
            "cost_drag": cost_drag,
            "symbol_breakdown": symbol_breakdown,
            "time_breakdown": period_breakdown,
            "entry_quality_breakdown": entry_quality,
            "bucket_breakdown": bucket_breakdown,
            "stop_target_diagnosis": stop_target,
            "profitability_requirement_diagnosis": profitability,
            "time_exit_and_target_achievement_diagnosis": exit_diagnosis,
            "verdict": verdict,
            "most_actionable_next_fix": next_fix,
            "why": why,
            "subset_edge_diagnosis": subset_verdict,
            "safety_statement": "Research-only loss diagnosis. No paper or live approval has been changed.",
        }

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str | None = None,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
        )
        dist = report.get("return_distribution", {}) or {}
        cost = report.get("cost_drag", {}) or {}
        stop = report.get("stop_target_diagnosis", {}) or {}
        profitability = report.get("profitability_requirement_diagnosis", {}) or {}
        exit_diagnosis = report.get("time_exit_and_target_achievement_diagnosis", {}) or {}
        subset_edge = report.get("subset_edge_diagnosis", {}) or {}
        lines = [
            str(report.get("title", "Strategy Loss Diagnosis")),
            f"base_strategy={report.get('base_strategy_id', '-')}"
            f" | profile={report.get('profile_id', '-')}"
            f" | timeframe={report.get('timeframe', '-')}"
            f" | data_source={report.get('data_source', '-')}",
            f"baseline_variant_id={report.get('baseline_variant_id', '-')}"
            f" | diagnosed_variant_id={report.get('diagnosed_variant_id', '-')}",
            f"diagnosed_params_json={report.get('diagnosed_params_json', {})}",
            (
                "return_distribution="
                f"total_decisions={int(dist.get('total_decisions', 0) or 0)}"
                f" | winners={int(dist.get('winners', 0) or 0)}"
                f" | losers={int(dist.get('losers', 0) or 0)}"
                f" | win_rate={dist.get('win_rate', 0.0)}"
                f" | avg_winner={dist.get('average_winner', 0.0)}"
                f" | avg_loser={dist.get('average_loser', 0.0)}"
                f" | median_return={dist.get('median_return', 0.0)}"
                f" | gross_return_before_costs={dist.get('gross_return_before_costs', 0.0)}"
                f" | net_return_after_costs={dist.get('net_return_after_costs', 0.0)}"
                f" | profit_factor={dist.get('profit_factor', 0.0)}"
            ),
            (
                "cost_drag="
                f"total_drag={cost.get('total_cost_drag', 0.0)}"
                f" | avg_cost_per_decision={cost.get('average_cost_per_decision', 0.0)}"
                f" | gross_positive_net_negative={int(cost.get('gross_positive_net_negative_count', 0) or 0)}"
            ),
            "best_symbols:",
        ]
        for item in (report.get("symbol_breakdown", {}) or {}).get("best_10", []) or []:
            lines.append(
                f"- symbol={item.get('symbol', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | average_winner={item.get('average_winner', 0.0)}"
                f" | average_loser={item.get('average_loser', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
                f" | drawdown={item.get('drawdown', 0.0)}"
            )
        lines.append("worst_symbols:")
        for item in (report.get("symbol_breakdown", {}) or {}).get("worst_10", []) or []:
            lines.append(
                f"- symbol={item.get('symbol', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | average_winner={item.get('average_winner', 0.0)}"
                f" | average_loser={item.get('average_loser', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
                f" | drawdown={item.get('drawdown', 0.0)}"
            )
        lines.append("bucket_breakdown:")
        for section_name in (
            "by_month",
            "by_trade_count_bucket",
            "by_pullback_depth_bucket",
            "by_discovery_score_bucket",
            "by_movement_bucket",
            "by_rank_bucket",
        ):
            lines.append(f"{section_name}:")
            for item in (report.get("bucket_breakdown", {}) or {}).get(section_name, []) or []:
                label = item.get("bucket", item.get("period", "-"))
                lines.append(
                    f"- bucket={label}"
                    f" | sample_size={item.get('sample_size', 0)}"
                    f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                    f" | win_rate={item.get('win_rate', 0.0)}"
                    f" | average_winner={item.get('average_winner', 0.0)}"
                    f" | average_loser={item.get('average_loser', 0.0)}"
                    f" | target_hit_count={item.get('target_hit_count', 0)}"
                    f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                    f" | time_exit_count={item.get('time_exit_count', 0)}"
                )
        lines.append(
            f"exit_reason_counts=target_hit:{int(stop.get('target_hit_count', 0) or 0)},"
            f"stop_hit:{int(stop.get('stop_hit_count', 0) or 0)},"
            f"time_exit:{int(stop.get('time_exit_count', 0) or 0)},"
            f"ambiguous:{int(stop.get('ambiguous_count', 0) or 0)}"
        )
        lines.append("Profitability Requirement Diagnosis")
        lines.append(
            f"current_win_rate={profitability.get('current_win_rate', 0.0)}"
            f" | required_win_rate={profitability.get('required_win_rate', 0.0)}"
            f" | win_rate_gap={profitability.get('win_rate_gap', 0.0)}"
            f" | current_average_winner_pct={profitability.get('current_average_winner_pct', 0.0)}"
            f" | required_average_winner_pct={profitability.get('required_average_winner_pct', 0.0)}"
            f" | average_winner_gap={profitability.get('average_winner_gap', 0.0)}"
            f" | current_average_loser_pct={profitability.get('current_average_loser_pct', 0.0)}"
            f" | current_profit_factor={profitability.get('current_profit_factor', 0.0)}"
            f" | target_profit_factor={profitability.get('target_profit_factor', 0.0)}"
            f" | configured_target_return_pct={profitability.get('configured_target_return_pct', 0.0)}"
        )
        lines.append(
            f"observed_vs_required_summary={profitability.get('observed_vs_required_summary', '-')}"
            f" | profitability_verdict={profitability.get('profitability_verdict', '-')}"
            f" | most_actionable_next_fix={profitability.get('most_actionable_next_fix', '-')}"
        )
        lines.append("Time Exit and Target Achievement Diagnosis")
        for item in exit_diagnosis.get("exit_reason_breakdown", []) or []:
            lines.append(
                f"- exit_reason={item.get('exit_reason', '-')}"
                f" | count={item.get('count', 0)}"
                f" | pct_of_decisions={item.get('pct_of_decisions', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | average_return={item.get('average_return', 0.0)}"
                f" | median_return={item.get('median_return', 0.0)}"
                f" | gross_return_before_costs={item.get('gross_return_before_costs', 0.0)}"
                f" | average_cost={item.get('average_cost', 0.0)}"
                f" | contribution_to_total_net_return={item.get('contribution_to_total_net_return', 0.0)}"
            )
        lines.append(
            f"time_exit_quality_summary={exit_diagnosis.get('time_exit_quality_summary', '-')}"
            f" | target_achievement_summary={exit_diagnosis.get('target_achievement_summary', '-')}"
            f" | stop_damage_summary={exit_diagnosis.get('stop_damage_summary', '-')}"
        )
        lines.append(
            f"holding_window_diagnostics_available={'yes' if exit_diagnosis.get('holding_window_diagnostics_available') else 'no'}"
            f" | exit_verdict={exit_diagnosis.get('exit_verdict', '-')}"
            f" | most_actionable_next_fix={exit_diagnosis.get('most_actionable_next_fix', '-')}"
        )
        lines.append(
            f"verdict={report.get('verdict', '-')}"
            f" | most_actionable_next_fix={report.get('most_actionable_next_fix', '-')}"
            f" | why={report.get('why', '-')}"
        )
        lines.append(
            f"subset_edge_verdict={subset_edge.get('verdict', '-')}"
            f" | most_actionable_next_fix={subset_edge.get('most_actionable_next_fix', '-')}"
            f" | why={subset_edge.get('why', '-')}"
        )
        lines.append(str(report.get("safety_statement", "")))
        return "\n".join(lines)

    def _return_distribution(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        net = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes]
        gross = [float(item.get("gross_realized_return_pct", 0.0) or 0.0) for item in outcomes]
        winners = [value for value in net if value > 0]
        losers = [value for value in net if value < 0]
        gross_profit = sum(value for value in net if value > 0)
        gross_loss_abs = abs(sum(value for value in net if value < 0))
        return {
            "total_decisions": len(outcomes),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round((len(winners) / len(outcomes)) if outcomes else 0.0, 6),
            "average_winner": round(sum(winners) / len(winners), 6) if winners else 0.0,
            "average_loser": round(sum(losers) / len(losers), 6) if losers else 0.0,
            "median_return": round(median(net), 6) if net else 0.0,
            "gross_return_before_costs": round(sum(gross) / len(gross), 6) if gross else 0.0,
            "net_return_after_costs": round(sum(net) / len(net), 6) if net else 0.0,
            "profit_factor": round((gross_profit / gross_loss_abs), 6) if gross_loss_abs > 0 else 0.0,
        }

    def _cost_drag(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        total_drag_values = [
            float(item.get("gross_realized_return_pct", 0.0) or 0.0)
            - float(item.get("realized_return_pct", 0.0) or 0.0)
            for item in outcomes
        ]
        gross_positive_net_negative = sum(
            1
            for item in outcomes
            if float(item.get("gross_realized_return_pct", 0.0) or 0.0) > 0
            and float(item.get("realized_return_pct", 0.0) or 0.0) < 0
        )
        return {
            "gross_return_before_costs": round(
                sum(float(item.get("gross_realized_return_pct", 0.0) or 0.0) for item in outcomes) / len(outcomes),
                6,
            )
            if outcomes
            else 0.0,
            "net_return_after_costs": round(
                sum(float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes) / len(outcomes),
                6,
            )
            if outcomes
            else 0.0,
            "total_cost_drag": round(sum(total_drag_values) / len(total_drag_values), 6) if total_drag_values else 0.0,
            "average_cost_per_decision": round(sum(total_drag_values) / len(total_drag_values), 6) if total_drag_values else 0.0,
            "gross_positive_net_negative_count": gross_positive_net_negative,
        }

    def _symbol_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in outcomes:
            symbol = str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "")
            if symbol:
                groups[symbol].append(item)
        rows = [self._group_row("symbol", symbol, rows) for symbol, rows in groups.items()]
        rows.sort(key=lambda item: (item["net_return_after_costs"], item["win_rate"], -item["drawdown"]), reverse=True)
        sufficient = [item for item in rows if item["sample_size"] >= 20]
        total_loss = abs(sum(item["net_return_after_costs"] for item in rows if item["net_return_after_costs"] < 0))
        worst_three_loss = abs(sum(item["net_return_after_costs"] for item in rows[-3:] if item["net_return_after_costs"] < 0))
        return {
            "best_10": rows[:10],
            "worst_10": list(reversed(rows[-10:])),
            "symbols_with_enough_sample": sufficient,
            "losses_concentrated_in_small_symbol_set": bool(total_loss > 0 and worst_three_loss / total_loss >= 0.5),
        }

    def _bucket_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        groups: dict[str, dict[str, list[dict[str, Any]]]] = {
            "by_month": defaultdict(list),
            "by_trade_count_bucket": defaultdict(list),
            "by_pullback_depth_bucket": defaultdict(list),
            "by_discovery_score_bucket": defaultdict(list),
            "by_movement_bucket": defaultdict(list),
            "by_rank_bucket": defaultdict(list),
        }
        for item in outcomes:
            evaluated_at = self._to_datetime(item.get("evaluated_at"))
            proposal = dict(item.get("proposal_context", {}) or {})
            if evaluated_at is not None:
                groups["by_month"][evaluated_at.strftime("%Y-%m")].append(item)
            trade_count = proposal.get("trade_count")
            if trade_count is not None:
                groups["by_trade_count_bucket"][self._bucket_trade_count(int(trade_count or 0))].append(item)
            movement = proposal.get("movement_pct")
            if movement is not None:
                movement_value = float(movement or 0.0)
                groups["by_pullback_depth_bucket"][self._bucket_movement(movement_value)].append(item)
                groups["by_movement_bucket"][self._bucket_movement(movement_value)].append(item)
            discovery = proposal.get("discovery_score")
            if discovery is not None:
                groups["by_discovery_score_bucket"][self._bucket_discovery(float(discovery or 0.0))].append(item)
            signal_rank = proposal.get("signal_rank")
            if signal_rank is not None:
                groups["by_rank_bucket"][self._bucket_signal_rank(int(signal_rank or 0))].append(item)
        return {
            section_name: [
                self._group_row("bucket", bucket, rows, label_key="period" if section_name == "by_month" else "bucket")
                for bucket, rows in sorted(section.items())
            ]
            for section_name, section in groups.items()
        }

    def _period_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        months: dict[str, list[float]] = defaultdict(list)
        holding_buckets: dict[str, list[float]] = defaultdict(list)
        for item in outcomes:
            evaluated_at = self._to_datetime(item.get("evaluated_at"))
            if evaluated_at is not None:
                months[evaluated_at.strftime("%Y-%m")].append(float(item.get("realized_return_pct", 0.0) or 0.0))
            minutes = int(item.get("checkpoint_minutes", 0) or 0)
            bucket = "intraday_<=60m" if minutes <= 60 else "swing_>60m"
            holding_buckets[bucket].append(float(item.get("realized_return_pct", 0.0) or 0.0))
        return {
            "by_month": [
                {"period": key, "sample_size": len(values), "net_return_after_costs": round(sum(values) / len(values), 6)}
                for key, values in sorted(months.items())
            ],
            "by_holding_bucket": [
                {"bucket": key, "sample_size": len(values), "net_return_after_costs": round(sum(values) / len(values), 6)}
                for key, values in holding_buckets.items()
            ],
        }

    def _entry_quality_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        buckets = {
            "discovery_score": defaultdict(list),
            "movement_pct": defaultdict(list),
            "trade_count": defaultdict(list),
            "signal_rank": defaultdict(list),
        }
        for item in outcomes:
            proposal = dict(item.get("proposal_context", {}) or {})
            net = float(item.get("realized_return_pct", 0.0) or 0.0)
            discovery = float(proposal.get("discovery_score", 0.0) or 0.0)
            movement = float(proposal.get("movement_pct", 0.0) or 0.0)
            trade_count = int(proposal.get("trade_count", 0) or 0)
            signal_rank = int(proposal.get("signal_rank", 0) or 0)
            buckets["discovery_score"][self._bucket_discovery(discovery)].append(net)
            buckets["movement_pct"][self._bucket_movement(movement)].append(net)
            buckets["trade_count"][self._bucket_trade_count(trade_count)].append(net)
            buckets["signal_rank"][self._bucket_signal_rank(signal_rank)].append(net)
        return {
            key: [
                {"bucket": bucket, "sample_size": len(values), "net_return_after_costs": round(sum(values) / len(values), 6)}
                for bucket, values in sorted(group.items())
            ]
            for key, group in buckets.items()
        }

    def _stop_target_diagnosis(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(str(item.get("outcome_status", "") or "") for item in outcomes)
        by_reason: dict[str, list[float]] = defaultdict(list)
        for item in outcomes:
            by_reason[str(item.get("outcome_status", "") or "")].append(float(item.get("realized_return_pct", 0.0) or 0.0))
        return {
            "target_hit_count": int(counts.get("target_hit", 0)),
            "stop_hit_count": int(counts.get("stop_hit", 0)),
            "time_exit_count": int(counts.get("time_exit", 0)),
            "ambiguous_count": int(counts.get("ambiguous_range", 0)),
            "average_return_by_exit_reason": {
                key: round(sum(values) / len(values), 6) if values else 0.0
                for key, values in by_reason.items()
            },
            "target_multiple_comment": "target_multiple may be unrealistic" if counts.get("time_exit", 0) > counts.get("target_hit", 0) else "target_multiple not obviously the main blocker",
            "stop_loss_comment": "stop_loss may be too tight" if counts.get("stop_hit", 0) > counts.get("target_hit", 0) else "stop_loss not obviously too tight",
        }

    def _profitability_requirement_diagnosis(
        self,
        *,
        distribution: dict[str, Any],
        cost_drag: dict[str, Any],
        stop_target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        current_win_rate = float(distribution.get("win_rate", 0.0) or 0.0)
        current_loss_rate = round(max(0.0, 1.0 - current_win_rate), 6)
        current_average_winner_pct = float(distribution.get("average_winner", 0.0) or 0.0)
        current_average_loser_pct = abs(float(distribution.get("average_loser", 0.0) or 0.0))
        average_cost_per_decision_pct = float(cost_drag.get("average_cost_per_decision", 0.0) or 0.0)
        current_profit_factor = float(distribution.get("profit_factor", 0.0) or 0.0)
        configured_stop_loss_pct = float((baseline.get("params_json", {}) or {}).get("stop_loss_pct", 0.0) or 0.0)
        configured_target_multiple = float((baseline.get("params_json", {}) or {}).get("target_multiple", 0.0) or 0.0)
        configured_target_return_pct = round(configured_stop_loss_pct * configured_target_multiple * 100.0, 6)
        required_average_winner_pct = self._safe_divide(
            current_loss_rate * current_average_loser_pct,
            current_win_rate,
        )
        required_average_winner_for_5pct_edge = (
            round(required_average_winner_pct * 1.05, 6) if required_average_winner_pct > 0 else 0.0
        )
        required_average_winner_for_10pct_edge = (
            round(required_average_winner_pct * 1.10, 6) if required_average_winner_pct > 0 else 0.0
        )
        required_win_rate = self._safe_divide(
            current_average_loser_pct,
            current_average_winner_pct + current_average_loser_pct,
        )
        cost_adjusted_required_average_winner_pct = round(
            required_average_winner_pct + average_cost_per_decision_pct,
            6,
        ) if required_average_winner_pct > 0 else average_cost_per_decision_pct
        average_winner_gap = round(current_average_winner_pct - required_average_winner_pct, 6)
        current_gap_to_required_average_winner_pct = round(
            current_average_winner_pct - cost_adjusted_required_average_winner_pct,
            6,
        )
        win_rate_gap = round(current_win_rate - required_win_rate, 6) if required_win_rate > 0 else 0.0
        realized_winners_too_small = (
            required_average_winner_pct > 0 and current_average_winner_pct < required_average_winner_pct
        )
        win_rate_too_low = required_win_rate > 0 and current_win_rate < required_win_rate
        profitability_verdict, most_actionable_next_fix, why = self._profitability_verdict(
            current_win_rate=current_win_rate,
            required_win_rate=required_win_rate,
            current_average_winner_pct=current_average_winner_pct,
            required_average_winner_pct=required_average_winner_pct,
            average_cost_per_decision_pct=average_cost_per_decision_pct,
            configured_target_return_pct=configured_target_return_pct,
            stop_target=stop_target,
        )
        observed_vs_required_summary = (
            f"Observed average winner {round(current_average_winner_pct, 6)}% vs required {round(required_average_winner_pct, 6)}%; "
            f"observed win rate {round(current_win_rate, 6)} vs required {round(required_win_rate, 6)}."
        )
        return {
            "section_title": "Profitability Requirement Diagnosis",
            "current_win_rate": round(current_win_rate, 6),
            "required_win_rate": round(required_win_rate, 6),
            "win_rate_gap": win_rate_gap,
            "current_average_winner_pct": round(current_average_winner_pct, 6),
            "required_average_winner_pct": round(required_average_winner_pct, 6),
            "required_average_winner_for_5pct_edge": required_average_winner_for_5pct_edge,
            "required_average_winner_for_10pct_edge": required_average_winner_for_10pct_edge,
            "average_winner_gap": average_winner_gap,
            "current_average_loser_pct": round(current_average_loser_pct, 6),
            "current_profit_factor": round(current_profit_factor, 6),
            "required_profit_factor": 1.0,
            "target_profit_factor": 1.1,
            "average_cost_per_decision_pct": round(average_cost_per_decision_pct, 6),
            "cost_adjusted_required_average_winner_pct": round(cost_adjusted_required_average_winner_pct, 6),
            "current_gap_to_required_average_winner_pct": current_gap_to_required_average_winner_pct,
            "configured_stop_loss_pct": round(configured_stop_loss_pct * 100.0, 6),
            "configured_target_multiple": round(configured_target_multiple, 6),
            "configured_target_return_pct": configured_target_return_pct,
            "observed_average_winner_is_net_of_costs": True,
            "observed_average_loser_is_net_of_costs": True,
            "realized_winners_too_small": realized_winners_too_small,
            "win_rate_too_low": win_rate_too_low,
            "observed_vs_required_summary": observed_vs_required_summary,
            "profitability_verdict": profitability_verdict,
            "most_actionable_next_fix": most_actionable_next_fix,
            "why": why,
        }

    def _profitability_verdict(
        self,
        *,
        current_win_rate: float,
        required_win_rate: float,
        current_average_winner_pct: float,
        required_average_winner_pct: float,
        average_cost_per_decision_pct: float,
        configured_target_return_pct: float,
        stop_target: dict[str, Any],
    ) -> tuple[str, str, str]:
        if current_win_rate <= 0 or current_average_winner_pct <= 0 or required_average_winner_pct <= 0:
            return (
                "insufficient_data",
                "Collect more valid winners and losers before changing snapback economics.",
                "The profitability requirement math needs both positive winners and non-zero loss observations.",
            )
        winners_too_small = current_average_winner_pct < required_average_winner_pct
        win_rate_too_low = current_win_rate < required_win_rate
        time_exits = int(stop_target.get("time_exit_count", 0) or 0)
        target_hits = int(stop_target.get("target_hit_count", 0) or 0)
        if (
            configured_target_return_pct > 0
            and current_average_winner_pct < configured_target_return_pct
            and time_exits > target_hits
        ):
            return (
                "target_exit_logic_problem",
                "Diagnose time exits and target achievement before adding more entry filters.",
                "Configured target is theoretically high enough, but realised winners are materially smaller and time exits dominate target hits.",
            )
        if average_cost_per_decision_pct >= max(0.0, required_average_winner_pct - current_average_winner_pct):
            return (
                "costs_dominate_small_edge",
                "Reduce cost drag or require materially larger winners before broadening snapback.",
                "The remaining gap to break-even is small enough that trading friction can dominate the edge.",
            )
        if winners_too_small and win_rate_too_low:
            return (
                "both_win_rate_and_winner_size_too_weak",
                "Diagnose exit logic and target achievement before adding more filters.",
                "Observed winners are too small and the hit rate is below break-even requirements.",
            )
        if winners_too_small:
            return (
                "winner_size_too_small",
                "Diagnose exit logic and target achievement before adding more filters.",
                "Observed average winner is below the break-even requirement.",
            )
        if win_rate_too_low:
            return (
                "win_rate_too_low",
                "Improve entry quality before changing risk or promotion thresholds.",
                "Observed win rate is below the break-even requirement even with current winner size.",
            )
        return (
            "break_even_requirements_met",
            "The economics are near break-even; validate stability before expanding the grid.",
            "Observed winner size and hit rate meet the simple break-even requirement.",
        )

    def _time_exit_and_target_achievement_diagnosis(
        self,
        *,
        outcomes: list[dict[str, Any]],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        if not outcomes:
            return {
                "section_title": "Time Exit and Target Achievement Diagnosis",
                "exit_reason_breakdown": [],
                "holding_window_diagnostics_available": False,
                "exit_verdict": "insufficient_exit_diagnostics",
                "most_actionable_next_fix": "Collect more exit outcomes before changing snapback exit logic.",
                "why": "No outcomes were available for exit analysis.",
            }
        total = len(outcomes)
        total_net = sum(float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes)
        by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in outcomes:
            by_reason[str(item.get("outcome_status", "") or "unknown")].append(item)
        exit_reason_breakdown = [
            self._exit_reason_row(
                exit_reason=reason,
                rows=rows,
                total_decisions=total,
                total_net_return=total_net,
            )
            for reason, rows in sorted(by_reason.items())
        ]
        time_exit_rows = list(by_reason.get("time_exit", []))
        target_rows = list(by_reason.get("target_hit", []))
        stop_rows = list(by_reason.get("stop_hit", []))
        time_exit_quality = self._time_exit_quality(time_exit_rows)
        target_achievement = self._target_achievement(target_rows)
        stop_damage = self._stop_damage(stop_rows)
        holding_window = self._holding_window_sensitivity(outcomes)
        exit_verdict, next_fix, why = self._exit_verdict(
            time_exit_quality=time_exit_quality,
            target_achievement=target_achievement,
            stop_damage=stop_damage,
            holding_window=holding_window,
            baseline=baseline,
        )
        return {
            "section_title": "Time Exit and Target Achievement Diagnosis",
            "exit_reason_breakdown": exit_reason_breakdown,
            "time_exit_quality": time_exit_quality,
            "target_achievement": target_achievement,
            "stop_damage": stop_damage,
            "holding_window_sensitivity": holding_window,
            "holding_window_diagnostics_available": bool(holding_window.get("available")),
            "time_exit_quality_summary": time_exit_quality.get("summary", "time_exit diagnostics unavailable"),
            "target_achievement_summary": target_achievement.get("summary", "target diagnostics unavailable"),
            "stop_damage_summary": stop_damage.get("summary", "stop diagnostics unavailable"),
            "exit_verdict": exit_verdict,
            "most_actionable_next_fix": next_fix,
            "why": why,
        }

    def _exit_reason_row(
        self,
        *,
        exit_reason: str,
        rows: list[dict[str, Any]],
        total_decisions: int,
        total_net_return: float,
    ) -> dict[str, Any]:
        net = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in rows]
        gross = [float(item.get("gross_realized_return_pct", 0.0) or 0.0) for item in rows]
        costs = [
            float(item.get("gross_realized_return_pct", 0.0) or 0.0)
            - float(item.get("realized_return_pct", 0.0) or 0.0)
            for item in rows
        ]
        winners = [value for value in net if value > 0]
        return {
            "exit_reason": exit_reason,
            "count": len(rows),
            "pct_of_decisions": round((len(rows) / total_decisions), 6) if total_decisions else 0.0,
            "win_rate": round((len(winners) / len(rows)), 6) if rows else 0.0,
            "average_return": round(sum(net) / len(net), 6) if net else 0.0,
            "median_return": round(median(net), 6) if net else 0.0,
            "gross_return_before_costs": round(sum(gross) / len(gross), 6) if gross else 0.0,
            "net_return_after_costs": round(sum(net) / len(net), 6) if net else 0.0,
            "average_cost": round(sum(costs) / len(costs), 6) if costs else 0.0,
            "contribution_to_total_net_return": round(sum(net), 6),
            "contribution_share_of_total_net_return": round((sum(net) / total_net_return), 6)
            if total_net_return
            else 0.0,
        }

    def _time_exit_quality(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "summary": "No time exits available."}
        net = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in rows]
        winners = [value for value in net if value > 0]
        losers = [value for value in net if value < 0]
        mfe = [float(item.get("max_favorable_excursion_pct", 0.0) or 0.0) for item in rows if item.get("max_favorable_excursion_pct") is not None]
        mae = [float(item.get("max_adverse_excursion_pct", 0.0) or 0.0) for item in rows if item.get("max_adverse_excursion_pct") is not None]
        distance_to_target = [
            round(
                float((item.get("proposal_context", {}) or {}).get("target_return_pct", 0.0) or 0.0)
                - float(item.get("realized_return_pct", 0.0) or 0.0),
                6,
            )
            for item in rows
            if (item.get("proposal_context", {}) or {}).get("target_return_pct") is not None
        ]
        distance_to_stop = [
            round(
                float(item.get("realized_return_pct", 0.0) or 0.0)
                + abs(float((item.get("proposal_context", {}) or {}).get("risk_pct", 0.0) or 0.0)),
                6,
            )
            for item in rows
            if (item.get("proposal_context", {}) or {}).get("risk_pct") is not None
        ]
        summary = (
            f"time_exit count={len(rows)}, win_rate={round(len(winners) / len(rows), 6)}, "
            f"avg_return={round(sum(net) / len(net), 6)}, avg_mfe={round(sum(mfe) / len(mfe), 6) if mfe else 'unavailable'}."
        )
        return {
            "count": len(rows),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / len(rows), 6) if rows else 0.0,
            "average_return": round(sum(net) / len(net), 6) if net else 0.0,
            "median_return": round(median(net), 6) if net else 0.0,
            "average_max_favorable_excursion_pct": round(sum(mfe) / len(mfe), 6) if mfe else None,
            "average_max_adverse_excursion_pct": round(sum(mae) / len(mae), 6) if mae else None,
            "average_distance_to_target_at_exit_pct": round(sum(distance_to_target) / len(distance_to_target), 6)
            if distance_to_target
            else None,
            "average_distance_to_stop_at_exit_pct": round(sum(distance_to_stop) / len(distance_to_stop), 6)
            if distance_to_stop
            else None,
            "summary": summary,
        }

    def _target_achievement(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "summary": "No target hits available."}
        durations = [self._minutes_between(item.get("replay_timestamp"), item.get("evaluated_at")) for item in rows]
        valid_durations = [value for value in durations if value is not None]
        symbols = Counter(str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "") for item in rows)
        periods = Counter(
            self._to_datetime(item.get("evaluated_at")).strftime("%Y-%m")
            for item in rows
            if self._to_datetime(item.get("evaluated_at")) is not None
        )
        returns = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in rows]
        summary = (
            f"target_hit count={len(rows)}, avg_time_to_target={round(sum(valid_durations) / len(valid_durations), 6) if valid_durations else 'unavailable'}, "
            f"top_symbol={symbols.most_common(1)[0][0] if symbols else 'unknown'}."
        )
        return {
            "count": len(rows),
            "average_time_to_target_minutes": round(sum(valid_durations) / len(valid_durations), 6) if valid_durations else None,
            "median_time_to_target_minutes": round(median(valid_durations), 6) if valid_durations else None,
            "average_return": round(sum(returns) / len(returns), 6) if returns else 0.0,
            "median_return": round(median(returns), 6) if returns else 0.0,
            "symbols_with_most_target_hits": [{"symbol": symbol, "count": count} for symbol, count in symbols.most_common(5) if symbol],
            "periods_with_most_target_hits": [{"period": period, "count": count} for period, count in periods.most_common(5)],
            "summary": summary,
        }

    def _stop_damage(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "summary": "No stop hits available."}
        returns = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in rows]
        symbols = Counter(str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "") for item in rows)
        trade_count_buckets: dict[str, list[float]] = defaultdict(list)
        movement_buckets: dict[str, list[float]] = defaultdict(list)
        for item in rows:
            proposal = dict(item.get("proposal_context", {}) or {})
            trade_count_buckets[self._bucket_trade_count(int(proposal.get("trade_count", 0) or 0))].append(
                float(item.get("realized_return_pct", 0.0) or 0.0)
            )
            movement_buckets[self._bucket_movement(float(proposal.get("movement_pct", 0.0) or 0.0))].append(
                float(item.get("realized_return_pct", 0.0) or 0.0)
            )
        summary = (
            f"stop_hit count={len(rows)}, avg_return={round(sum(returns) / len(returns), 6)}, "
            f"top_symbol={symbols.most_common(1)[0][0] if symbols else 'unknown'}."
        )
        return {
            "count": len(rows),
            "average_stop_loss": round(sum(returns) / len(returns), 6) if returns else 0.0,
            "median_stop_loss": round(median(returns), 6) if returns else 0.0,
            "symbols_with_most_stop_hits": [{"symbol": symbol, "count": count} for symbol, count in symbols.most_common(5) if symbol],
            "trade_count_buckets": [
                {"bucket": bucket, "count": len(values), "average_return": round(sum(values) / len(values), 6)}
                for bucket, values in sorted(trade_count_buckets.items())
            ],
            "movement_buckets": [
                {"bucket": bucket, "count": len(values), "average_return": round(sum(values) / len(values), 6)}
                for bucket, values in sorted(movement_buckets.items())
            ],
            "summary": summary,
        }

    def _holding_window_sensitivity(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        windows: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in outcomes:
            minutes = int(item.get("checkpoint_minutes", 0) or 0)
            if minutes > 0:
                windows[minutes].append(item)
        rows = []
        for minutes, entries in sorted(windows.items()):
            realized = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in entries]
            winners = [value for value in realized if value > 0]
            losers = [value for value in realized if value < 0]
            rows.append(
                {
                    "holding_window_minutes": minutes,
                    "sample_size": len(entries),
                    "target_hit_count": sum(1 for item in entries if str(item.get("outcome_status", "")) == "target_hit"),
                    "stop_hit_count": sum(1 for item in entries if str(item.get("outcome_status", "")) == "stop_hit"),
                    "time_exit_count": sum(1 for item in entries if str(item.get("outcome_status", "")) == "time_exit"),
                    "win_rate": round(len(winners) / len(entries), 6) if entries else 0.0,
                    "average_winner": round(sum(winners) / len(winners), 6) if winners else 0.0,
                    "average_loser": round(sum(losers) / len(losers), 6) if losers else 0.0,
                    "net_return_after_costs": round(sum(realized) / len(realized), 6) if realized else 0.0,
                    "drawdown": round(
                        sum(abs(float(item.get("max_adverse_excursion_pct", 0.0) or 0.0)) for item in entries) / len(entries),
                        6,
                    ) if entries else None,
                }
            )
        return {
            "available": len(rows) > 0,
            "windows": rows,
            "note": "Uses replay checkpoint windows already present in the baseline evaluation; no new execution logic was added.",
        }

    def _exit_verdict(
        self,
        *,
        time_exit_quality: dict[str, Any],
        target_achievement: dict[str, Any],
        stop_damage: dict[str, Any],
        holding_window: dict[str, Any],
        baseline: dict[str, Any],
    ) -> tuple[str, str, str]:
        if not time_exit_quality.get("count") and not target_achievement.get("count") and not stop_damage.get("count"):
            return (
                "insufficient_exit_diagnostics",
                "Collect more exit outcomes before changing snapback exit logic.",
                "No meaningful exit breakdown was available.",
            )
        target_multiple = float((baseline.get("params_json", {}) or {}).get("target_multiple", 0.0) or 0.0)
        time_exit_count = int(time_exit_quality.get("count", 0) or 0)
        time_exit_avg = float(time_exit_quality.get("average_return", 0.0) or 0.0)
        target_hit_count = int(target_achievement.get("count", 0) or 0)
        stop_hit_count = int(stop_damage.get("count", 0) or 0)
        distance_to_target = time_exit_quality.get("average_distance_to_target_at_exit_pct")
        windows = list(holding_window.get("windows", []) or [])
        best_window = max(windows, key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0)) if windows else None
        current_window = next((item for item in windows if int(item.get("holding_window_minutes", 0) or 0) == 60), None)
        if best_window and current_window:
            if int(best_window.get("holding_window_minutes", 0) or 0) > 60 and float(best_window.get("net_return_after_costs", 0.0) or 0.0) > float(current_window.get("net_return_after_costs", 0.0) or 0.0):
                return (
                    "holding_window_too_short",
                    "Retest a longer holding window before changing entry filters.",
                    "A longer existing replay checkpoint window looks less bad than the current one-hour hold.",
                )
            if int(best_window.get("holding_window_minutes", 0) or 0) < 60 and float(best_window.get("net_return_after_costs", 0.0) or 0.0) > float(current_window.get("net_return_after_costs", 0.0) or 0.0):
                return (
                    "holding_window_too_long",
                    "Retest a shorter holding window before changing entry filters.",
                    "A shorter existing replay checkpoint window looks less bad than the current one-hour hold.",
                )
        if time_exit_count > target_hit_count and time_exit_avg < 0 and distance_to_target is not None and distance_to_target > 0.4:
            return (
                "target_too_far",
                "Retest target achievement and time exits before adding more entry filters.",
                "Time exits are frequent, negative on average, and still meaningfully short of the configured target.",
            )
        if stop_hit_count > target_hit_count and float(stop_damage.get("average_stop_loss", 0.0) or 0.0) < -1.0:
            return (
                "stop_too_tight",
                "Review stop placement before widening the variant grid.",
                "Stop losses outnumber target hits and remain meaningfully damaging.",
            )
        if time_exit_count > max(target_hit_count, stop_hit_count):
            return (
                "time_exit_too_frequent",
                "Diagnose time exits and target achievement before adding more entry filters.",
                "Time exits are the single most common resolution path.",
            )
        return (
            "exit_logic_no_clear_fix",
            "No single exit tweak is obviously dominant; avoid changing live or paper policy from this evidence alone.",
            f"Target multiple {target_multiple} and current exit mix do not point to one clean fix.",
        )

    def _minutes_between(self, start_value: Any, end_value: Any) -> float | None:
        start = self._to_datetime(start_value)
        end = self._to_datetime(end_value)
        if start is None or end is None:
            return None
        return round((end - start).total_seconds() / 60.0, 6)

    def _safe_divide(self, numerator: float, denominator: float) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 6)

    def _verdict(
        self,
        *,
        base_strategy_id: str,
        distribution: dict[str, Any],
        cost_drag: dict[str, Any],
        symbol_breakdown: dict[str, Any],
        entry_quality: dict[str, Any],
        stop_target: dict[str, Any],
    ) -> tuple[str, str, str]:
        is_snapback = base_strategy_id == "mean_reversion.snapback"
        labels = {
            "cost": "snapback_cost_problem" if is_snapback else "cost_problem",
            "symbol": "snapback_symbol_filter_problem" if is_snapback else "symbol_filter_problem",
            "exit": "snapback_exit_logic_problem" if is_snapback else "exit_logic_problem",
            "entry": "snapback_entry_quality_problem" if is_snapback else "entry_quality_problem",
            "none": "snapback_no_edge_detected" if is_snapback else "no_edge_detected",
        }
        if int(distribution.get("total_decisions", 0) or 0) <= 0:
            return (
                "insufficient_diagnostics",
                "Regenerate a baseline replay with decisions before changing strategy logic.",
                "No decisions were available for diagnosis.",
            )
        if int(cost_drag.get("gross_positive_net_negative_count", 0) or 0) > max(10, int(distribution.get("total_decisions", 0) or 0) // 20):
            return (
                labels["cost"],
                "Raise the minimum expected edge before changing the strategy family.",
                "A meaningful share of gross-positive trades become net-negative after costs.",
            )
        if bool((symbol_breakdown.get("losses_concentrated_in_small_symbol_set", False))):
            return (
                labels["symbol"],
                "Add symbol allow/deny filtering before changing the core strategy logic.",
                "A small subset of symbols appears to drive a disproportionate share of losses.",
            )
        time_exits = int(stop_target.get("time_exit_count", 0) or 0)
        target_hits = int(stop_target.get("target_hit_count", 0) or 0)
        stop_hits = int(stop_target.get("stop_hit_count", 0) or 0)
        if time_exits > target_hits and time_exits > stop_hits:
            return (
                labels["exit"],
                "Review the holding window and target expectations before broadening the variant grid.",
                "Timeout exits dominate the sample, suggesting the current exit logic is not capturing enough follow-through.",
            )
        movement_rows = list((entry_quality.get("movement_pct", []) or []))
        if movement_rows:
            best_bucket = max(movement_rows, key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0))
            worst_bucket = min(movement_rows, key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0))
            if best_bucket.get("bucket") != worst_bucket.get("bucket"):
                return (
                    labels["entry"],
                    "Tighten entry-quality filters around the better-performing pullback bucket.",
                    "Return quality varies meaningfully across entry buckets, so candidate quality looks more important than the current grid.",
                )
        return (
            labels["none"],
            "Retire this strategy for now unless a distinct symbol or regime edge emerges.",
            "No bucket shows a durable positive edge after costs.",
        )

    def _group_row(
        self,
        row_type: str,
        label: str,
        rows: list[dict[str, Any]],
        *,
        label_key: str | None = None,
    ) -> dict[str, Any]:
        net = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in rows]
        wins = [value for value in net if value > 0]
        losses = [value for value in net if value < 0]
        drawdowns = [abs(float(item.get("max_adverse_excursion_pct", 0.0) or 0.0)) for item in rows]
        counts = Counter(str(item.get("outcome_status", "") or "") for item in rows)
        payload = {
            "sample_size": len(rows),
            "net_return_after_costs": round(sum(net) / len(net), 6) if net else 0.0,
            "win_rate": round(len(wins) / len(rows), 6) if rows else 0.0,
            "average_winner": round(sum(wins) / len(wins), 6) if wins else 0.0,
            "average_loser": round(sum(losses) / len(losses), 6) if losses else 0.0,
            "target_hit_count": int(counts.get("target_hit", 0)),
            "stop_hit_count": int(counts.get("stop_hit", 0)),
            "time_exit_count": int(counts.get("time_exit", 0)),
            "drawdown": round(sum(drawdowns) / len(drawdowns), 6) if drawdowns else None,
        }
        payload[label_key or row_type] = label
        return payload

    def _subset_edge_verdict(
        self,
        *,
        symbol_breakdown: dict[str, Any],
        bucket_breakdown: dict[str, Any],
    ) -> dict[str, Any]:
        enough_symbols = list(symbol_breakdown.get("symbols_with_enough_sample", []) or [])
        best_symbols = [item for item in enough_symbols if float(item.get("net_return_after_costs", 0.0) or 0.0) > 0]
        if not enough_symbols:
            return {
                "verdict": "insufficient_subset_data",
                "most_actionable_next_fix": "Collect more targeted variant outcomes before trusting subset filters.",
                "why": "No symbol had enough sample size to support a subset-edge recommendation.",
            }
        if best_symbols:
            top_symbol = max(best_symbols, key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0))
            if int(top_symbol.get("sample_size", 0) or 0) >= 20 and float(top_symbol.get("win_rate", 0.0) or 0.0) >= 0.5:
                return {
                    "verdict": "symbol_filter_promising",
                    "most_actionable_next_fix": "Validate whether the best symbols stay positive across adjacent months before adding any symbol filter.",
                    "why": "At least one symbol shows positive after-cost returns with a non-trivial sample and acceptable hit rate.",
                }
        candidates = {
            "trade_count_filter_promising": self._best_bucket(bucket_breakdown.get("by_trade_count_bucket", [])),
            "pullback_depth_filter_promising": self._best_bucket(bucket_breakdown.get("by_pullback_depth_bucket", [])),
            "score_filter_promising": self._best_bucket(bucket_breakdown.get("by_discovery_score_bucket", [])),
            "regime_filter_promising": self._best_bucket(bucket_breakdown.get("by_month", [])),
        }
        for verdict, bucket in candidates.items():
            if bucket and int(bucket.get("sample_size", 0) or 0) >= 25 and float(bucket.get("net_return_after_costs", 0.0) or 0.0) > 0:
                return {
                    "verdict": verdict,
                    "most_actionable_next_fix": f"Retest the positive bucket {bucket.get('bucket', bucket.get('period', '-'))} against neighboring buckets before creating any filter.",
                    "why": "One subset bucket is positive after costs with a usable sample, but still needs stability checks.",
                }
        return {
            "verdict": "no_clear_subset_edge",
            "most_actionable_next_fix": "Focus on improving exit economics before expanding the variant grid.",
            "why": "No symbol or regime bucket shows a clearly robust positive after-cost edge.",
        }

    def _best_bucket(self, rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        usable = [item for item in list(rows or []) if int(item.get("sample_size", 0) or 0) > 0]
        if not usable:
            return None
        return max(usable, key=lambda item: float(item.get("net_return_after_costs", 0.0) or 0.0))

    def _bucket_discovery(self, value: float) -> str:
        if value < 4.0:
            return "<4.0"
        if value < 5.0:
            return "4.0-4.99"
        return ">=5.0"

    def _bucket_movement(self, value: float) -> str:
        if value > -0.20:
            return "shallow_-0.18_to_-0.199"
        if value > -0.30:
            return "mid_-0.20_to_-0.299"
        return "deep_<=-0.30"

    def _bucket_trade_count(self, value: int) -> str:
        if value < 50:
            return "<50"
        if value < 100:
            return "50-99"
        return ">=100"

    def _bucket_signal_rank(self, value: int) -> str:
        if value <= 1:
            return "rank_1"
        if value == 2:
            return "rank_2"
        return "rank_3_plus"

    def _empty_report(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        data_source: str,
        diagnosed_variant_id: str = "",
        baseline: dict[str, Any] | None = None,
        data_adequacy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "title": "Strategy Loss Diagnosis",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "data_source": data_source,
            "baseline_variant_id": str(((baseline or {}).get("variant_id", "")) or ""),
            "baseline_params_json": dict((baseline or {}).get("params_json", {}) or {}),
            "diagnosed_variant_id": diagnosed_variant_id,
            "diagnosed_params_json": {},
            "data_adequacy": dict(data_adequacy or {}),
            "return_distribution": {},
            "cost_drag": {},
            "symbol_breakdown": {"best_10": [], "worst_10": [], "symbols_with_enough_sample": []},
            "time_breakdown": {"by_month": [], "by_holding_bucket": []},
            "entry_quality_breakdown": {},
            "bucket_breakdown": {
                "by_month": [],
                "by_trade_count_bucket": [],
                "by_pullback_depth_bucket": [],
                "by_discovery_score_bucket": [],
                "by_movement_bucket": [],
                "by_rank_bucket": [],
            },
            "stop_target_diagnosis": {},
            "profitability_requirement_diagnosis": {
                "section_title": "Profitability Requirement Diagnosis",
                "profitability_verdict": "insufficient_data",
                "most_actionable_next_fix": "Regenerate the baseline evaluation read-only before diagnosing profitability requirements.",
            },
            "subset_edge_diagnosis": {
                "verdict": "insufficient_subset_data",
                "most_actionable_next_fix": "Regenerate the targeted variant read-only before diagnosing subset edge.",
                "why": "No baseline decisions were available.",
            },
            "verdict": "insufficient_diagnostics",
            "most_actionable_next_fix": "Regenerate the baseline evaluation read-only before diagnosing losses.",
            "why": "No baseline decisions were available.",
            "safety_statement": "Research-only loss diagnosis. No paper or live approval has been changed.",
        }

    def _to_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        return datetime.fromisoformat(str(value))
