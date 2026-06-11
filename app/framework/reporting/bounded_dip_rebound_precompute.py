from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Any

from app.framework.reporting.strategy_variant_research import StrategyVariantResearchService
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = (
    "Research-only bounded dip rebound outcome precompute. No paper trades, live settings, "
    "thresholds, or promotion policy were changed."
)
PRECOMPUTE_COMMAND = ".venv-mac/bin/python main.py --precompute-bounded-dip-rebound-15min-outcomes"


@dataclass(frozen=True)
class _Target:
    base_strategy_id: str = "crypto_research.dip_rebound"
    profile_id: str = "dip_rebound"
    timeframe: str = "15Min"


class BoundedDipReboundPrecomputeReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        variant_service: StrategyVariantResearchService | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=False,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )
        self.variant_service = variant_service or StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(self) -> dict[str, Any]:
        target = _Target()
        prepared_at = datetime.now().astimezone()
        result = self.variant_service.run_research(
            base_strategy_id=target.base_strategy_id,
            profile_id=target.profile_id,
            timeframe=target.timeframe,
            created_by="precompute_bounded_dip_rebound_15Min_outcomes",
            bounded_diagnosis=True,
        )
        baseline = dict(result.get("baseline_metrics") or {})
        raw = dict(baseline.get("raw_json", baseline.get("raw", {})) or {})
        diagnostics = dict(raw.get("diagnostics", {}) or {})
        adequacy = dict(diagnostics.get("data_adequacy", {}) or {})
        runtime_blocker = str(
            adequacy.get("zero_decision_reason", "")
            or diagnostics.get("runtime_blocker", "")
            or ""
        )
        sample_size = int(baseline.get("sample_size", 0) or 0)
        runtime_status = (
            "runtime_blocked"
            if runtime_blocker
            else ("precomputed" if sample_size > 0 else "insufficient_data")
        )
        next_required_action = (
            "precompute_bounded_dip_rebound_15Min_outcomes"
            if runtime_status == "runtime_blocked"
            else "strategy_portfolio_research_planner"
        )
        next_recommended_command = (
            PRECOMPUTE_COMMAND
            if runtime_status == "runtime_blocked"
            else ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        )
        report = {
            "title": "Bounded Dip Rebound 15Min Outcome Precompute",
            "prepared_at": prepared_at.isoformat(),
            "strategy": target.base_strategy_id,
            "profile": target.profile_id,
            "timeframe": target.timeframe,
            "symbols_processed": len(list(baseline.get("symbols_tested", []) or [])),
            "bars_read": int(adequacy.get("total_bars", 0) or 0),
            "outcomes_generated": sample_size,
            "sample_size": sample_size,
            "net_return_after_costs": float(baseline.get("net_return_after_costs", 0.0) or 0.0),
            "win_rate": float(baseline.get("win_rate", 0.0) or 0.0),
            "drawdown": baseline.get("drawdown"),
            "runtime_status": runtime_status,
            "runtime_blocker": runtime_blocker,
            "cache_status": "fresh" if runtime_status != "runtime_blocked" else "blocked",
            "next_required_action": next_required_action,
            "next_recommended_command": next_recommended_command,
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
            "safety_statement": SAFETY_STATEMENT,
        }
        report["persistence"] = self._persist(target=target, prepared_at=prepared_at, report=report)
        return report

    def render(self) -> str:
        report = self.build_report()
        lines = [
            str(report.get("title", "")),
            f"prepared_at={report.get('prepared_at', '')}",
            f"strategy={report.get('strategy', '')}",
            f"profile={report.get('profile', '')}",
            f"timeframe={report.get('timeframe', '')}",
            f"symbols_processed={report.get('symbols_processed', 0)}",
            f"bars_read={report.get('bars_read', 0)}",
            f"outcomes_generated={report.get('outcomes_generated', 0)}",
            f"sample_size={report.get('sample_size', 0)}",
            f"net_return_after_costs={report.get('net_return_after_costs', 0.0)}",
            f"win_rate={report.get('win_rate', 0.0)}",
            f"drawdown={report.get('drawdown', '')}",
            f"runtime_status={report.get('runtime_status', '')}",
            f"runtime_blocker={report.get('runtime_blocker', '')}",
            f"cache_status={report.get('cache_status', '')}",
            f"next_required_action={report.get('next_required_action', '')}",
            f"next_recommended_command={report.get('next_recommended_command', '')}",
            f"paper_trades_created={report.get('paper_trades_created', 'no')}",
            f"live_changed={report.get('live_changed', 'no')}",
            f"thresholds_changed={report.get('thresholds_changed', 'no')}",
            f"promotion_policy_changed={report.get('promotion_policy_changed', 'no')}",
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def _persist(self, *, target: _Target, prepared_at: datetime, report: dict[str, Any]) -> dict[str, Any]:
        raw = {
            "report_type": "replay_dataset_preparation",
            "scope": "strategy",
            "prep_status": "replay_prepared_candidate_unlocked" if report["runtime_status"] != "runtime_blocked" else "replay_prepared_but_still_slow",
            "prep_action": "precompute_bounded_dip_rebound_15Min_outcomes",
            "blocker_reason": report.get("runtime_blocker", ""),
            "base_strategy_id": target.base_strategy_id,
            "profile_id": target.profile_id,
            "timeframe": target.timeframe,
            "asset_class": "crypto",
            "usable_symbols": list((report.get("symbols_processed") and (report.get("symbols_tested") or [])) or baseline_symbols_from_report(report)),
            "symbols_processed": report.get("symbols_processed", 0),
            "bars_read": report.get("bars_read", 0),
            "outcomes_generated": report.get("outcomes_generated", 0),
            "sample_size": report.get("sample_size", 0),
            "net_return_after_costs": report.get("net_return_after_costs", 0.0),
            "win_rate": report.get("win_rate", 0.0),
            "drawdown": report.get("drawdown"),
            "runtime_status": report.get("runtime_status", ""),
            "runtime_blocker": report.get("runtime_blocker", ""),
            "cache_status": report.get("cache_status", ""),
            "next_required_action": report.get("next_required_action", ""),
            "next_recommended_command": report.get("next_recommended_command", ""),
            "safety_statement": SAFETY_STATEMENT,
        }
        digest = sha1(json.dumps(raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        timestamp_fragment = prepared_at.strftime("%Y%m%d%H%M%S")
        evaluation_id = (
            "replay-dataset-preparation:"
            f"{target.base_strategy_id}:{target.profile_id}:{target.timeframe}:{timestamp_fragment}:{digest}"
        )
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=evaluation_id,
            variant_id="precompute-bounded-dip-rebound-15min-outcomes",
            base_strategy_id=target.base_strategy_id,
            profile_id=target.profile_id,
            timeframe=target.timeframe,
            replay_id=f"precompute-bounded-dip-rebound-15min-{prepared_at.strftime('%Y%m%d-%H%M%S')}",
            dataset_id="replay_dataset_preparation_summary",
            asset_class="crypto",
            symbols_tested=[],
            sample_size=int(report.get("sample_size", 0) or 0),
            gross_return=float(report.get("net_return_after_costs", 0.0) or 0.0),
            net_return_after_costs=float(report.get("net_return_after_costs", 0.0) or 0.0),
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=float(report.get("win_rate", 0.0) or 0.0),
            drawdown=report.get("drawdown"),
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
        return {"evaluation_id": evaluation_id, "recorded_at": prepared_at.isoformat()}


def baseline_symbols_from_report(report: dict[str, Any]) -> list[str]:
    return list(report.get("symbols_tested", []) or [])
