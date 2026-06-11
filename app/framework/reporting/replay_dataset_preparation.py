from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Any

from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = (
    "Research-only replay dataset preparation. No paper trades, live settings, "
    "thresholds, or promotion policy were changed."
)


@dataclass(frozen=True)
class _StrategyTarget:
    base_strategy_id: str
    profile_id: str
    timeframe: str


class ReplayDatasetPreparationReport:
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

    def build_report(self) -> dict[str, Any]:
        planner_report = self.planner.build_report()
        ranked = list(planner_report.get("ranked_strategies", []) or [])
        candidates = [
            row for row in ranked
            if str(row.get("research_status", "") or "") in {"runtime_blocked", "data_gap", "insufficient_data"}
        ]
        prepared = [self._prepare_strategy(row) for row in candidates]
        asset_blockers = Counter(
            item["asset_class"] for item in prepared if item.get("is_current_blocker")
        )
        overall_blocker = "none"
        if asset_blockers:
            overall_blocker = max(asset_blockers.items(), key=lambda item: item[1])[0]
        report = {
            "title": "Replay Dataset Preparation",
            "prepared_at": datetime.now().astimezone().isoformat(),
            "replay_prep_outcome": self._portfolio_outcome(prepared),
            "planner_next_action_before": str(planner_report.get("next_portfolio_action", "") or ""),
            "planner_next_candidate_before": self._identity_string(planner_report.get("next_actionable_research_candidate")),
            "runtime_blocked_strategies": [
                self._identity_summary(item)
                for item in prepared
                if item.get("research_status") == "runtime_blocked"
            ],
            "data_gap_strategies": [
                self._identity_summary(item)
                for item in prepared
                if item.get("research_status") == "data_gap"
            ],
            "insufficient_data_strategies": [
                self._identity_summary(item)
                for item in prepared
                if item.get("research_status") == "insufficient_data"
            ],
            "strategy_preparation": prepared,
            "strategies_needing_precomputed_replay_outcomes": [
                self._identity_summary(item)
                for item in prepared
                if item.get("needs_precomputed_replay_outcomes")
            ],
            "usable_bar_coverage": [
                {
                    "base_strategy_id": item["base_strategy_id"],
                    "profile_id": item["profile_id"],
                    "timeframe": item["timeframe"],
                    "asset_class": item["asset_class"],
                    "usable_symbols": list(item.get("usable_symbols", []) or []),
                    "symbols_with_rows": int(item.get("symbols_with_rows", 0) or 0),
                    "total_symbols_checked": int(item.get("total_symbols_checked", 0) or 0),
                    "latest_bar_timestamp": item.get("latest_bar_timestamp"),
                    "coverage_query_status": item.get("coverage_query_status", ""),
                }
                for item in prepared
            ],
            "datasets_missing_or_slow": [
                {
                    "base_strategy_id": item["base_strategy_id"],
                    "profile_id": item["profile_id"],
                    "timeframe": item["timeframe"],
                    "asset_class": item["asset_class"],
                    "blocker_type": item["blocker_type"],
                    "blocker_reason": item["blocker_reason"],
                    "coverage_query_status": item["coverage_query_status"],
                    "missing_symbols": list(item.get("missing_symbols", []) or []),
                }
                for item in prepared
                if item.get("blocker_type") not in {"none", ""}
            ],
            "current_replay_blocker_asset_class": overall_blocker,
            "crypto_replay_blocker": "yes" if overall_blocker == "crypto" else "no",
            "equity_replay_blocker": "yes" if overall_blocker == "equity" else "no",
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
            "safety_statement": SAFETY_STATEMENT,
        }
        persisted = self._persist_report(report=report, prepared=prepared)
        report["persistence"] = persisted
        return report

    def render(self) -> str:
        report = self.build_report()
        lines = [
            str(report.get("title", "Replay Dataset Preparation")),
            f"prepared_at={report.get('prepared_at', '')}",
            f"planner_next_action_before={report.get('planner_next_action_before', '')}",
            f"planner_next_candidate_before={report.get('planner_next_candidate_before', '')}",
            f"runtime_blocked_strategies_count={len(report.get('runtime_blocked_strategies', []) or [])}",
            f"data_gap_strategies_count={len(report.get('data_gap_strategies', []) or [])}",
            f"strategies_needing_precomputed_replay_outcomes_count={len(report.get('strategies_needing_precomputed_replay_outcomes', []) or [])}",
            f"current_replay_blocker_asset_class={report.get('current_replay_blocker_asset_class', 'none')}",
            "",
            "Strategy Preparation",
        ]
        for item in report.get("strategy_preparation", []) or []:
            lines.append(
                f"strategy={item.get('base_strategy_id', '-')}/{item.get('profile_id', '-')}/{item.get('timeframe', '-')}"
                f" | research_status={item.get('research_status', '-')}"
                f" | prep_status={item.get('prep_status', '-')}"
                f" | prep_action={item.get('prep_action', '-')}"
                f" | blocker_type={item.get('blocker_type', '-')}"
                f" | blocker_reason={item.get('blocker_reason', '-')}"
                f" | coverage_query_status={item.get('coverage_query_status', '-')}"
                f" | usable_symbols={','.join(item.get('usable_symbols', []) or ['none'])}"
                f" | missing_symbols={','.join(item.get('missing_symbols', []) or ['none'])}"
                f" | needs_precomputed_replay_outcomes={'yes' if item.get('needs_precomputed_replay_outcomes') else 'no'}"
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

    def _prepare_strategy(self, row: dict[str, Any]) -> dict[str, Any]:
        target = _StrategyTarget(
            base_strategy_id=str(row.get("base_strategy_id", "") or ""),
            profile_id=str(row.get("profile_id", "") or ""),
            timeframe=str(row.get("timeframe", "") or ""),
        )
        asset_class = "crypto" if target.base_strategy_id.startswith("crypto_") else "equity"
        symbols = list(
            self.config.discovery_crypto_symbols if asset_class == "crypto" else self.config.discovery_equity_symbols
        )
        coverage_rows, coverage_status, coverage_reason = self._coverage_rows(
            asset_class=asset_class,
            symbols=symbols,
            timeframe=target.timeframe,
        )
        usable_symbols = sorted(
            str(item.get("symbol", "") or "").upper()
            for item in coverage_rows
            if int(item.get("row_count", 0) or 0) > 0
        )
        missing_symbols = sorted(
            symbol.upper()
            for symbol in symbols
            if symbol.upper() not in set(usable_symbols)
        )
        latest_bar = max(
            (
                item.get("latest_bar_timestamp")
                for item in coverage_rows
                if item.get("latest_bar_timestamp") is not None
            ),
            default=None,
        )
        blocker_type = self._blocker_type(
            zero_decision_reason=str(row.get("zero_decision_reason", "") or ""),
            coverage_status=coverage_status,
            usable_symbols=usable_symbols,
            sample_size=int(row.get("latest_sample_size", 0) or 0),
        )
        blocker_reason = self._blocker_reason(
            blocker_type=blocker_type,
            zero_decision_reason=str(row.get("zero_decision_reason", "") or ""),
            coverage_reason=coverage_reason,
            timeframe=target.timeframe,
            asset_class=asset_class,
            usable_symbol_count=len(usable_symbols),
            total_symbol_count=len(symbols),
        )
        prep_status = self._prep_status(
            blocker_type=blocker_type,
            research_status=str(row.get("research_status", "") or ""),
            needs_precomputed_replay_outcomes=bool(usable_symbols) and int(row.get("latest_sample_size", 0) or 0) <= 0,
        )
        prep_action = self._prep_action(
            base_strategy_id=target.base_strategy_id,
            timeframe=target.timeframe,
            prep_status=prep_status,
        )
        return {
            "base_strategy_id": target.base_strategy_id,
            "profile_id": target.profile_id,
            "timeframe": target.timeframe,
            "asset_class": asset_class,
            "research_status": str(row.get("research_status", "") or ""),
            "zero_decision_reason": str(row.get("zero_decision_reason", "") or ""),
            "coverage_query_status": coverage_status,
            "coverage_query_reason": coverage_reason,
            "symbols_with_rows": len(usable_symbols),
            "total_symbols_checked": len(symbols),
            "usable_symbols": usable_symbols[:12],
            "missing_symbols": missing_symbols[:12],
            "latest_bar_timestamp": latest_bar.isoformat() if hasattr(latest_bar, "isoformat") else latest_bar,
            "needs_precomputed_replay_outcomes": bool(usable_symbols) and int(row.get("latest_sample_size", 0) or 0) <= 0,
            "blocker_type": blocker_type,
            "blocker_reason": blocker_reason,
            "prep_status": prep_status,
            "prep_action": prep_action,
            "is_current_blocker": bool(str(row.get("research_status", "") or "") in {"runtime_blocked", "data_gap"}),
        }

    def _coverage_rows(
        self,
        *,
        asset_class: str,
        symbols: list[str],
        timeframe: str,
    ) -> tuple[list[dict[str, Any]], str, str]:
        try:
            rows = list(
                self.usage_ledger.summarize_historical_bar_coverage(
                    asset_class=asset_class,
                    symbols=symbols,
                    timeframes=[timeframe] if timeframe else None,
                )
            )
        except Exception as exc:
            text = str(exc).lower()
            if "lock timeout" in text or "locknotavailable" in text:
                return [], "lock_timeout", str(exc)
            return [], "query_failed", str(exc)
        return rows, "ok", ""

    def _blocker_type(
        self,
        *,
        zero_decision_reason: str,
        coverage_status: str,
        usable_symbols: list[str],
        sample_size: int,
    ) -> str:
        if coverage_status == "lock_timeout":
            return "lock_timeout"
        if zero_decision_reason == "historical_bar_read_timeout":
            return "slow_reads"
        if zero_decision_reason == "no_bars_for_timeframe" or not usable_symbols:
            return "missing_bars"
        if sample_size <= 0:
            return "no_usable_signals"
        return "none"

    def _blocker_reason(
        self,
        *,
        blocker_type: str,
        zero_decision_reason: str,
        coverage_reason: str,
        timeframe: str,
        asset_class: str,
        usable_symbol_count: int,
        total_symbol_count: int,
    ) -> str:
        if blocker_type == "lock_timeout":
            return coverage_reason or "Historical coverage summary hit a lock timeout."
        if blocker_type == "slow_reads":
            return "Replay or historical bar reads timed out before usable bars were loaded."
        if blocker_type == "missing_bars":
            if zero_decision_reason == "no_bars_for_timeframe":
                return f"{usable_symbol_count}/{total_symbol_count} symbols have usable {timeframe} {asset_class} bars."
            return f"No usable {asset_class} {timeframe} bar coverage was found."
        if blocker_type == "no_usable_signals":
            return "Bars exist, but no bounded replay outcomes or usable zero-sample follow-up signals were available yet."
        return ""

    def _prep_status(
        self,
        *,
        blocker_type: str,
        research_status: str,
        needs_precomputed_replay_outcomes: bool,
    ) -> str:
        if research_status not in {"runtime_blocked", "data_gap", "insufficient_data"}:
            return "no_actionable_candidate"
        if blocker_type == "slow_reads":
            return "replay_prepared_but_still_slow"
        if blocker_type == "lock_timeout":
            return "prep_failed"
        if blocker_type == "missing_bars":
            return "missing_timeframe_bars"
        if blocker_type == "no_usable_signals":
            return "replay_prepared_but_no_signals"
        if needs_precomputed_replay_outcomes:
            return "needs_backfill_or_resample"
        return "no_actionable_candidate"

    def _prep_action(
        self,
        *,
        base_strategy_id: str,
        timeframe: str,
        prep_status: str,
    ) -> str:
        if prep_status == "missing_timeframe_bars":
            return f"backfill_or_resample_crypto_{timeframe}_bars" if base_strategy_id.startswith("crypto_") else f"backfill_or_resample_{timeframe}_bars"
        if prep_status == "replay_prepared_but_still_slow":
            if base_strategy_id == "crypto_research.dip_rebound" and timeframe == "15Min":
                return "precompute_bounded_dip_rebound_15Min_outcomes"
            return "optimise_specific_crypto_15Min_replay_cache" if base_strategy_id.startswith("crypto_") and timeframe == "15Min" else "precompute_specific_replay_cache"
        if prep_status == "replay_prepared_but_no_signals":
            return "deprioritise_until_new_data"
        if prep_status == "needs_backfill_or_resample":
            return "backfill_or_resample_replay_inputs"
        return ""

    def _portfolio_outcome(self, prepared: list[dict[str, Any]]) -> str:
        priorities = (
            "replay_prepared_candidate_unlocked",
            "replay_prepared_but_still_slow",
            "missing_timeframe_bars",
            "needs_backfill_or_resample",
            "replay_prepared_but_no_signals",
            "no_actionable_candidate",
            "prep_failed",
        )
        seen = {str(item.get("prep_status", "") or "") for item in prepared}
        for status in priorities:
            if status in seen:
                return status
        return "no_actionable_candidate"

    def _persist_report(self, *, report: dict[str, Any], prepared: list[dict[str, Any]]) -> dict[str, Any]:
        persisted_ids: list[str] = []
        prepared_at = datetime.now().astimezone()
        portfolio_raw = {
            "report_type": "replay_dataset_preparation",
            "scope": "portfolio",
            "summary": {
                "planner_next_action_before": report.get("planner_next_action_before", ""),
                "planner_next_candidate_before": report.get("planner_next_candidate_before", ""),
                "current_replay_blocker_asset_class": report.get("current_replay_blocker_asset_class", "none"),
            },
            "datasets_missing_or_slow": report.get("datasets_missing_or_slow", []),
            "safety_statement": SAFETY_STATEMENT,
        }
        persisted_ids.append(
            self._persist_evaluation(
                target=_StrategyTarget("portfolio", "replay_dataset_preparation", "mixed"),
                prepared_at=prepared_at,
                raw=portfolio_raw,
            )
        )
        for item in prepared:
            raw = {
                "report_type": "replay_dataset_preparation",
                "scope": "strategy",
                **item,
                "safety_statement": SAFETY_STATEMENT,
            }
            persisted_ids.append(
                self._persist_evaluation(
                    target=_StrategyTarget(
                        item["base_strategy_id"],
                        item["profile_id"],
                        item["timeframe"],
                    ),
                    prepared_at=prepared_at,
                    raw=raw,
                )
            )
        return {
            "evaluation_count": len(persisted_ids),
            "evaluation_ids": persisted_ids,
        }

    def _persist_evaluation(
        self,
        *,
        target: _StrategyTarget,
        prepared_at: datetime,
        raw: dict[str, Any],
    ) -> str:
        digest = sha1(json.dumps(raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        timestamp_fragment = prepared_at.strftime("%Y%m%d%H%M%S")
        evaluation_id = (
            "replay-dataset-preparation:"
            f"{target.base_strategy_id}:{target.profile_id}:{target.timeframe}:{timestamp_fragment}:{digest}"
        )
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=evaluation_id,
            variant_id="replay-dataset-preparation",
            base_strategy_id=target.base_strategy_id,
            profile_id=target.profile_id,
            timeframe=target.timeframe,
            replay_id=f"replay-dataset-preparation-{prepared_at.strftime('%Y%m%d-%H%M%S')}",
            dataset_id="replay_dataset_preparation_summary",
            asset_class=str(raw.get("asset_class", "mixed") or "mixed"),
            symbols_tested=list(raw.get("usable_symbols", []) or []),
            sample_size=0,
            gross_return=0.0,
            net_return_after_costs=0.0,
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=0.0,
            drawdown=None,
            baseline_variant_id="",
            baseline_strategy_key=f"{target.base_strategy_id}/{target.profile_id}/{target.timeframe}",
            baseline_net_return_after_costs=0.0,
            baseline_win_rate=0.0,
            beats_baseline=False,
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=prepared_at,
            notes=SAFETY_STATEMENT,
            raw=raw,
        )
        return evaluation_id

    def _identity_summary(self, item: dict[str, Any]) -> dict[str, str]:
        return {
            "base_strategy_id": str(item.get("base_strategy_id", "") or ""),
            "profile_id": str(item.get("profile_id", "") or ""),
            "timeframe": str(item.get("timeframe", "") or ""),
        }

    def _identity_string(self, summary: Any) -> str:
        item = dict(summary or {})
        if not item:
            return ""
        return (
            f"{str(item.get('base_strategy_id', '') or '')}/"
            f"{str(item.get('profile_id', '') or '')}/"
            f"{str(item.get('timeframe', '') or '')}"
        )
