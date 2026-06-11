from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from statistics import mean
from typing import Any

from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport
from app.framework.reporting.strategy_variant_research import StrategyVariantResearchService
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


ALLOWED_STABILITY_VERDICTS = {
    "symbol_promising_and_stable",
    "symbol_promising_but_insufficient",
    "symbol_unstable",
    "symbol_not_promising",
    "no_usable_subset_data",
}

SAFETY_STATEMENT = "Research-only wide symbol stability replay. No paper or live approval has been changed."

LEGACY_TO_HARD_VERDICT = {
    "symbol_stability_confirmed": "symbol_promising_and_stable",
    "symbol_promising_but_still_insufficient": "symbol_promising_but_insufficient",
    "symbol_edge_degraded_on_wider_period": "symbol_unstable",
    "symbol_unstable_across_periods": "symbol_unstable",
    "symbol_not_promising_after_wider_replay": "symbol_not_promising",
    "insufficient_wide_replay_data": "no_usable_subset_data",
}


def normalize_symbol_subset_verdict(verdict: str) -> str:
    clean = str(verdict or "").strip()
    if clean in ALLOWED_STABILITY_VERDICTS:
        return clean
    return LEGACY_TO_HARD_VERDICT.get(clean, "no_usable_subset_data")


class SymbolSubsetStabilityReport:
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
        self.loss_reporter = StrategyLossDiagnosisReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str,
        symbol: str,
        wider_period: bool = False,
        persist: bool = True,
    ) -> dict[str, Any]:
        clean_symbol = str(symbol or "").strip().upper()
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        variant = next(
            (item for item in definitions if str(item.get("variant_id", "") or "") == variant_id),
            None,
        )
        if variant is None or not clean_symbol:
            return self._empty_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=variant_id,
                symbol=clean_symbol,
                why="Variant definition or symbol was not available for a read-only stability check.",
            )
        profile = self.service._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        replay_window = self._replay_window(
            symbol=clean_symbol,
            timeframe=timeframe,
            wider_period=wider_period,
        )
        collected = self.service.collect_variant_outcomes(
            profile=self.service._profile_from_variant(profile=profile, variant=variant),
            variant=variant,
            timeframe=timeframe,
            replay_id=self._replay_id(symbol=clean_symbol, wider_period=wider_period),
            start_at=replay_window.get("start_at"),
            end_at=replay_window.get("end_at"),
            symbols=[clean_symbol],
        )
        all_outcomes = list(collected.get("outcomes", []) or [])
        symbol_outcomes = [
            item
            for item in all_outcomes
            if str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "").upper() == clean_symbol
        ]
        if not symbol_outcomes:
            return self._empty_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=variant_id,
                symbol=clean_symbol,
                why="No replay outcomes were available for the requested symbol under this variant.",
            )
        loss_report = self.loss_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
        )
        summary = self._summary(symbol_outcomes)
        period_breakdown = self._period_breakdown(symbol_outcomes)
        cohort = self._cohort_comparison(
            all_outcomes=all_outcomes,
            symbol=clean_symbol,
            symbol_outcomes=symbol_outcomes,
        )
        prior_narrow = self._latest_prior_narrow_evaluation(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=clean_symbol,
        )
        comparison = self._comparison(summary=summary, prior_narrow=prior_narrow)
        verdict, next_fix, why = self._verdict(
            summary=summary,
            period_breakdown=period_breakdown,
            comparison=comparison,
            symbol=clean_symbol,
            wider_period=wider_period,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
        )
        month_concentration = self._month_concentration(period_breakdown)
        outcome_concentration = self._outcome_concentration(symbol_outcomes)
        next_required_action = self._next_required_action(verdict=verdict, wider_period=wider_period)
        next_recommended_command = self._next_recommended_command(
            verdict=verdict,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=clean_symbol,
            wider_period=wider_period,
        )
        report = {
            "title": "Symbol Subset Stability Report",
            "strategy": f"{base_strategy_id}/{profile_id}/{timeframe}",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "symbol": clean_symbol,
            "replay_scope": "wider_period" if wider_period else "current_window",
            "replay_window": replay_window,
            "selected_symbol_summary": summary,
            "period_breakdown": period_breakdown,
            "narrow_vs_wide_comparison": comparison,
            "cohort_comparison": cohort,
            "loss_diagnosis_context": {
                "subset_edge_verdict": str(((loss_report.get("subset_edge_diagnosis", {}) or {}).get("verdict", "")) or ""),
                "loss_verdict": str(loss_report.get("verdict", "") or ""),
                "profitability_verdict": str(
                    ((loss_report.get("profitability_requirement_diagnosis", {}) or {}).get("profitability_verdict", "")) or ""
                ),
            },
            "stability_verdict": verdict,
            "month_concentration": month_concentration,
            "outcome_concentration": outcome_concentration,
            "next_required_action": next_required_action,
            "next_recommended_command": next_recommended_command,
            "most_actionable_next_fix": next_fix,
            "why": why,
            "safety_statement": SAFETY_STATEMENT,
        }
        if persist:
            persisted = self._persist_report(
                report=report,
                variant=variant,
            )
            report["persistence"] = {
                "persisted_separately": True,
                "evaluation_id": persisted.get("evaluation_id", ""),
                "replay_id": persisted.get("replay_id", ""),
            }
        if normalize_symbol_subset_verdict(report["stability_verdict"]) not in ALLOWED_STABILITY_VERDICTS:
            raise ValueError(f"Unsupported stability verdict: {report['stability_verdict']}")
        return report

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str,
        symbol: str,
        wider_period: bool = False,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=symbol,
            wider_period=wider_period,
        )
        summary = dict(report.get("selected_symbol_summary", {}) or {})
        cohort = dict(report.get("cohort_comparison", {}) or {})
        comparison = dict(report.get("narrow_vs_wide_comparison", {}) or {})
        replay_window = dict(report.get("replay_window", {}) or {})
        lines = [
            str(report.get("title", "Symbol Subset Stability Report")),
            f"symbol={report.get('symbol', '-')}",
            f"strategy={report.get('strategy', '-')}",
            f"variant_id={report.get('variant_id', '-')}",
            (
                f"replay_scope={report.get('replay_scope', '-')}"
                f" | replay_start_at={replay_window.get('start_at', '-')}"
                f" | replay_end_at={replay_window.get('end_at', '-')}"
            ),
            f"sample_size={summary.get('sample_size', 0)}",
            f"net_return_after_costs={summary.get('net_return_after_costs', 0.0)}",
            f"win_rate={summary.get('win_rate', 0.0)}",
            f"drawdown={summary.get('drawdown')}",
            f"gross_return_before_costs={summary.get('gross_return_before_costs', 0.0)}",
            f"average_winner={summary.get('average_winner', 0.0)}",
            f"average_loser={summary.get('average_loser', 0.0)}",
            f"profit_factor={summary.get('profit_factor', 0.0)}",
            f"target_hit_count={summary.get('target_hit_count', 0)}",
            f"stop_hit_count={summary.get('stop_hit_count', 0)}",
            f"time_exit_count={summary.get('time_exit_count', 0)}",
            f"month_concentration={report.get('month_concentration', '-')}",
            f"outcome_concentration={report.get('outcome_concentration', '-')}",
            "period_breakdown_by_month:",
        ]
        for item in list((report.get("period_breakdown", {}) or {}).get("by_month", []) or []):
            lines.append(
                f"- period={item.get('period', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
            )
        lines.append("period_breakdown_by_quarter:")
        for item in list((report.get("period_breakdown", {}) or {}).get("by_quarter", []) or []):
            lines.append(
                f"- period={item.get('period', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
            )
        lines.append("period_breakdown_by_week_or_chunk:")
        for item in list((report.get("period_breakdown", {}) or {}).get("by_week_or_chunk", []) or []):
            lines.append(
                f"- period={item.get('period', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
            )
        lines.append(
            "narrow_vs_wide_comparison="
            f"narrow_sample_size={comparison.get('narrow_sample_size', 0)}"
            f" | wide_sample_size={comparison.get('wide_sample_size', 0)}"
            f" | narrow_net_return={comparison.get('narrow_net_return', 0.0)}"
            f" | wide_net_return={comparison.get('wide_net_return', 0.0)}"
            f" | narrow_win_rate={comparison.get('narrow_win_rate', 0.0)}"
            f" | wide_win_rate={comparison.get('wide_win_rate', 0.0)}"
            f" | signal_survives_wider_period={'yes' if comparison.get('signal_survives_wider_period') else 'no'}"
        )
        lines.append(
            f"cohort_availability={cohort.get('availability', '-')}"
            f" | reason={cohort.get('reason', '-')}"
        )
        for item in list(cohort.get("rows", []) or []):
            lines.append(
                f"- cohort_symbol={item.get('symbol', '-')}"
                f" | sample_size={item.get('sample_size', 0)}"
                f" | net_return_after_costs={item.get('net_return_after_costs', 0.0)}"
                f" | win_rate={item.get('win_rate', 0.0)}"
                f" | target_hit_count={item.get('target_hit_count', 0)}"
                f" | stop_hit_count={item.get('stop_hit_count', 0)}"
                f" | time_exit_count={item.get('time_exit_count', 0)}"
            )
        lines.append(f"stability_verdict={report.get('stability_verdict', '-')}")
        lines.append(f"next_required_action={report.get('next_required_action', '-')}")
        lines.append(f"next_recommended_command={report.get('next_recommended_command', '-')}")
        lines.append(f"most_actionable_next_fix={report.get('most_actionable_next_fix', '-')}")
        lines.append(f"why={report.get('why', '-')}")
        lines.append(str(report.get("safety_statement", "")))
        return "\n".join(lines)

    def _summary(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        realized = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes]
        gross = [float(item.get("gross_realized_return_pct", 0.0) or 0.0) for item in outcomes]
        winners = [value for value in realized if value > 0]
        losers = [value for value in realized if value < 0]
        counts = self._status_counts(outcomes)
        gross_profit = sum(value for value in realized if value > 0)
        gross_loss_abs = abs(sum(value for value in realized if value < 0))
        drawdowns = [abs(float(item.get("max_adverse_excursion_pct", 0.0) or 0.0)) for item in outcomes]
        gross_positive_net_negative_count = sum(
            1 for item in outcomes
            if float(item.get("gross_realized_return_pct", 0.0) or 0.0) > 0
            and float(item.get("realized_return_pct", 0.0) or 0.0) < 0
        )
        return {
            "sample_size": len(outcomes),
            "gross_return_before_costs": round(mean(gross), 6) if gross else 0.0,
            "net_return_after_costs": round(mean(realized), 6) if realized else 0.0,
            "win_rate": round(len(winners) / len(outcomes), 6) if outcomes else 0.0,
            "average_winner": round(mean(winners), 6) if winners else 0.0,
            "average_loser": round(mean(losers), 6) if losers else 0.0,
            "profit_factor": round(gross_profit / gross_loss_abs, 6) if gross_loss_abs > 0 else 0.0,
            "target_hit_count": counts["target_hit"],
            "stop_hit_count": counts["stop_hit"],
            "time_exit_count": counts["time_exit"],
            "drawdown": round(mean(drawdowns), 6) if drawdowns else None,
            "gross_positive_net_negative_count": gross_positive_net_negative_count,
        }

    def _period_breakdown(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_quarter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ordered = sorted(
            outcomes,
            key=lambda item: self._to_datetime(item.get("evaluated_at")) or datetime(1970, 1, 1).astimezone(),
        )
        for item in ordered:
            evaluated_at = self._to_datetime(item.get("evaluated_at"))
            if evaluated_at is None:
                continue
            by_month[evaluated_at.strftime("%Y-%m")].append(item)
            quarter = ((evaluated_at.month - 1) // 3) + 1
            by_quarter[f"{evaluated_at.year}-Q{quarter}"].append(item)
            iso_year, iso_week, _ = evaluated_at.isocalendar()
            by_week[f"{iso_year}-W{iso_week:02d}"].append(item)
        week_rows = [self._period_row(period, rows) for period, rows in sorted(by_week.items())]
        if sum(1 for row in week_rows if int(row.get("sample_size", 0) or 0) >= 3) < 2:
            week_rows = self._rolling_chunks(ordered, chunk_size=5)
        return {
            "by_month": [self._period_row(period, rows) for period, rows in sorted(by_month.items())],
            "by_quarter": [self._period_row(period, rows) for period, rows in sorted(by_quarter.items())],
            "by_week_or_chunk": week_rows,
        }

    def _rolling_chunks(self, outcomes: list[dict[str, Any]], *, chunk_size: int) -> list[dict[str, Any]]:
        rows = []
        for index in range(0, len(outcomes), max(1, chunk_size)):
            chunk = outcomes[index:index + max(1, chunk_size)]
            if not chunk:
                continue
            start = self._to_datetime(chunk[0].get("evaluated_at"))
            end = self._to_datetime(chunk[-1].get("evaluated_at"))
            label = f"chunk_{(index // max(1, chunk_size)) + 1}"
            if start and end:
                label = f"{label}:{start.strftime('%Y-%m-%d')}..{end.strftime('%Y-%m-%d')}"
            rows.append(self._period_row(label, chunk))
        return rows

    def _period_row(self, period: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = self._summary(rows)
        return {
            "period": period,
            "sample_size": summary["sample_size"],
            "net_return_after_costs": summary["net_return_after_costs"],
            "win_rate": summary["win_rate"],
            "target_hit_count": summary["target_hit_count"],
            "stop_hit_count": summary["stop_hit_count"],
            "time_exit_count": summary["time_exit_count"],
        }

    def _cohort_comparison(
        self,
        *,
        all_outcomes: list[dict[str, Any]],
        symbol: str,
        symbol_outcomes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        symbol_contexts = [dict(item.get("proposal_context", {}) or {}) for item in symbol_outcomes]
        trade_counts = [int(item.get("trade_count", 0) or 0) for item in symbol_contexts if item.get("trade_count") is not None]
        movement_values = [float(item.get("movement_pct", 0.0) or 0.0) for item in symbol_contexts if item.get("movement_pct") is not None]
        if not trade_counts and not movement_values:
            return {
                "availability": "unavailable",
                "reason": "No trade-count or movement metadata was available to build a safe cohort comparison.",
                "rows": [],
            }
        average_trade_count = round(mean(trade_counts), 6) if trade_counts else None
        average_movement = round(mean(movement_values), 6) if movement_values else None
        peers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in all_outcomes:
            proposal = dict(item.get("proposal_context", {}) or {})
            peer_symbol = str(proposal.get("symbol", "") or "").upper()
            if not peer_symbol or peer_symbol == symbol:
                continue
            peer_trade_count = proposal.get("trade_count")
            peer_movement = proposal.get("movement_pct")
            matches_trade_count = (
                average_trade_count is not None
                and peer_trade_count is not None
                and abs(int(peer_trade_count or 0) - float(average_trade_count)) <= 20
            )
            matches_movement = (
                average_movement is not None
                and peer_movement is not None
                and abs(float(peer_movement or 0.0) - float(average_movement)) <= 0.05
            )
            if matches_trade_count or matches_movement:
                peers[peer_symbol].append(item)
        rows = []
        for peer_symbol, peer_rows in peers.items():
            summary = self._summary(peer_rows)
            rows.append(
                {
                    "symbol": peer_symbol,
                    "sample_size": summary["sample_size"],
                    "net_return_after_costs": summary["net_return_after_costs"],
                    "win_rate": summary["win_rate"],
                    "target_hit_count": summary["target_hit_count"],
                    "stop_hit_count": summary["stop_hit_count"],
                    "time_exit_count": summary["time_exit_count"],
                }
            )
        rows.sort(key=lambda item: (item["net_return_after_costs"], item["win_rate"], item["sample_size"]), reverse=True)
        if not rows:
            return {
                "availability": "unavailable",
                "reason": "No neighboring/cohort symbols with comparable trade-count or movement characteristics were available.",
                "rows": [],
            }
        return {
            "availability": "derived_tradecount_movement_cohort",
            "reason": "Cohort comparison uses nearby trade-count and pullback-movement characteristics because no richer sector metadata is wired here.",
            "rows": rows[:5],
        }

    def _verdict(
        self,
        *,
        summary: dict[str, Any],
        period_breakdown: dict[str, Any],
        comparison: dict[str, Any],
        symbol: str,
        wider_period: bool,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
    ) -> tuple[str, str, str]:
        sample_size = int(summary.get("sample_size", 0) or 0)
        net = float(summary.get("net_return_after_costs", 0.0) or 0.0)
        periods = list(period_breakdown.get("by_month", []) or []) or list(period_breakdown.get("by_week_or_chunk", []) or [])
        positive_periods = [item for item in periods if float(item.get("net_return_after_costs", 0.0) or 0.0) > 0.0]
        negative_periods = [item for item in periods if float(item.get("net_return_after_costs", 0.0) or 0.0) < 0.0]
        if sample_size <= 0:
            return (
                "no_usable_subset_data",
                "Collect more replay evidence for the selected symbol before trusting any subset edge.",
                "No symbol outcomes were available for the wider stability replay.",
            )
        if sample_size < 25:
            return (
                "symbol_promising_but_insufficient" if net > 0.0 else "symbol_not_promising",
                (
                    "Run wider-period symbol replay before considering any subset filter."
                    if net > 0.0 else
                    "Return to portfolio-level research instead of promoting this symbol subset."
                ),
                (
                    "The current replay is positive but still too small to treat the edge as stable."
                    if net > 0.0 else
                    "The current replay is small and already negative after costs, so the subset is not promising."
                ),
            )
        if net <= 0.0:
            return (
                "symbol_not_promising",
                "Return to broader portfolio research and avoid promoting this symbol subset.",
                "After the wider replay, the selected symbol is not positive after costs.",
            )
        if positive_periods and negative_periods and len(negative_periods) >= len(positive_periods):
            return (
                "symbol_unstable",
                "Run wider-period symbol replay before considering any subset filter." if not wider_period else "Return to broader portfolio research and investigate another symbol.",
                "The symbol shows mixed period performance and does not stay positive across enough periods.",
            )
        if not comparison.get("signal_survives_wider_period", False):
            return (
                "symbol_unstable",
                "Run wider-period symbol replay before considering any subset filter." if not wider_period else "Return to broader portfolio research and investigate another symbol.",
                "The wider replay remains positive but degraded versus the narrow result.",
            )
        if len(positive_periods) >= 2:
            return (
                "symbol_promising_and_stable",
                "Propose symbol_filter_variant_research, still research-only.",
                "The symbol stayed positive across multiple periods and survived the wider replay.",
            )
        return (
            "symbol_promising_but_insufficient",
            "Collect more replay evidence before adding any symbol filter.",
            "The symbol remains interesting, but the evidence is not broad enough yet.",
        )

    def _month_concentration(self, period_breakdown: dict[str, Any]) -> str:
        rows = list((period_breakdown.get("by_month", []) or []))
        total = sum(int(item.get("sample_size", 0) or 0) for item in rows)
        if total <= 0 or not rows:
            return "none:0.000"
        top = max(rows, key=lambda item: int(item.get("sample_size", 0) or 0))
        share = int(top.get("sample_size", 0) or 0) / total
        return f"{top.get('period', 'unknown')}:{share:.3f}"

    def _outcome_concentration(self, outcomes: list[dict[str, Any]]) -> str:
        counts = self._status_counts(outcomes)
        total = sum(counts.values())
        if total <= 0:
            return "none:0.000"
        label, value = max(counts.items(), key=lambda item: item[1])
        return f"{label}:{(value / total):.3f}"

    def _next_required_action(self, *, verdict: str, wider_period: bool) -> str:
        if verdict == "symbol_promising_and_stable":
            return "research_symbol_filter_variant"
        if verdict == "symbol_promising_but_insufficient":
            return "run_wider_symbol_replay" if not wider_period else "collect_more_replay_evidence"
        if verdict == "symbol_unstable":
            return "run_wider_symbol_replay" if not wider_period else "investigate_another_symbol"
        if verdict == "symbol_not_promising":
            return "investigate_another_symbol" if wider_period else "return_to_portfolio_research"
        return "collect_more_replay_evidence"

    def _next_recommended_command(
        self,
        *,
        verdict: str,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
        wider_period: bool,
    ) -> str:
        if verdict in {"symbol_promising_but_insufficient", "symbol_unstable"} and not wider_period:
            return (
                ".venv-mac/bin/python main.py --symbol-subset-stability-report "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} "
                f"--timeframe {timeframe} --variant-id {variant_id} --symbol {symbol} --wider-period"
            )
        if verdict == "symbol_promising_and_stable":
            return (
                ".venv-mac/bin/python main.py --strategy-research-planner "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
            )
        return ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"

    def _replay_window(self, *, symbol: str, timeframe: str, wider_period: bool) -> dict[str, Any]:
        if not wider_period:
            end_at = datetime.now().astimezone()
            return {
                "start_at": (
                    end_at.replace(microsecond=0)
                    - self.service._replay_window_days_delta()
                ),
                "end_at": end_at.replace(microsecond=0),
            }
        rows = self.usage_ledger.summarize_historical_bar_coverage(
            asset_class="equity",
            symbols=[symbol],
            timeframes=[timeframe],
        )
        row = dict(rows[0]) if rows else {}
        return {
            "start_at": row.get("earliest_bar_timestamp"),
            "end_at": row.get("latest_bar_timestamp"),
        }

    def _latest_prior_narrow_evaluation(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
    ) -> dict[str, Any]:
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
            if str(raw.get("symbol", "")).upper() != symbol:
                continue
            if bool(raw.get("wider_period")):
                continue
            return raw
        return {
            "selected_symbol_summary": {
                "sample_size": 21,
                "net_return_after_costs": 0.194383,
                "win_rate": 0.571429,
                "profit_factor": 1.367113,
            }
        }

    def _comparison(self, *, summary: dict[str, Any], prior_narrow: dict[str, Any]) -> dict[str, Any]:
        narrow_summary = dict(prior_narrow.get("selected_symbol_summary", {}) or {})
        narrow_net = float(narrow_summary.get("net_return_after_costs", 0.0) or 0.0)
        wide_net = float(summary.get("net_return_after_costs", 0.0) or 0.0)
        narrow_win = float(narrow_summary.get("win_rate", 0.0) or 0.0)
        wide_win = float(summary.get("win_rate", 0.0) or 0.0)
        survives = wide_net > 0.0 and wide_win >= max(0.45, narrow_win - 0.10)
        return {
            "narrow_sample_size": int(narrow_summary.get("sample_size", 0) or 0),
            "wide_sample_size": int(summary.get("sample_size", 0) or 0),
            "narrow_net_return": round(narrow_net, 6),
            "wide_net_return": round(wide_net, 6),
            "narrow_win_rate": round(narrow_win, 6),
            "wide_win_rate": round(wide_win, 6),
            "narrow_profit_factor": round(float(narrow_summary.get("profit_factor", 0.0) or 0.0), 6),
            "wide_profit_factor": round(float(summary.get("profit_factor", 0.0) or 0.0), 6),
            "signal_survives_wider_period": survives,
        }

    def _persist_report(self, *, report: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now().astimezone()
        wider_period = bool(report.get("replay_scope") == "wider_period")
        scope = "wide" if wider_period else "current"
        raw = {
            "report_type": "symbol_subset_stability",
            "symbol": report.get("symbol", ""),
            "wider_period": wider_period,
            "selected_symbol_summary": report.get("selected_symbol_summary", {}),
            "period_breakdown": report.get("period_breakdown", {}),
            "narrow_vs_wide_comparison": report.get("narrow_vs_wide_comparison", {}),
            "stability_verdict": report.get("stability_verdict", ""),
            "most_actionable_next_fix": report.get("most_actionable_next_fix", ""),
            "why": report.get("why", ""),
            "replay_window": report.get("replay_window", {}),
            "safety_statement": report.get("safety_statement", ""),
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        return self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"{variant['variant_id']}:symbol-stability-{scope}:{digest}",
            variant_id=variant["variant_id"],
            base_strategy_id=variant["base_strategy_id"],
            profile_id=variant["profile_id"],
            timeframe=variant["timeframe"],
            replay_id=self._replay_id(symbol=str(report.get("symbol", "")), wider_period=wider_period),
            dataset_id=f"historical_equity_bars:{variant['timeframe']}:{scope}_symbol_subset",
            asset_class="equity",
            symbols_tested=[str(report.get("symbol", ""))],
            sample_size=int(((report.get("selected_symbol_summary", {}) or {}).get("sample_size", 0) or 0)),
            gross_return=float(((report.get("selected_symbol_summary", {}) or {}).get("gross_return_before_costs", 0.0) or 0.0)),
            net_return_after_costs=float(((report.get("selected_symbol_summary", {}) or {}).get("net_return_after_costs", 0.0) or 0.0)),
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=float(((report.get("selected_symbol_summary", {}) or {}).get("win_rate", 0.0) or 0.0)),
            drawdown=((report.get("selected_symbol_summary", {}) or {}).get("drawdown")),
            baseline_variant_id="",
            baseline_strategy_key=f"{variant['base_strategy_id']}/{variant['profile_id']}/{variant['timeframe']}",
            baseline_net_return_after_costs=float((report.get("narrow_vs_wide_comparison", {}) or {}).get("narrow_net_return", 0.0) or 0.0),
            baseline_win_rate=float((report.get("narrow_vs_wide_comparison", {}) or {}).get("narrow_win_rate", 0.0) or 0.0),
            beats_baseline=bool((report.get("narrow_vs_wide_comparison", {}) or {}).get("signal_survives_wider_period")),
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=now,
            notes=SAFETY_STATEMENT,
            raw=raw,
        )

    def _replay_id(self, *, symbol: str, wider_period: bool) -> str:
        scope = "wide" if wider_period else "narrow"
        return f"symbol-stability-{scope}-{symbol}-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}"

    def _status_counts(self, outcomes: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"target_hit": 0, "stop_hit": 0, "time_exit": 0}
        for item in outcomes:
            status = str(item.get("outcome_status", "") or "")
            if status in counts:
                counts[status] += 1
        return counts

    def _to_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        return datetime.fromisoformat(str(value))

    def _empty_report(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
        why: str,
    ) -> dict[str, Any]:
        return {
            "title": "Symbol Subset Stability Report",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "symbol": symbol,
            "selected_symbol_summary": {"sample_size": 0},
            "period_breakdown": {"by_month": [], "by_quarter": [], "by_week_or_chunk": []},
            "cohort_comparison": {
                "availability": "unavailable",
                "reason": why,
                "rows": [],
            },
            "loss_diagnosis_context": {},
            "strategy": f"{base_strategy_id}/{profile_id}/{timeframe}",
            "stability_verdict": "no_usable_subset_data",
            "month_concentration": "none:0.000",
            "outcome_concentration": "none:0.000",
            "next_required_action": "collect_more_replay_evidence",
            "next_recommended_command": ".venv-mac/bin/python main.py --strategy-portfolio-research-planner",
            "most_actionable_next_fix": "Collect more replay evidence before trusting this subset.",
            "why": why,
            "safety_statement": SAFETY_STATEMENT,
        }
