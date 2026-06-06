from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from time import perf_counter
from typing import Any

from app.framework.engine.replay import HistoricalReplayRunner
from app.framework.reporting.historical_bars_status import HistoricalBarsStatusReport
from app.framework.reporting.promotion_gate import PromotionGateReport
from app.framework.reporting.replay_summary import ReplayComparisonReport, ReplaySummaryReport
from app.framework.runtime.models import TickReport
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.runtime.attention_alerts import (
    approval_request_id,
    build_event_id,
    create_attention_alert,
    send_due_attention_alerts,
)
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.registry import build_strategy_registry


@dataclass(frozen=True, slots=True)
class ResearchWindow:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class TimeframePlan:
    timeframe: str
    status: str
    reason: str
    available_symbols: list[str]
    available_timeframes: list[str]
    windows: tuple[ResearchWindow, ...] = tuple()
    readiness: dict[str, Any] | None = None
    historical_coverage: dict[str, Any] | None = None


class ResearchCycleRunner:
    """Run autonomous replay research and persist evidence without enabling execution."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        source: str = "manual_cli",
        parent_tick_id: str = "",
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.source = str(source or "manual_cli").strip() or "manual_cli"
        self.parent_tick_id = str(parent_tick_id or "").strip()
        self.replay_runner = HistoricalReplayRunner(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.summary_report = ReplaySummaryReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.comparison_report = ReplayComparisonReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.bars_report = HistoricalBarsStatusReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.promotion_gate = PromotionGateReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def run(self) -> TickReport:
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        cycle_id = f"researchcycle-{started_at.strftime('%Y%m%d-%H%M%S-%f')}"
        diagnostics = self.build_historical_replay_diagnostics(end_at=started_at)
        inventory = diagnostics["inventory"]
        plans = diagnostics["plans"]

        replay_runs_by_timeframe: dict[str, list[dict[str, Any]]] = defaultdict(list)
        replay_run_ids: list[str] = []
        for plan in plans:
            if plan.status != "ready":
                continue
            for window in plan.windows:
                replay = self.replay_runner.run(
                    days=self.config.research_replay_days,
                    timeframe=plan.timeframe,
                    equity_symbols=self.config.discovery_equity_symbols,
                    crypto_symbols=self.config.discovery_crypto_symbols,
                    max_timestamps=self.config.research_max_replay_timestamps,
                    start_at=window.start_at,
                    end_at=window.end_at,
                    dry_run=False,
                )
                replay_run_ids.append(replay.tick_id)
                replay_runs_by_timeframe[plan.timeframe].append(
                    self.summary_report.build_report(replay_run_id=replay.tick_id)
                )

        comparison = (
            self.comparison_report.build_report(replay_limit=max(1, len(replay_run_ids)))
            if replay_run_ids
            else {"status": "not_run", "reason": "no_replay_runs"}
        )
        decisions = self._build_research_decisions(
            cycle_id=cycle_id,
            created_at=started_at,
            plans=plans,
            replay_runs_by_timeframe=replay_runs_by_timeframe,
        )
        profile_count = len(self._research_profiles())
        usable_decisions_count = len(decisions)
        paper_candidates_created = sum(
            1
            for item in decisions
            if str(item.get("recommendation", "")) == "paper_sim_candidate"
        )
        paper_removal_candidates_created = sum(
            1
            for item in decisions
            if str(item.get("recommendation", "")) == "paper_removal_candidate"
        )
        decisions_written = self.usage_ledger.record_research_cycle_decisions(decisions=decisions)
        for decision in decisions:
            self.promotion_gate.record_research_evidence(
                strategy_id=str(decision.get("strategy_id", "")),
                profile_id=str(decision.get("profile_id", "")),
                recommendation=str(decision.get("recommendation", "research_only")),
                blocker_reasons=list(decision.get("blocker_reasons", []) or []),
                replay_summary={
                    "classification": decision.get("recommendation", "research_only"),
                    "recommendation": decision.get("recommendation", "research_only"),
                    "net_return_after_costs_pct": (
                        decision.get("net_return_summary", {}) or {}
                    ).get("avg_pct", 0.0),
                    "win_rate": (decision.get("win_rate_summary", {}) or {}).get("avg", 0.0),
                    "sample_size": int(decision.get("proposals_created", 0) or 0),
                    "windows_with_data": int(decision.get("windows_tested_count", 0) or 0),
                    "windows_required": int(self.config.research_min_windows),
                },
                paper_sim_summary={
                    "net_return_after_costs_pct": (
                        decision.get("net_return_summary", {}) or {}
                    ).get("avg_pct", 0.0),
                    "win_rate": (decision.get("win_rate_summary", {}) or {}).get("avg", 0.0),
                    "sample_size": int(decision.get("outcomes_recorded", 0) or 0),
                    "adverse_excursion_pct": (
                        decision.get("net_return_summary", {}) or {}
                    ).get("avg_max_adverse_excursion_pct", 0.0),
                    "composite_fitness_score": 0.0,
                },
                data_integrity={
                    "status": decision.get("data_integrity_status", "unknown"),
                    "failure_reasons": list(decision.get("blocker_reasons", []) or []),
                },
                research_only_profile=bool(decision.get("research_only_profile")),
            )
            self._create_attention_alerts_for_decision(
                cycle_id=cycle_id,
                created_at=started_at,
                decision=decision,
            )
        if decisions and self.source == "real_heartbeat":
            resolve_attention_alert = getattr(self.usage_ledger, "resolve_attention_alert", None)
            if callable(resolve_attention_alert):
                resolve_attention_alert(
                    event_id=build_event_id(event_type="research_cycle_failure"),
                    status="resolved",
                    reason="later_real_heartbeat_cycle_recorded_usable_decisions",
                    resolved_at=started_at,
                )
        else:
            create_attention_alert(
                usage_ledger=self.usage_ledger,
                now=started_at,
                event_id=build_event_id(event_type="research_cycle_failure"),
                severity="critical",
                event_type="research_cycle_failure",
                title="Research cycle produced no usable decisions",
                message=(
                    "Research cycle could not produce any usable replay decisions. "
                    "Broker paper and live remain disabled."
                ),
                evidence_summary={
                    "tick_id": self.parent_tick_id or cycle_id,
                    "cycle_id": cycle_id,
                    "source": self.source,
                    "stage": "research_only",
                    "created_at": started_at.isoformat(),
                    "last_checked_at": started_at.isoformat(),
                    "strategy_profiles_discovered": profile_count,
                    "strategy_profiles_evaluated": profile_count,
                    "usable_decisions_count": usable_decisions_count,
                    "paper_candidates_created": paper_candidates_created,
                    "paper_removal_candidates_created": paper_removal_candidates_created,
                    "open_reason": (
                        "Waiting for a later real heartbeat research cycle to produce usable decisions."
                    ),
                    **dict(
                        getattr(
                            self.usage_ledger,
                            "latest_real_heartbeat_research_cycle_summary",
                            lambda: {},
                        )()
                        or {}
                    ),
                },
                recommended_action="Inspect historical bar coverage, replay readiness, and research configuration.",
                requires_attention=True,
                source=self.source,
            )
        self._send_immediate_attention_alerts(cycle_id=cycle_id, started_at=started_at)

        state_snapshot = self._build_state_snapshot(
            cycle_id=cycle_id,
            started_at=started_at,
            plans=plans,
            diagnostics=diagnostics,
            replay_run_ids=replay_run_ids,
            decisions=decisions,
            comparison=comparison,
            inventory=inventory,
            profile_count=profile_count,
            usable_decisions_count=usable_decisions_count,
            paper_candidates_created=paper_candidates_created,
            paper_removal_candidates_created=paper_removal_candidates_created,
            decisions_written=decisions_written,
        )
        ended_at = datetime.now().astimezone()
        report = TickReport(
            tick_id=cycle_id,
            status="ok",
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=perf_counter() - started_perf,
            state_snapshot=state_snapshot,
            operations_backend=self.usage_ledger.backend,
            operations_backend_detail=self.usage_ledger.backend_detail,
        )
        try:
            report.persisted_tick_run = self.usage_ledger.record_tick_run(report)
        except Exception as exc:
            report.persistence_error = f"{type(exc).__name__}: {exc}"
        return report

    def build_historical_replay_diagnostics(
        self,
        *,
        end_at: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_end_at = end_at or datetime.now().astimezone()
        inventory = self.bars_report.build_report(
            days=self.config.research_replay_days,
            timeframe=self.config.research_replay_timeframe,
            crypto_symbols=self.config.discovery_crypto_symbols,
            equity_symbols=self.config.discovery_equity_symbols,
            end_at=resolved_end_at,
        )
        plans = self._build_timeframe_plans(
            inventory=inventory,
            end_at=resolved_end_at,
        )
        requested_windows = max(1, int(self.config.research_min_windows or 1))
        replay_window_candidates: list[dict[str, Any]] = []
        replay_window_rejections: list[dict[str, Any]] = []
        replay_window_acceptances: list[dict[str, Any]] = []
        for plan in plans:
            candidate_windows = list(plan.windows)
            if not candidate_windows:
                candidate_windows = self._candidate_windows_for_rejection(
                    anchor_end_at=self._plan_anchor_end_at(plan=plan, fallback_end_at=resolved_end_at),
                    count=requested_windows,
                )
            for index, window in enumerate(candidate_windows, start=1):
                row = {
                    "timeframe": plan.timeframe,
                    "window_index": index,
                    "start_at": window.start_at.isoformat(),
                    "end_at": window.end_at.isoformat(),
                    "status": "accepted" if plan.status == "ready" else "rejected",
                    "reason": plan.reason,
                    "latest_valid_replay_window_end": self._iso_or_blank(
                        (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
                    ),
                }
                replay_window_candidates.append(row)
                if plan.status == "ready":
                    replay_window_acceptances.append(row)
                else:
                    replay_window_rejections.append(row)
        anchor_summary = self._summarize_plan_anchor_coverage(plans=plans)
        return {
            "inventory": inventory,
            "plans": plans,
            "replay_window_candidates": replay_window_candidates,
            "replay_window_acceptances": replay_window_acceptances,
            "replay_window_rejections": replay_window_rejections,
            "historical_windows_selected": len(replay_window_acceptances),
            "replay_windows_accepted_count": len(replay_window_acceptances),
            "replay_windows_rejected_count": len(replay_window_rejections),
            **anchor_summary,
        }

    def _create_attention_alerts_for_decision(
        self,
        *,
        cycle_id: str,
        created_at: datetime,
        decision: dict[str, Any],
    ) -> None:
        strategy_id = str(decision.get("strategy_id", ""))
        profile_id = str(decision.get("profile_id", ""))
        recommendation = str(decision.get("recommendation", "research_only"))
        approval_id = approval_request_id(strategy_id=strategy_id, profile_id=profile_id)
        if recommendation == "paper_sim_candidate":
            create_attention_alert(
                usage_ledger=self.usage_ledger,
                now=created_at,
                event_id=build_event_id(
                    event_type="paper_candidate",
                    strategy_id=strategy_id,
                    profile_id=profile_id,
                    approval_id=approval_id,
                ),
                severity="warning",
                event_type="paper_candidate",
                title="Broker paper approval required",
                message=(
                    f"{strategy_id}/{profile_id} reached paper_candidate from research evidence. "
                    "Broker paper remains blocked until manual approval."
                ),
                evidence_summary={
                    "stage": "paper_candidate",
                    "cycle_id": cycle_id,
                    "approval_command": (
                        "python main.py --promotion-approve-paper "
                        f"--strategy-id {strategy_id} --profile-id {profile_id} "
                        "--max-paper-notional 10 --max-open-trades 1 "
                        "--cooldown-minutes 60 --confirm-promotion-approval"
                    ),
                    "reject_command": (
                        "python main.py --promotion-reject "
                        f"--strategy-id {strategy_id} --profile-id {profile_id} "
                        '--reason "manual review rejected"'
                    ),
                },
                recommended_action="Approve or reject this request.",
                requires_attention=True,
                strategy_id=strategy_id,
                profile_id=profile_id,
                approval_request_id_value=approval_id,
                source=self.source,
            )
        if recommendation == "paper_removal_candidate":
            create_attention_alert(
                usage_ledger=self.usage_ledger,
                now=created_at,
                event_id=build_event_id(
                    event_type="paper_removal_candidate",
                    strategy_id=strategy_id,
                    profile_id=profile_id,
                    approval_id=approval_id,
                ),
                severity="warning",
                event_type="paper_removal_candidate",
                title="Broker paper removal review required",
                message=(
                    f"{strategy_id}/{profile_id} no longer meets safe paper evidence expectations. "
                    "Manual review is required before any broker paper removal or unapproval."
                ),
                evidence_summary={
                    "stage": "paper_removal_candidate",
                    "cycle_id": cycle_id,
                    "reject_command": (
                        "python main.py --promotion-reject "
                        f"--strategy-id {strategy_id} --profile-id {profile_id} "
                        '--reason "paper removal review acknowledged"'
                    ),
                },
                recommended_action="Review whether broker paper approval should be kept or removed.",
                requires_attention=True,
                strategy_id=strategy_id,
                profile_id=profile_id,
                approval_request_id_value=approval_id,
                source=self.source,
            )
        if str(decision.get("data_integrity_status", "pass")) == "fail":
            create_attention_alert(
                usage_ledger=self.usage_ledger,
                now=created_at,
                event_id=build_event_id(
                    event_type="data_integrity_failure",
                    strategy_id=strategy_id,
                    profile_id=profile_id,
                ),
                severity="critical",
                event_type="data_integrity_failure",
                title="Research data integrity failure",
                message=(
                    f"{strategy_id}/{profile_id} has failing research data integrity. "
                    "Research evidence should be reviewed before any promotion decision."
                ),
                evidence_summary={
                    "stage": recommendation,
                    "cycle_id": cycle_id,
                },
                recommended_action="Inspect research data integrity and replay coverage.",
                requires_attention=True,
                strategy_id=strategy_id,
                profile_id=profile_id,
                source=self.source,
            )

    def _send_immediate_attention_alerts(self, *, cycle_id: str, started_at: datetime) -> None:
        context = type(
            "ResearchAlertContext",
            (),
            {
                "tick_id": cycle_id,
                "started_at": started_at,
                "config": self.config,
                "usage_ledger": self.usage_ledger,
            },
        )()
        send_due_attention_alerts(context=context)

    def _build_timeframe_plans(
        self,
        *,
        inventory: dict[str, Any],
        end_at: datetime,
    ) -> list[TimeframePlan]:
        historical = inventory.get("historical", {}) or {}
        symbol_rows = historical.get("symbol_rows", []) or []
        available_symbols = sorted(
            {
                str(row.get("symbol", "")).strip()
                for row in symbol_rows
                if str(row.get("symbol", "")).strip()
            }
        )
        available_timeframes = sorted(
            {
                str(row.get("timeframe", "")).strip()
                for row in historical.get("rows_by_timeframe", []) or []
                if str(row.get("timeframe", "")).strip()
            }
        )
        timeframe_candidates = self._ordered_unique(
            [self.config.research_replay_timeframe, *available_timeframes]
        )
        plans: list[TimeframePlan] = []
        for timeframe in timeframe_candidates:
            coverage = self._timeframe_historical_coverage(
                timeframe=timeframe,
                fallback_end_at=end_at,
            )
            readiness_report = self.bars_report.build_report(
                days=self.config.research_replay_days,
                timeframe=timeframe,
                crypto_symbols=self.config.discovery_crypto_symbols,
                equity_symbols=self.config.discovery_equity_symbols,
                end_at=self._plan_anchor_end_at(
                    plan=TimeframePlan(
                        timeframe=timeframe,
                        status="pending",
                        reason="pending",
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        historical_coverage=coverage,
                    ),
                    fallback_end_at=end_at,
                ),
            )
            readiness = dict(readiness_report.get("replay_readiness", {}) or {})
            if timeframe not in available_timeframes:
                plans.append(
                    TimeframePlan(
                        timeframe=timeframe,
                        status="skipped",
                        reason="timeframe_not_present_in_historical_store",
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        readiness=readiness,
                        historical_coverage=coverage,
                    )
                )
                continue
            if (
                not bool(coverage.get("has_historical_bars"))
                and not str(coverage.get("fallback_mode", "")).strip()
            ):
                plans.append(
                    TimeframePlan(
                        timeframe=timeframe,
                        status="skipped",
                        reason="no_matching_historical_rows_for_requested_symbols",
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        readiness=readiness,
                        historical_coverage=coverage,
                    )
                )
                continue
            latest_valid_end = coverage.get("latest_valid_replay_window_end")
            if not isinstance(latest_valid_end, datetime):
                plans.append(
                    TimeframePlan(
                        timeframe=timeframe,
                        status="skipped",
                        reason="not_enough_future_data_for_checkpoint_windows",
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        readiness=readiness,
                        historical_coverage=coverage,
                    )
                )
                continue
            if not bool(readiness.get("can_replay_requested_range")):
                plans.append(
                    TimeframePlan(
                        timeframe=timeframe,
                        status="skipped",
                        reason=str(readiness.get("reason", "cannot_replay")),
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        readiness=readiness,
                        historical_coverage=coverage,
                    )
                )
                continue
            windows = tuple(
                self._select_windows(
                    end_at=latest_valid_end,
                    earliest_start_at=coverage.get("earliest_available_historical_bar_at"),
                    eligible_timestamps=int(readiness.get("eligible_timestamps", 0) or 0),
                )
            )
            if not windows:
                plans.append(
                    TimeframePlan(
                        timeframe=timeframe,
                        status="skipped",
                        reason="no_safe_replay_windows",
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        readiness=readiness,
                        historical_coverage=coverage,
                    )
                )
                continue
            plans.append(
                TimeframePlan(
                    timeframe=timeframe,
                    status="ready",
                    reason="ok",
                    available_symbols=available_symbols,
                    available_timeframes=available_timeframes,
                    windows=windows,
                    readiness=readiness,
                    historical_coverage=coverage,
                )
            )
        return plans

    def _select_windows(
        self,
        *,
        end_at: datetime,
        earliest_start_at: datetime | None,
        eligible_timestamps: int,
    ) -> list[ResearchWindow]:
        if eligible_timestamps <= 0:
            return []
        window_count = max(1, self.config.research_min_windows)
        total_span = timedelta(days=max(1, self.config.research_replay_days))
        if isinstance(earliest_start_at, datetime) and (end_at - total_span) < earliest_start_at:
            return []
        window_span = total_span / window_count
        windows: list[ResearchWindow] = []
        cursor = end_at - total_span
        for _ in range(window_count):
            window_end = min(end_at, cursor + window_span)
            windows.append(ResearchWindow(start_at=cursor, end_at=window_end))
            cursor = window_end
        return windows

    def _candidate_windows_for_rejection(
        self,
        *,
        anchor_end_at: datetime,
        count: int,
    ) -> list[ResearchWindow]:
        window_count = max(1, int(count or 1))
        total_span = timedelta(days=max(1, self.config.research_replay_days))
        window_span = total_span / window_count
        windows: list[ResearchWindow] = []
        cursor = anchor_end_at - total_span
        for _ in range(window_count):
            window_end = min(anchor_end_at, cursor + window_span)
            windows.append(ResearchWindow(start_at=cursor, end_at=window_end))
            cursor = window_end
        return windows

    def _timeframe_historical_coverage(
        self,
        *,
        timeframe: str,
        fallback_end_at: datetime | None = None,
    ) -> dict[str, Any]:
        supported_windows = self._supported_checkpoint_windows_for_timeframe(timeframe=timeframe)
        max_future_horizon = timedelta(
            minutes=max(0, self._max_checkpoint_window_minutes_for_timeframe(timeframe=timeframe))
        )
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if not callable(list_historical_bars):
            latest_valid_end = fallback_end_at
            latest_available = (
                fallback_end_at + max_future_horizon
                if isinstance(fallback_end_at, datetime)
                else None
            )
            return {
                "supported_checkpoint_windows": list(supported_windows),
                "max_required_future_horizon": max_future_horizon,
                "earliest_available_historical_bar_at": None,
                "latest_available_historical_bar_at": latest_available,
                "latest_valid_replay_window_end": latest_valid_end,
                "window_anchor_mode": "latest_historical_bar_minus_future_horizon",
                "has_historical_bars": False,
                "fallback_mode": "no_usage_ledger_historical_bar_listing",
            }
        rows = list_historical_bars(
            timeframe=timeframe,
            sources=["alpaca_market_data", "alpaca_crypto_data"],
            symbols=[*self.config.discovery_equity_symbols, *self.config.discovery_crypto_symbols],
        )
        timestamps = sorted(
            row["bar_timestamp"]
            for row in rows
            if isinstance(row.get("bar_timestamp"), datetime)
        )
        earliest = timestamps[0] if timestamps else None
        latest = timestamps[-1] if timestamps else None
        latest_valid_end = None
        if isinstance(latest, datetime):
            latest_valid_end = latest - max_future_horizon
            if isinstance(earliest, datetime) and latest_valid_end < earliest:
                latest_valid_end = None
        return {
            "supported_checkpoint_windows": list(supported_windows),
            "max_required_future_horizon": max_future_horizon,
            "earliest_available_historical_bar_at": earliest,
            "latest_available_historical_bar_at": latest,
            "latest_valid_replay_window_end": latest_valid_end,
            "window_anchor_mode": "latest_historical_bar_minus_future_horizon",
            "has_historical_bars": bool(timestamps),
        }

    def _summarize_plan_anchor_coverage(self, *, plans: list[TimeframePlan]) -> dict[str, Any]:
        latest_values = [
            coverage.get("latest_available_historical_bar_at")
            for coverage in (plan.historical_coverage or {} for plan in plans)
            if isinstance(coverage.get("latest_available_historical_bar_at"), datetime)
        ]
        earliest_values = [
            coverage.get("earliest_available_historical_bar_at")
            for coverage in (plan.historical_coverage or {} for plan in plans)
            if isinstance(coverage.get("earliest_available_historical_bar_at"), datetime)
        ]
        latest_valid_values = [
            coverage.get("latest_valid_replay_window_end")
            for coverage in (plan.historical_coverage or {} for plan in plans)
            if isinstance(coverage.get("latest_valid_replay_window_end"), datetime)
        ]
        max_horizon = max(
            (
                coverage.get("max_required_future_horizon")
                for coverage in (plan.historical_coverage or {} for plan in plans)
                if isinstance(coverage.get("max_required_future_horizon"), timedelta)
            ),
            default=timedelta(0),
        )
        return {
            "earliest_available_historical_bar_at": min(earliest_values) if earliest_values else None,
            "latest_available_historical_bar_at": max(latest_values) if latest_values else None,
            "max_required_future_horizon": max_horizon,
            "latest_valid_replay_window_end": min(latest_valid_values) if latest_valid_values else None,
            "window_anchor_mode": "latest_historical_bar_minus_future_horizon",
            "timeframe_historical_coverage": {
                plan.timeframe: self._serialize_coverage(plan.historical_coverage or {}) for plan in plans
            },
        }

    def _serialize_coverage(self, coverage: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(coverage)
        for key in (
            "earliest_available_historical_bar_at",
            "latest_available_historical_bar_at",
            "latest_valid_replay_window_end",
        ):
            serialized[key] = self._iso_or_blank(serialized.get(key))
        horizon = serialized.get("max_required_future_horizon")
        if isinstance(horizon, timedelta):
            serialized["max_required_future_horizon"] = str(horizon)
        return serialized

    def _supported_checkpoint_windows_for_timeframe(self, *, timeframe: str) -> tuple[str, ...]:
        from app.framework.engine.replay import _supported_checkpoint_windows

        return _supported_checkpoint_windows(
            timeframe=timeframe,
            checkpoint_windows=getattr(
                self.config,
                "shadow_checkpoint_windows",
                ("15m", "1h", "1d", "7d"),
            ),
        )

    def _max_checkpoint_window_minutes_for_timeframe(self, *, timeframe: str) -> int:
        from app.framework.engine.replay import _max_checkpoint_window_minutes

        return _max_checkpoint_window_minutes(
            self._supported_checkpoint_windows_for_timeframe(timeframe=timeframe)
        )

    def _plan_anchor_end_at(self, *, plan: TimeframePlan, fallback_end_at: datetime) -> datetime:
        latest_valid = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
        if isinstance(latest_valid, datetime):
            return latest_valid
        latest_available = (plan.historical_coverage or {}).get("latest_available_historical_bar_at")
        if isinstance(latest_available, datetime):
            return latest_available
        return fallback_end_at

    def _iso_or_blank(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return ""

    def _build_research_decisions(
        self,
        *,
        cycle_id: str,
        created_at: datetime,
        plans: list[TimeframePlan],
        replay_runs_by_timeframe: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        profiles = self._research_profiles()
        decisions: list[dict[str, Any]] = []
        skipped_timeframes = [
            {"timeframe": plan.timeframe, "reason": plan.reason}
            for plan in plans
            if plan.status != "ready"
        ]
        timeframes_used = [plan.timeframe for plan in plans if plan.status == "ready"]
        for plan in plans:
            if plan.status != "ready":
                continue
            for profile in profiles:
                runs = list(replay_runs_by_timeframe.get(plan.timeframe, []))
                decision = self._evaluate_profile(
                    cycle_id=cycle_id,
                    created_at=created_at,
                    profile=profile,
                    timeframe=plan.timeframe,
                    windows=plan.windows,
                    runs=runs,
                    skipped_timeframes=skipped_timeframes,
                    timeframes_used=timeframes_used,
                )
                decisions.append(decision)
        return decisions

    def _evaluate_profile(
        self,
        *,
        cycle_id: str,
        created_at: datetime,
        profile: Any,
        timeframe: str,
        windows: tuple[ResearchWindow, ...],
        runs: list[dict[str, Any]],
        skipped_timeframes: list[dict[str, str]],
        timeframes_used: list[str],
    ) -> dict[str, Any]:
        gross_returns: list[float] = []
        net_returns: list[float] = []
        win_rates: list[float] = []
        adverse_excursions: list[float] = []
        proposals_created = 0
        outcomes_recorded = 0
        candidates_evaluated = 0
        signals_generated = 0
        windows_with_data = 0
        symbol_universe: set[str] = set()

        for run in runs:
            candidates_evaluated += int(run.get("candidates_evaluated", 0) or 0)
            profile_proposals = [
                item
                for item in self._replay_proposals(run)
                if str(item.get("strategy_id", "")) == str(profile.strategy_id)
                and str(item.get("profile_id", "")) == str(profile.profile_id)
            ]
            profile_outcomes = [
                item
                for item in self._replay_outcomes(run)
                if str(item.get("strategy_id", "")) == str(profile.strategy_id)
                and str(item.get("profile_id", "")) == str(profile.profile_id)
            ]
            if not profile_proposals:
                continue
            windows_with_data += 1
            proposals_created += len(profile_proposals)
            signals_generated += len(profile_proposals)
            outcomes_recorded += len(profile_outcomes)
            symbol_universe.update(
                str(item.get("symbol", "")).strip()
                for item in profile_proposals
                if str(item.get("symbol", "")).strip()
            )
            gross_avg = self._mean(
                self._numeric_values(profile_outcomes, key="realized_return_pct")
            )
            gross_returns.append(gross_avg)
            asset_class = str(profile.asset_classes[0] if profile.asset_classes else "")
            net_avg = gross_avg - self._estimated_cost_pct(asset_class=asset_class)
            net_returns.append(net_avg)
            win_rates.append(self._win_rate(profile_outcomes))
            adverse_excursions.append(
                self._mean(
                    self._numeric_values(profile_outcomes, key="max_adverse_excursion_pct")
                )
            )

        sample_ok = proposals_created >= self.config.research_min_proposals
        windows_ok = windows_with_data >= self.config.research_min_windows
        net_avg = self._mean(net_returns)
        win_rate_avg = self._mean(win_rates)
        return_ok = net_avg >= self.config.research_min_net_return_pct
        win_ok = win_rate_avg >= self.config.research_min_net_win_rate
        blocker_reasons = list(skipped_timeframes)
        blocker_labels: list[str] = []
        if not windows_ok:
            blocker_labels.append("insufficient_replay_windows")
        if not sample_ok:
            blocker_labels.append("insufficient_sample_size")
        if not return_ok:
            blocker_labels.append("net_return_below_threshold")
        if not win_ok:
            blocker_labels.append("win_rate_below_threshold")
        if not self.config.include_backtest_evidence_in_paper_fitness:
            blocker_labels.append("paper_allocation_excludes_backtest_evidence")
        if not self.config.include_backtest_evidence_in_live_fitness:
            blocker_labels.append("live_allocation_excludes_backtest_evidence")

        recommendation = "research_only"
        if windows_ok and sample_ok and return_ok and win_ok:
            recommendation = "paper_sim_candidate"
        elif not windows_ok or not sample_ok:
            recommendation = "research_only"
        elif net_avg > 0:
            recommendation = "promising_research"
        elif proposals_created > 0:
            recommendation = "rejected_research"

        data_integrity_status = "pass"
        if skipped_timeframes and not timeframes_used:
            data_integrity_status = "fail"
        elif skipped_timeframes:
            data_integrity_status = "warn"

        return {
            "cycle_id": cycle_id,
            "created_at": created_at,
            "strategy_id": str(profile.strategy_id),
            "profile_id": str(profile.profile_id),
            "asset_class": str(profile.asset_classes[0] if profile.asset_classes else ""),
            "symbol_universe": sorted(symbol_universe),
            "timeframe": timeframe,
            "replay_window_start": windows[0].start_at if windows else created_at,
            "replay_window_end": windows[-1].end_at if windows else created_at,
            "windows_tested_count": len(windows),
            "candidates_evaluated": candidates_evaluated,
            "signals_generated": signals_generated,
            "proposals_created": proposals_created,
            "outcomes_recorded": outcomes_recorded,
            "gross_return_summary": {
                "avg_pct": round(self._mean(gross_returns), 6),
                "windows_with_data": windows_with_data,
            },
            "estimated_cost_assumptions": {
                "simulated_crypto_fee_bps": float(self.config.simulated_crypto_fee_bps),
                "simulated_crypto_slippage_bps": float(
                    self.config.simulated_crypto_slippage_bps
                ),
                "simulated_crypto_spread_bps": float(self.config.simulated_crypto_spread_bps),
            },
            "net_return_summary": {
                "avg_pct": round(net_avg, 6),
                "avg_max_adverse_excursion_pct": round(self._mean(adverse_excursions), 6),
            },
            "win_rate_summary": {"avg": round(win_rate_avg, 6)},
            "sample_size_status": "sufficient" if sample_ok else "insufficient",
            "data_integrity_status": data_integrity_status,
            "recommendation": recommendation,
            "blocker_reasons": [
                *blocker_labels,
                *[
                    f"timeframe:{item.get('timeframe', '-')}/{item.get('reason', '-')}"
                    for item in skipped_timeframes
                ],
            ],
            "source_environment": "backtest",
            "execution_provider": "simulator",
            "windows_used": [
                {
                    "start_at": window.start_at.isoformat(),
                    "end_at": window.end_at.isoformat(),
                }
                for window in windows
            ],
            "timeframes_used": list(timeframes_used),
            "timeframes_skipped": list(skipped_timeframes),
            "paper_fitness_includes_backtest": bool(
                self.config.include_backtest_evidence_in_paper_fitness
            ),
            "live_fitness_includes_backtest": bool(
                self.config.include_backtest_evidence_in_live_fitness
            ),
            "research_only_profile": bool(getattr(profile, "parameters", {}).get("research_only")),
        }

    def _build_state_snapshot(
        self,
        *,
        cycle_id: str,
        started_at: datetime,
        plans: list[TimeframePlan],
        diagnostics: dict[str, Any],
        replay_run_ids: list[str],
        decisions: list[dict[str, Any]],
        comparison: dict[str, Any],
        inventory: dict[str, Any],
        profile_count: int,
        usable_decisions_count: int,
        paper_candidates_created: int,
        paper_removal_candidates_created: int,
        decisions_written: int,
    ) -> dict[str, Any]:
        grouped_strategies: dict[str, Any] = {}
        for decision in decisions:
            grouped_strategies[f"{decision['strategy_id']}::{decision['profile_id']}"] = {
                "classification": decision["recommendation"],
                "promotion_recommendation": decision["recommendation"],
                "replay_windows_with_data": int(decision["windows_tested_count"]),
                "replay_windows_required": int(self.config.research_min_windows),
                "proposal_count": int(decision["proposals_created"]),
                "sample_size_status": decision["sample_size_status"],
                "gross_performance_pct": (
                    decision.get("gross_return_summary", {}) or {}
                ).get("avg_pct", 0.0),
                "net_performance_pct": (decision.get("net_return_summary", {}) or {}).get(
                    "avg_pct", 0.0
                ),
                "net_win_rate": (decision.get("win_rate_summary", {}) or {}).get("avg", 0.0),
                "blocked_from_execution_reasons": list(decision.get("blocker_reasons", [])),
                "allocation_includes_backtest_evidence": {
                    "paper": bool(decision.get("paper_fitness_includes_backtest")),
                    "live": bool(decision.get("live_fitness_includes_backtest")),
                },
            }
        return {
            "run": {
                "pipeline": "research_cycle",
                "research_cycle_id": cycle_id,
                "source": self.source,
                "parent_tick_id": self.parent_tick_id,
                "research_started_at": started_at.isoformat(),
                "research_cycle_enabled": bool(self.config.research_cycle_enabled),
                "timeframe": self.config.research_replay_timeframe,
                "days": self.config.research_replay_days,
                "max_replay_timestamps": self.config.research_max_replay_timestamps,
            },
            "research_cycle": {
                "status": "ok",
                "completed_at": started_at.isoformat(),
                "available_symbols": (
                    inventory.get("historical", {}) or {}
                ).get("distinct_symbols", 0),
                "historical_readiness": inventory.get("replay_readiness", {}),
                "historical_windows_selected": int(
                    diagnostics.get("historical_windows_selected", 0) or 0
                ),
                "replay_windows_accepted_count": int(
                    diagnostics.get("replay_windows_accepted_count", 0) or 0
                ),
                "replay_windows_rejected_count": int(
                    diagnostics.get("replay_windows_rejected_count", 0) or 0
                ),
                "earliest_available_historical_bar_at": self._iso_or_blank(
                    diagnostics.get("earliest_available_historical_bar_at")
                ),
                "latest_available_historical_bar_at": self._iso_or_blank(
                    diagnostics.get("latest_available_historical_bar_at")
                ),
                "max_required_future_horizon": str(
                    diagnostics.get("max_required_future_horizon", "") or ""
                ),
                "latest_valid_replay_window_end": self._iso_or_blank(
                    diagnostics.get("latest_valid_replay_window_end")
                ),
                "window_anchor_mode": str(diagnostics.get("window_anchor_mode", "") or ""),
                "timeframes_used": [plan.timeframe for plan in plans if plan.status == "ready"],
                "timeframes_skipped": [
                    {"timeframe": plan.timeframe, "reason": plan.reason}
                    for plan in plans
                    if plan.status != "ready"
                ],
                "replay_windows_tested": [
                    {
                        "timeframe": plan.timeframe,
                        "start_at": window.start_at.isoformat(),
                        "end_at": window.end_at.isoformat(),
                    }
                    for plan in plans
                    if plan.status == "ready"
                    for window in plan.windows
                ],
                "replay_window_candidates": list(
                    diagnostics.get("replay_window_candidates", []) or []
                ),
                "replay_window_acceptances": list(
                    diagnostics.get("replay_window_acceptances", []) or []
                ),
                "replay_window_rejections": list(
                    diagnostics.get("replay_window_rejections", []) or []
                ),
                "strategies": grouped_strategies,
                "decisions": decisions,
                "comparison": comparison,
                "replay_run_ids": replay_run_ids,
                "strategy_profiles_discovered": profile_count,
                "strategy_profiles_evaluated": profile_count,
                "research_decisions_written": int(decisions_written or 0),
                "usable_decisions_count": usable_decisions_count,
                "paper_candidates_created": paper_candidates_created,
                "paper_removal_candidates_created": paper_removal_candidates_created,
                "blockers": sorted(
                    {
                        str(reason)
                        for decision in decisions
                        for reason in list(decision.get("blocker_reasons", []) or [])
                        if str(reason).strip()
                    }
                ),
                "allocation_guardrails": {
                    "include_backtest_evidence_in_paper_fitness": bool(
                        self.config.include_backtest_evidence_in_paper_fitness
                    ),
                    "include_backtest_evidence_in_live_fitness": bool(
                        self.config.include_backtest_evidence_in_live_fitness
                    ),
                    "auto_promotion_enabled": False,
                },
                "paper_live_execution_effect": "none",
                "live_execution_remains_disabled": True,
            },
        }

    def _research_profiles(self) -> list[Any]:
        profiles: list[Any] = []
        for strategy in build_strategy_registry():
            try:
                strategy_profiles = strategy.build_profiles(self.config)
            except Exception:
                continue
            for profile in strategy_profiles:
                profiles.append(profile)
        return profiles

    def _replay_proposals(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        replay_run_id = str(run.get("replay_run_id", "") or "")
        if not replay_run_id:
            return []
        return self.usage_ledger.list_shadow_trade_proposals_by_note_prefix(
            note_prefix=f"historical_replay:{replay_run_id}:"
        )

    def _replay_outcomes(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        replay_run_id = str(run.get("replay_run_id", "") or "")
        if not replay_run_id:
            return []
        return self.usage_ledger.list_shadow_trade_outcomes_by_note_prefix(
            note_prefix=f"historical_replay:{replay_run_id}:"
        )

    def _estimated_cost_pct(self, *, asset_class: str) -> float:
        if str(asset_class).lower() != "crypto":
            return 0.0
        fee = float(self.config.simulated_crypto_fee_bps) * 2.0 / 100.0
        spread = float(self.config.simulated_crypto_spread_bps) / 100.0
        slippage = float(self.config.simulated_crypto_slippage_bps) * 2.0 / 100.0
        return fee + spread + slippage

    def _win_rate(self, outcomes: list[dict[str, Any]]) -> float:
        realized = self._numeric_values(outcomes, key="realized_return_pct")
        if not realized:
            return 0.0
        return sum(1 for value in realized if value > 0) / len(realized)

    def _numeric_values(self, rows: list[dict[str, Any]], *, key: str) -> list[float]:
        values: list[float] = []
        for row in rows:
            value = row.get(key)
            try:
                if value is None:
                    continue
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        return values

    def _mean(self, values: list[float]) -> float:
        return round(mean(values), 6) if values else 0.0

    def _ordered_unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered
