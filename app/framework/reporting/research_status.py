from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from app.framework.reporting.promotion_gate import PromotionGateReport
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ResearchStatusReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        cycle = self._latest_research_cycle()
        if cycle is None:
            return {"status": "not_found", "reason": "No research cycle has been recorded yet."}
        snapshot = cycle.get("state_snapshot_json", {}) if isinstance(cycle, dict) else {}
        state = snapshot.get("research_cycle", {}) if isinstance(snapshot, dict) else {}
        run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        decisions = self.usage_ledger.list_research_cycle_decisions(
            cycle_id=str(cycle.get("tick_id", "") or ""),
            limit=500,
        )
        if not decisions:
            decisions = self.usage_ledger.list_latest_research_cycle_decisions()
        promotion_gate = PromotionGateReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        return {
            "status": "ok",
            "research_cycle_id": cycle.get("tick_id"),
            "last_research_cycle_time": cycle.get("started_at"),
            "timeframe": run.get("timeframe"),
            "days": run.get("days"),
            "replay_windows_tested": state.get("replay_windows_tested", []),
            "timeframes_used": state.get("timeframes_used", []),
            "timeframes_skipped": state.get("timeframes_skipped", []),
            "strategies": state.get("strategies", {}),
            "decisions": [
                {
                    **item,
                    "broker_paper_approved": bool(
                        (
                            promotion_gate.get_paper_approval(
                                strategy_id=str(item.get("strategy_id", "")),
                                profile_id=str(item.get("profile_id", "")),
                            )
                            or SimpleNamespace(paper_approved=False)
                        ).paper_approved
                    ),
                }
                for item in decisions
            ],
            "allocation_guardrails": state.get("allocation_guardrails", {}),
            "live_execution_remains_disabled": True,
        }

    def render(self) -> str:
        report = self.build_report()
        if report.get("status") != "ok":
            return (
                "Research Status\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )
        lines = [
            "Research Status",
            (
                f"last_research_cycle_time={self._fmt_dt(report.get('last_research_cycle_time'))}"
                f" | research_cycle_id={report.get('research_cycle_id', '-')}"
                f" | timeframe={report.get('timeframe', '-')}"
                f" | days={report.get('days', '-')}"
            ),
            f"replay_windows_tested={len(report.get('replay_windows_tested', []) or [])}",
            f"timeframes_used={','.join(report.get('timeframes_used', []) or ['-'])}",
        ]
        skipped = report.get("timeframes_skipped", []) or []
        if skipped:
            lines.append(
                "timeframes_skipped="
                + ",".join(
                    f"{item.get('timeframe', '-')}/{item.get('reason', '-')}" for item in skipped
                )
            )
        guardrails = report.get("allocation_guardrails", {}) or {}
        lines.append(
            "backtest_evidence_in_allocation="
            f"paper:{'yes' if guardrails.get('include_backtest_evidence_in_paper_fitness') else 'no'}"
            f"/live:{'yes' if guardrails.get('include_backtest_evidence_in_live_fitness') else 'no'}"
        )
        decisions = report.get("decisions", []) or []
        if not decisions:
            lines.append("strategies_evaluated=none")
        else:
            for item in decisions:
                lines.append(
                    f"strategy={item.get('strategy_id', '-')}"
                    f" | profile={item.get('profile_id', '-')}"
                    f" | timeframe={item.get('timeframe', '-')}"
                )
                lines.append(
                    f"- recommendation={item.get('recommendation', '-')}"
                    f" | windows_tested={int(item.get('windows_tested_count', 0) or 0)}"
                    f" | sample_size_status={item.get('sample_size_status', '-')}"
                    f" | data_integrity_status={item.get('data_integrity_status', '-')}"
                )
                gross = item.get("gross_return_summary_json", {}) or {}
                net = item.get("net_return_summary_json", {}) or {}
                win = item.get("win_rate_summary_json", {}) or {}
                lines.append(
                    f"- gross_performance_pct={gross.get('avg_pct', 0)}"
                    f" | net_performance_pct={net.get('avg_pct', 0)}"
                    f" | net_win_rate={win.get('avg', 0)}"
                    f" | outcomes_recorded={int(item.get('outcomes_recorded', 0) or 0)}"
                )
                lines.append(
                    f"- blocker_reasons={','.join(item.get('blocker_reasons_json', []) or ['none'])}"
                )
                lines.append(
                    f"- broker_paper_approved={'yes' if item.get('broker_paper_approved') else 'no'}"
                )
        lines.append(
            "live_execution_status=disabled_manual_only"
        )
        return "\n".join(lines)

    def _latest_research_cycle(self) -> dict[str, Any] | None:
        for row in self.usage_ledger.list_recent_tick_runs(limit=200):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            run = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
            if str(run.get("pipeline", "") or "") == "research_cycle":
                return row
        return None

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")
