from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
import hashlib
import os
from pathlib import Path
from statistics import mean
import subprocess
from time import perf_counter
from typing import Any

from app.framework.engine.backfill import HistoricalBackfillRunner
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
    bucket_id: str = ""
    asset_class: str = ""
    equity_symbols: tuple[str, ...] = tuple()
    crypto_symbols: tuple[str, ...] = tuple()
    windows: tuple[ResearchWindow, ...] = tuple()
    readiness: dict[str, Any] | None = None
    historical_coverage: dict[str, Any] | None = None


class ResearchCycleAlreadyRunningError(RuntimeError):
    """Raised when a second research cycle would overlap an active one."""


class ResearchCycleRunner:
    """Run autonomous replay research and persist evidence without enabling execution."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        source: str = "manual_cli",
        parent_tick_id: str = "",
        cycle_origin: str = "manual_cli",
        parent_process_mode: str = "unknown",
        command_source: str = "unknown",
        force_mode: bool = False,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.source = str(source or "manual_cli").strip() or "manual_cli"
        self.parent_tick_id = str(parent_tick_id or "").strip()
        self.cycle_origin = str(cycle_origin or "manual_cli").strip() or "manual_cli"
        self.parent_process_mode = str(parent_process_mode or "unknown").strip() or "unknown"
        self.command_source = str(command_source or "unknown").strip() or "unknown"
        self.force_mode = bool(force_mode)
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
        lock_state = self._acquire_research_cycle_singleton()
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        cycle_id = f"researchcycle-{started_at.strftime('%Y%m%d-%H%M%S-%f')}"
        os.environ["CENTAUR_RESEARCH_CYCLE_ID_IF_KNOWN"] = cycle_id
        try:
            pre_replay_refresh = self._run_pre_replay_historical_refresh(as_of=started_at)
            diagnostics = self.build_historical_replay_diagnostics(
                end_at=started_at,
                pre_replay_refresh=pre_replay_refresh,
            )
            inventory = diagnostics["inventory"]
            plans = diagnostics["plans"]
            selected_windows_by_bucket = dict(diagnostics.get("_selected_windows_by_bucket", {}) or {})
            cursor_updates: list[dict[str, Any]] = []
            replay_evidence_new_rows_inserted = 0

            replay_runs_by_timeframe: dict[str, list[dict[str, Any]]] = defaultdict(list)
            replay_run_ids: list[str] = []
            for plan in plans:
                if plan.status != "ready":
                    continue
                for window in plan.windows:
                    replay = self.replay_runner.run(
                        days=self.config.research_replay_days,
                        timeframe=plan.timeframe,
                        equity_symbols=plan.equity_symbols or self.config.discovery_equity_symbols,
                        crypto_symbols=plan.crypto_symbols or self.config.discovery_crypto_symbols,
                        max_timestamps=self.config.research_max_replay_timestamps,
                        start_at=window.start_at,
                        end_at=window.end_at,
                        dry_run=False,
                    )
                    replay_run_ids.append(replay.tick_id)
                    replay_snapshot = dict(getattr(replay, "state_snapshot", {}) or {})
                    training_state = dict(replay_snapshot.get("historical_replay_training", {}) or {})
                    fitness_state = dict(replay_snapshot.get("historical_replay_fitness", {}) or {})
                    replay_evidence_new_rows_inserted += int(training_state.get("outcomes_recorded", 0) or 0)
                    replay_evidence_new_rows_inserted += int(fitness_state.get("summaries_saved", 0) or 0)
                    replay_runs_by_timeframe[plan.timeframe].append(
                        self.summary_report.build_report(replay_run_id=replay.tick_id)
                    )
                    if bool(getattr(self.config, "rolling_replay_cursor_enabled", False)):
                        bucket = str(plan.bucket_id or "").strip()
                        selected_for_bucket = list(selected_windows_by_bucket.get(bucket, []) or [])
                        selected_hash = self._window_set_hash(selected_for_bucket)
                        cursor_updates.append(
                            {
                                "bucket": bucket,
                                "last_replayed_until": window.end_at,
                                "last_selected_window_hash": selected_hash,
                            }
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
                if str(item.get("recommendation", "")) == "paper_candidate"
            )
            paper_removal_candidates_created = sum(
                1
                for item in decisions
                if str(item.get("recommendation", "")) == "paper_removal_candidate"
            )
            decisions_written = self.usage_ledger.record_research_cycle_decisions(decisions=decisions)
            if decisions_written and cursor_updates:
                for item in cursor_updates:
                    self.usage_ledger.upsert_replay_progress_cursor(
                        bucket=str(item.get("bucket", "") or ""),
                        last_replayed_until=item["last_replayed_until"],
                        last_selected_window_hash=str(item.get("last_selected_window_hash", "") or ""),
                        last_research_cycle_id=cycle_id,
                        last_updated_at=started_at,
                    )
            diagnostics["replay_evidence_new_rows_inserted"] = replay_evidence_new_rows_inserted
            diagnostics["replay_evidence_duplicate_rows_skipped"] = int(
                diagnostics.get("duplicate_replay_windows_skipped_count", 0) or 0
            )
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
        finally:
            os.environ.pop("CENTAUR_RESEARCH_CYCLE_ID_IF_KNOWN", None)
            self._release_research_cycle_singleton(lock_state)

    def build_historical_replay_diagnostics(
        self,
        *,
        end_at: datetime | None = None,
        pre_replay_refresh: dict[str, Any] | None = None,
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
        raw_plans = list(plans)
        selection_anchor_end_at = self._diagnostic_selection_anchor_end_at(
            plans=plans,
            fallback_end_at=resolved_end_at,
        )
        inventory = self.bars_report.build_report(
            days=self.config.research_replay_days,
            timeframe=self.config.research_replay_timeframe,
            crypto_symbols=self.config.discovery_crypto_symbols,
            equity_symbols=self.config.discovery_equity_symbols,
            end_at=selection_anchor_end_at,
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
        pre_replay_refresh_diagnostics = self._merge_pre_replay_refresh_diagnostics(
            refresh_state=pre_replay_refresh,
            plans=raw_plans,
            latest_available_historical_bar_at=anchor_summary.get(
                "latest_available_historical_bar_at"
            ),
            selection_anchor_end_at=selection_anchor_end_at,
            as_of=resolved_end_at,
        )
        rolling_diagnostics = self._build_rolling_replay_diagnostics(
            plans=raw_plans,
            previous_cycles=self._recent_self_improvement_cycles(limit=2),
        )
        plans = self._apply_rolling_replay_selection(
            plans=plans,
            rolling_diagnostics=rolling_diagnostics,
        )
        selected_windows_by_bucket = self._selected_windows_by_bucket(plans=plans)
        return {
            "inventory": inventory,
            "plans": plans,
            "replay_window_candidates": replay_window_candidates,
            "replay_window_acceptances": replay_window_acceptances,
            "replay_window_rejections": replay_window_rejections,
            "historical_windows_selected": len(replay_window_acceptances),
            "replay_windows_accepted_count": len(replay_window_acceptances),
            "replay_windows_rejected_count": len(replay_window_rejections),
            "selection_anchor_end_at": selection_anchor_end_at,
            **pre_replay_refresh_diagnostics,
            **rolling_diagnostics,
            **anchor_summary,
            "_selected_windows_by_bucket": selected_windows_by_bucket,
        }

    def _recent_self_improvement_cycles(self, *, limit: int) -> list[dict[str, Any]]:
        rows = getattr(self.usage_ledger, "list_recent_tick_runs", lambda limit=0: [])(limit=limit + 8)
        cycles: list[dict[str, Any]] = []
        for row in rows:
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            run = snapshot.get("run", {})
            state = snapshot.get("research_cycle", {})
            if not isinstance(run, dict) or not isinstance(state, dict):
                continue
            if str(run.get("pipeline", "") or "") != "research_cycle":
                continue
            if str(run.get("source", "") or "") != "real_heartbeat":
                continue
            cycles.append(state)
            if len(cycles) >= limit:
                break
        return cycles

    def _build_rolling_replay_diagnostics(
        self,
        *,
        plans: list[TimeframePlan],
        previous_cycles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rolling_enabled = bool(getattr(self.config, "rolling_replay_cursor_enabled", False))
        cursor_rows = {
            str(item.get("bucket", "") or ""): item
            for item in list(getattr(self.usage_ledger, "list_replay_progress_cursors", lambda: [])() or [])
            if str(item.get("bucket", "") or "").strip()
        }
        latest_by_bucket: dict[str, str] = {}
        previous_by_bucket: dict[str, str] = {}
        last_replayed_until_by_bucket: dict[str, str] = {}
        unseen_available_by_bucket: dict[str, str] = {}
        next_start_by_bucket: dict[str, str] = {}
        next_end_by_bucket: dict[str, str] = {}
        delta_by_bucket: dict[str, str] = {}
        replay_modes: dict[str, str] = {}
        selected_current: list[str] = []
        duplicate_skipped = 0
        new_selected = 0
        previous_state = previous_cycles[1] if len(previous_cycles) > 1 else (previous_cycles[0] if previous_cycles else {})
        previous_selected_map = dict(previous_state.get("selected_replay_window_end_by_bucket", {}) or {})
        previous_hash_map = dict(previous_state.get("selected_window_ids_current", {}) or {})
        for plan in plans:
            bucket = str(plan.bucket_id or "").strip()
            latest_valid = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if bucket and isinstance(latest_valid, datetime):
                latest_by_bucket[bucket] = latest_valid.isoformat()
            if bucket:
                prev_value = str(previous_selected_map.get(bucket, "") or "").strip()
                if prev_value:
                    previous_by_bucket[bucket] = prev_value
            if bucket in latest_by_bucket and bucket in previous_by_bucket:
                delta_by_bucket[bucket] = self._format_delta_between_iso(
                    previous_by_bucket[bucket],
                    latest_by_bucket[bucket],
                )
            cursor = cursor_rows.get(bucket, {})
            last_replayed = self._coerce_datetime(cursor.get("last_replayed_until"))
            if isinstance(last_replayed, datetime):
                last_replayed_until_by_bucket[bucket] = last_replayed.isoformat()
            latest_valid = self._coerce_datetime(latest_by_bucket.get(bucket, ""))
            unseen_available = bool(isinstance(latest_valid, datetime) and ((last_replayed is None) or latest_valid > last_replayed))
            unseen_available_by_bucket[bucket] = "yes" if unseen_available else "no"
            if isinstance(last_replayed, datetime):
                next_start_by_bucket[bucket] = last_replayed.isoformat()
            if unseen_available and isinstance(latest_valid, datetime):
                next_end_by_bucket[bucket] = latest_valid.isoformat()
            candidate_rows = (
                [
                    {
                        "bucket": bucket,
                        "start_at": next_start_by_bucket.get(bucket, ""),
                        "end_at": next_end_by_bucket.get(bucket, ""),
                    }
                ]
                if unseen_available and rolling_enabled
                else (
                    []
                    if rolling_enabled
                    else [
                        {
                            "bucket": bucket,
                            "start_at": window.start_at.isoformat(),
                            "end_at": window.end_at.isoformat(),
                        }
                        for window in plan.windows
                    ]
                )
            )
            selected_hash = self._window_set_hash(candidate_rows)
            if bucket and selected_hash:
                selected_current.append(f"{bucket}:{selected_hash}")
                if selected_hash and selected_hash == str(cursor.get("last_selected_window_hash", "") or ""):
                    duplicate_skipped += 1
                elif selected_hash:
                    new_selected += 1
            if rolling_enabled:
                if not isinstance(last_replayed, datetime):
                    replay_modes[bucket] = "bootstrap"
                elif unseen_available:
                    replay_modes[bucket] = "rolling"
                else:
                    replay_modes[bucket] = "rolling"
            else:
                replay_modes[bucket] = "global_latest_window"
        previous_selected = dict(previous_hash_map)
        current_selected_map = self._mapping_from_window_id_rows(selected_current)
        selected_changed = "yes" if current_selected_map and current_selected_map != previous_selected else ("no" if previous_selected else "unknown")
        learning_progress = "yes" if new_selected > 0 and duplicate_skipped < max(1, len(current_selected_map)) else "no"
        no_progress_reason = "-"
        if learning_progress == "no":
            if rolling_enabled and all(value == "no" for value in unseen_available_by_bucket.values()) and unseen_available_by_bucket:
                no_progress_reason = "no_new_replay_eligible_slice"
            elif selected_changed == "no":
                no_progress_reason = "same_replay_windows_as_previous_cycle"
            elif duplicate_skipped > 0:
                no_progress_reason = "duplicate_replay_window"
            else:
                no_progress_reason = "no_replay_windows_selected"
        return {
            "rolling_replay_mode_enabled": "yes" if rolling_enabled else "no",
            "rolling_replay_cursor_enabled": "yes" if rolling_enabled else "no",
            "replay_mode": "rolling" if rolling_enabled else "global_latest_window",
            "latest_replay_eligible_at_by_bucket": latest_by_bucket,
            "previous_replay_eligible_at_by_bucket": previous_by_bucket,
            "replay_eligible_advance_delta_by_bucket": delta_by_bucket,
            "last_replayed_until_by_bucket": last_replayed_until_by_bucket,
            "unseen_replay_range_available_by_bucket": unseen_available_by_bucket,
            "next_unseen_replay_start_by_bucket": next_start_by_bucket,
            "next_unseen_replay_end_by_bucket": next_end_by_bucket,
            "selected_window_ids_current": current_selected_map,
            "selected_window_ids_previous": previous_selected,
            "selected_window_set_changed": selected_changed,
            "new_replay_windows_selected_count": new_selected,
            "duplicate_replay_windows_skipped_count": duplicate_skipped,
            "replay_evidence_new_rows_inserted": 0,
            "replay_evidence_duplicate_rows_skipped": 0,
            "learning_progress_this_cycle": learning_progress,
            "reason_replay_window_not_advancing": no_progress_reason if selected_changed == "no" else "-",
            "reason_no_learning_progress": no_progress_reason,
            "replay_mode_by_bucket": replay_modes,
            "_cursor_window_hash_by_bucket": {
                bucket: str(item.get("last_selected_window_hash", "") or "")
                for bucket, item in cursor_rows.items()
            },
        }

    def _apply_rolling_replay_selection(
        self,
        *,
        plans: list[TimeframePlan],
        rolling_diagnostics: dict[str, Any],
    ) -> list[TimeframePlan]:
        if not bool(getattr(self.config, "rolling_replay_cursor_enabled", False)):
            return plans
        next_start = dict(rolling_diagnostics.get("next_unseen_replay_start_by_bucket", {}) or {})
        next_end = dict(rolling_diagnostics.get("next_unseen_replay_end_by_bucket", {}) or {})
        last_replayed = dict(rolling_diagnostics.get("last_replayed_until_by_bucket", {}) or {})
        cursor_hash_by_bucket = dict(rolling_diagnostics.get("_cursor_window_hash_by_bucket", {}) or {})
        result: list[TimeframePlan] = []
        for plan in plans:
            bucket = str(plan.bucket_id or "").strip()
            start_at = self._coerce_datetime(next_start.get(bucket, ""))
            end_at = self._coerce_datetime(next_end.get(bucket, ""))
            if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
                result.append(plan)
                continue
            if end_at <= start_at:
                result.append(
                    replace(plan, status="skipped", reason="no_new_replay_eligible_slice", windows=tuple())
                )
                continue
            if last_replayed.get(bucket) and self._window_set_hash([
                {"bucket": bucket, "start_at": start_at.isoformat(), "end_at": end_at.isoformat()}
            ]) == str(cursor_hash_by_bucket.get(bucket, "") or ""):
                result.append(
                    replace(plan, status="skipped", reason="duplicate_replay_window", windows=tuple())
                )
                continue
            result.append(
                replace(plan, windows=(ResearchWindow(start_at=start_at, end_at=end_at),))
            )
        return result

    def _selected_windows_by_bucket(self, *, plans: list[TimeframePlan]) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        for plan in plans:
            bucket = str(plan.bucket_id or "").strip()
            if not bucket or plan.status != "ready":
                continue
            result[bucket] = [
                {
                    "bucket": bucket,
                    "start_at": window.start_at.isoformat(),
                    "end_at": window.end_at.isoformat(),
                }
                for window in plan.windows
            ]
        return result

    def _window_set_hash(self, rows: list[dict[str, Any]]) -> str:
        payload = [
            {
                "bucket": str(item.get("bucket", "") or ""),
                "start_at": str(item.get("start_at", "") or ""),
                "end_at": str(item.get("end_at", "") or ""),
            }
            for item in rows
        ]
        if not payload:
            return ""
        return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:16]

    def _mapping_from_window_id_rows(self, rows: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in rows:
            bucket, _, window_id = str(row).partition(":")
            if bucket and window_id:
                result[bucket] = window_id
        return dict(sorted(result.items()))

    def _format_delta_between_iso(self, older_text: str, newer_text: str) -> str:
        older = self._coerce_datetime(older_text)
        newer = self._coerce_datetime(newer_text)
        if not isinstance(older, datetime) or not isinstance(newer, datetime):
            return "unknown"
        if newer <= older:
            return "0s"
        return self._format_timedelta(newer - older)

    def _merge_pre_replay_refresh_diagnostics(
        self,
        *,
        refresh_state: dict[str, Any] | None,
        plans: list[TimeframePlan],
        latest_available_historical_bar_at: datetime | None,
        selection_anchor_end_at: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        default_refresh_state = self._default_pre_replay_refresh_state(as_of=as_of)
        merged_refresh_state = {**default_refresh_state, **dict(refresh_state or {})}
        latest_before = self._coerce_datetime(
            merged_refresh_state.get("latest_bar_before_refresh")
        ) or latest_available_historical_bar_at
        latest_after = self._coerce_datetime(
            merged_refresh_state.get("latest_bar_after_refresh")
        ) or latest_available_historical_bar_at
        selector_diagnostics = self._build_replay_window_selector_diagnostics(
            plans=plans,
            latest_after=latest_after,
            selection_anchor_end_at=selection_anchor_end_at,
        )
        if latest_after is None:
            selector_diagnostics["replay_windows_selected_from_latest_available_data"] = "no"
            selector_diagnostics[
                "reason_latest_bars_not_used_for_replay"
            ] = "no_historical_bars_available_for_requested_symbol_universe"
        elif selection_anchor_end_at > latest_after:
            selector_diagnostics["replay_windows_selected_from_latest_available_data"] = "no"
            selector_diagnostics[
                "reason_latest_bars_not_used_for_replay"
            ] = "selection_anchor_is_newer_than_latest_available_historical_bar"
        asset_class_freshness_status = {
            "equity": self._historical_asset_class_freshness(
                asset_class="equity",
                as_of=as_of,
            ),
            "crypto": self._historical_asset_class_freshness(
                asset_class="crypto",
                as_of=as_of,
            ),
        }
        return {
            **merged_refresh_state,
            "ingestion_ran_this_cycle": (
                "yes"
                if str(merged_refresh_state.get("pre_replay_refresh_ran", "no")) == "yes"
                and str(merged_refresh_state.get("pre_replay_refresh_mode", "disabled"))
                == "write"
                else "no"
            ),
            "bars_inserted_this_cycle": int(
                merged_refresh_state.get("bars_inserted_by_refresh", 0) or 0
            ),
            "bars_updated_this_cycle": int(
                merged_refresh_state.get("bars_updated_by_refresh", 0) or 0
            ),
            "latest_bar_before_ingestion": latest_before,
            "latest_bar_after_ingestion": latest_after,
            "replay_windows_selected_from_latest_available_data": str(
                selector_diagnostics.get(
                    "replay_windows_selected_from_latest_available_data",
                    "unknown",
                )
                or "unknown"
            ),
            "reason_if_not": str(
                selector_diagnostics.get("reason_latest_bars_not_used_for_replay", "") or ""
            ),
            **selector_diagnostics,
            "asset_class_freshness_status": asset_class_freshness_status,
        }

    def _build_replay_window_selector_diagnostics(
        self,
        *,
        plans: list[TimeframePlan],
        latest_after: datetime | None,
        selection_anchor_end_at: datetime,
    ) -> dict[str, Any]:
        latest_available_by_asset_class = self._latest_available_bar_per_asset_class(
            plans=plans
        )
        latest_available_by_symbol = self._latest_available_bar_per_symbol()
        latest_replay_eligible_by_timeframe = self._latest_replay_eligible_bar_per_timeframe(
            plans=plans
        )
        latest_replay_eligible_by_asset_class = self._latest_replay_eligible_bar_per_asset_class(
            plans=plans,
            latest_by_symbol=latest_available_by_symbol,
        )
        candidate_replay_windows_considered: list[dict[str, Any]] = []
        candidate_replay_windows_rejected: list[dict[str, Any]] = []
        selected_replay_windows: list[dict[str, Any]] = []
        selected_reasons: list[str] = []
        selected_end_times: list[datetime] = []
        requested_windows = max(1, int(self.config.research_min_windows or 1))

        for plan in plans:
            asset_class = self._infer_asset_class_for_plan(
                plan=plan,
                latest_by_symbol=latest_available_by_symbol,
            )
            coverage = dict(plan.historical_coverage or {})
            plan_anchor_end_at = self._plan_anchor_end_at(
                plan=plan,
                fallback_end_at=selection_anchor_end_at,
            )
            candidate_windows = list(plan.windows) or self._candidate_windows_for_rejection(
                anchor_end_at=plan_anchor_end_at,
                count=requested_windows,
            )
            for index, window in enumerate(candidate_windows, start=1):
                row = {
                    "bucket": plan.bucket_id or f"{asset_class}/{plan.timeframe}",
                    "asset_class": asset_class,
                    "timeframe": plan.timeframe,
                    "window_index": index,
                    "start_at": window.start_at.isoformat(),
                    "end_at": window.end_at.isoformat(),
                    "status": plan.status,
                    "reason": plan.reason,
                    "latest_available_historical_bar_at": self._iso_or_blank(
                        coverage.get("latest_available_historical_bar_at")
                    ),
                    "latest_valid_replay_window_end": self._iso_or_blank(
                        coverage.get("latest_valid_replay_window_end")
                    ),
                    "max_required_future_horizon": (
                        str(coverage.get("max_required_future_horizon"))
                        if isinstance(
                            coverage.get("max_required_future_horizon"), timedelta
                        )
                        else ""
                    ),
                }
                candidate_replay_windows_considered.append(row)
                if plan.status == "ready":
                    selected_replay_windows.append(row)
                    selected_reasons.append(str(plan.reason or "ok"))
                    selected_end_times.append(window.end_at)
                else:
                    candidate_replay_windows_rejected.append(row)

        selected_end_by_timeframe = self._selected_replay_window_end_by_timeframe(
            rows=selected_replay_windows
        )
        selected_end_by_asset_class = self._selected_replay_window_end_by_asset_class(
            rows=selected_replay_windows
        )
        selected_end_by_bucket = self._selected_replay_window_end_by_bucket(
            rows=selected_replay_windows
        )
        accepted_count_by_timeframe = self._accepted_replay_window_count_by_timeframe(
            rows=selected_replay_windows
        )
        accepted_count_by_asset_class = self._accepted_replay_window_count_by_asset_class(
            rows=selected_replay_windows
        )
        windows_selected_by_bucket = self._accepted_replay_window_count_by_bucket(
            rows=selected_replay_windows
        )
        windows_rejected_by_bucket = self._accepted_replay_window_count_by_bucket(
            rows=candidate_replay_windows_rejected
        )
        bucket_rejection_reasons = self._bucket_rejection_reasons(
            plans=plans
        )
        selected_anchor_time_by_bucket = self._selected_anchor_time_by_bucket(
            rows=selected_replay_windows
        )
        candidate_anchor_time_by_bucket = self._candidate_anchor_time_by_bucket(plans=plans)
        rejected_bucket_anchor_time_by_bucket = self._rejected_bucket_anchor_time_by_bucket(
            plans=plans
        )
        global_anchor_constraint = self._global_anchor_constraint(
            plans=plans,
            selection_anchor_end_at=selection_anchor_end_at,
            latest_by_symbol=latest_available_by_symbol,
        )
        max_future_horizon = max(
            (
                (plan.historical_coverage or {}).get("max_required_future_horizon")
                for plan in plans
                if isinstance(
                    (plan.historical_coverage or {}).get("max_required_future_horizon"),
                    timedelta,
                )
            ),
            default=timedelta(0),
        )
        latest_replay_eligible_bar_at = self._maximum_datetime_from_iso_map(
            latest_replay_eligible_by_timeframe
        )
        freshness_lost_to_future_outcome_horizon = self._format_timedelta_or_unknown(
            self._freshness_gap(
                latest_after,
                latest_replay_eligible_bar_at,
            )
        )
        freshness_lost_to_global_anchor = self._format_timedelta_or_unknown(
            self._freshness_gap(
                latest_replay_eligible_bar_at,
                selection_anchor_end_at,
            )
        )
        simulated_modes = self._simulated_replay_selection_modes(
            plans=plans,
            latest_by_symbol=latest_available_by_symbol,
            global_anchor_end_at=selection_anchor_end_at,
        )
        reason_latest_bars_not_used = ""
        replay_windows_selected_from_latest_available_data = "unknown"
        if latest_after is None:
            replay_windows_selected_from_latest_available_data = "no"
            reason_latest_bars_not_used = (
                "no_historical_bars_available_for_requested_symbol_universe"
            )
        elif selected_end_times:
            newest_selected_end = max(selected_end_times)
            if newest_selected_end == latest_after:
                replay_windows_selected_from_latest_available_data = "yes"
                reason_latest_bars_not_used = (
                    "latest_available_bar_timestamp_is_itself_replay_eligible"
                )
            else:
                replay_windows_selected_from_latest_available_data = "no"
                reason_latest_bars_not_used = self._explain_latest_bar_gap(
                    plans=plans,
                    latest_after=latest_after,
                    selection_anchor_end_at=selection_anchor_end_at,
                    latest_by_symbol=latest_available_by_symbol,
                )
        else:
            replay_windows_selected_from_latest_available_data = "no"
            reason_latest_bars_not_used = "no_replay_windows_selected"

        return {
            "latest_raw_bar_at": self._iso_or_blank(latest_after),
            "max_future_outcome_horizon": self._format_timedelta(max_future_horizon),
            "latest_replay_eligible_bar_at": self._iso_or_blank(latest_replay_eligible_bar_at),
            "latest_available_bar_per_asset_class": latest_available_by_asset_class,
            "latest_available_bar_per_symbol": latest_available_by_symbol,
            "latest_replay_eligible_bar_per_timeframe": latest_replay_eligible_by_timeframe,
            "latest_replay_eligible_bar_per_asset_class": latest_replay_eligible_by_asset_class,
            "candidate_replay_windows_considered": candidate_replay_windows_considered,
            "candidate_replay_windows_rejected": candidate_replay_windows_rejected,
            "selected_replay_windows": selected_replay_windows,
            "selected_replay_window_reason": (
                "latest_available_bar_timestamp_used_directly"
                if replay_windows_selected_from_latest_available_data == "yes"
                else self._join_reasons(selected_reasons) or "no_replay_windows_selected"
            ),
            "max_allowed_replay_window_end": self._iso_or_blank(selection_anchor_end_at),
            "global_anchor_enabled": "yes" if len(plans) > 1 else "no",
            "global_anchor_time": self._iso_or_blank(selection_anchor_end_at),
            "global_anchor_constrained_by_asset_class": global_anchor_constraint.get(
                "asset_class", ""
            ),
            "global_anchor_constrained_by_timeframe": global_anchor_constraint.get(
                "timeframe", ""
            ),
            "global_anchor_constrained_by_symbol": global_anchor_constraint.get(
                "symbol", ""
            ),
            "freshness_lost_to_future_outcome_horizon": freshness_lost_to_future_outcome_horizon,
            "freshness_lost_to_global_anchor": freshness_lost_to_global_anchor,
            "selected_replay_window_end_by_timeframe": selected_end_by_timeframe,
            "selected_replay_window_end_by_asset_class": selected_end_by_asset_class,
            "selected_replay_window_end_by_bucket": selected_end_by_bucket,
            "accepted_replay_window_count_by_timeframe": accepted_count_by_timeframe,
            "accepted_replay_window_count_by_asset_class": accepted_count_by_asset_class,
            "selected_anchor_time_by_bucket": selected_anchor_time_by_bucket,
            "candidate_anchor_time_by_bucket": candidate_anchor_time_by_bucket,
            "rejected_bucket_anchor_time_by_bucket": rejected_bucket_anchor_time_by_bucket,
            "freshness_gain_vs_global_by_bucket": self._freshness_gain_map(
                anchors=selected_anchor_time_by_bucket,
                global_anchor_end_at=selection_anchor_end_at,
            ),
            "windows_selected_by_bucket": windows_selected_by_bucket,
            "windows_rejected_by_bucket": windows_rejected_by_bucket,
            "bucket_rejection_reasons": bucket_rejection_reasons,
            "replay_selection_mode": str(
                getattr(self.config, "replay_window_selection_mode", "global") or "global"
            ),
            "alternative_replay_selection_modes_available": (
                "yes" if simulated_modes.get("alternative_modes_available") else "no"
            ),
            "simulated_asset_class_anchor_time": dict(
                simulated_modes.get("asset_class_anchor_time", {}) or {}
            ),
            "simulated_asset_class_and_timeframe_anchor_time": dict(
                simulated_modes.get("asset_class_and_timeframe_anchor_time", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class": dict(
                simulated_modes.get("freshness_gain_by_asset_class", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class_and_timeframe": dict(
                simulated_modes.get("freshness_gain_by_asset_class_and_timeframe", {}) or {}
            ),
            "strategies_helped_by_isolated_replay": list(
                simulated_modes.get("strategies_helped_by_isolated_replay", []) or []
            ),
            "strategies_unaffected_by_isolated_replay": list(
                simulated_modes.get("strategies_unaffected_by_isolated_replay", []) or []
            ),
            "strategies_blocked_by_mixed_global_anchor": list(
                simulated_modes.get("strategies_blocked_by_mixed_global_anchor", []) or []
            ),
            "minimum_required_window_completeness": (
                "full_replay_window_plus_all_supported_checkpoint_outcomes"
            ),
            "lookback_window_policy": (
                f"{requested_windows}_windows_spanning_"
                f"{max(1, int(self.config.research_replay_days or 1))}_days"
            ),
            "warmup_buffer_policy": (
                "no_extra_selector_warmup_buffer_beyond_requested_window_start"
            ),
            "market_hours_policy": (
                "uses_persisted_bars_only_no_synthetic_market_hours_padding"
            ),
            "weekend_policy": "weekend_bars_allowed_if_present_no_weekend_backfill_padding",
            "asset_class_window_policy": (
                "bucket_isolated_by_asset_class_and_timeframe"
                if str(getattr(self.config, "replay_window_selection_mode", "global") or "global")
                == "asset_class_and_timeframe"
                else (
                    "bucket_isolated_by_asset_class"
                    if str(getattr(self.config, "replay_window_selection_mode", "global") or "global")
                    == "asset_class"
                    else "single_global_anchor_across_requested_symbol_universe"
                )
            ),
            "reason_latest_bars_not_used_for_replay": reason_latest_bars_not_used,
            "plain_english_replay_anchor_explanation": self._plain_english_replay_anchor_explanation(
                max_future_horizon=max_future_horizon,
                global_anchor_constraint=global_anchor_constraint,
                global_anchor_end_at=selection_anchor_end_at,
                freshness_lost_to_global_anchor=freshness_lost_to_global_anchor,
                simulated_modes=simulated_modes,
            ),
            "replay_windows_selected_from_latest_available_data": (
                replay_windows_selected_from_latest_available_data
            ),
        }

    def _latest_available_bar_per_asset_class(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        _ = plans
        latest_by_asset_class: dict[str, str] = {}
        for asset_class, symbols, sources in (
            ("equity", list(self.config.discovery_equity_symbols), ["alpaca_market_data"]),
            ("crypto", list(self.config.discovery_crypto_symbols), ["alpaca_crypto_data"]),
        ):
            latest_bar = self._latest_historical_bar_for_symbols(
                symbols=symbols,
                timeframes=self._diagnostic_timeframes(),
                sources=sources,
            )
            if isinstance(latest_bar, datetime):
                latest_by_asset_class[asset_class] = latest_bar.isoformat()
        return latest_by_asset_class

    def _latest_available_bar_per_symbol(self) -> dict[str, str]:
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if not callable(list_historical_bars):
            return {}
        latest_by_symbol: dict[str, datetime] = {}
        symbols = [*self.config.discovery_equity_symbols, *self.config.discovery_crypto_symbols]
        for timeframe in self._diagnostic_timeframes():
            rows = list_historical_bars(
                timeframe=timeframe,
                sources=["alpaca_market_data", "alpaca_crypto_data"],
                symbols=symbols,
            )
            for row in rows:
                symbol = str(row.get("symbol", "") or "").strip()
                timestamp = row.get("bar_timestamp")
                if not symbol or not isinstance(timestamp, datetime):
                    continue
                current = latest_by_symbol.get(symbol)
                if current is None or timestamp > current:
                    latest_by_symbol[symbol] = timestamp
        return {symbol: timestamp.isoformat() for symbol, timestamp in sorted(latest_by_symbol.items())}

    def _latest_replay_eligible_bar_per_timeframe(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for plan in plans:
            latest_valid = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if isinstance(latest_valid, datetime):
                result[plan.timeframe] = latest_valid.isoformat()
        return result

    def _latest_replay_eligible_bar_per_asset_class(
        self,
        *,
        plans: list[TimeframePlan],
        latest_by_symbol: dict[str, str],
    ) -> dict[str, str]:
        result: dict[str, datetime] = {}
        for plan in plans:
            asset_class = self._infer_asset_class_for_plan(
                plan=plan,
                latest_by_symbol=latest_by_symbol,
            )
            latest_valid = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if not asset_class or not isinstance(latest_valid, datetime):
                continue
            current = result.get(asset_class)
            if current is None or latest_valid > current:
                result[asset_class] = latest_valid
        return {key: value.isoformat() for key, value in sorted(result.items())}

    def _selected_replay_window_end_by_timeframe(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        return self._maximum_iso_value_by_key(rows=rows, key_field="timeframe")

    def _selected_replay_window_end_by_asset_class(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        return self._maximum_iso_value_by_key(rows=rows, key_field="asset_class")

    def _selected_replay_window_end_by_bucket(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        return self._maximum_iso_value_by_key(rows=rows, key_field="bucket")

    def _accepted_replay_window_count_by_timeframe(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        return self._count_rows_by_key(rows=rows, key_field="timeframe")

    def _accepted_replay_window_count_by_asset_class(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        return self._count_rows_by_key(rows=rows, key_field="asset_class")

    def _accepted_replay_window_count_by_bucket(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        return self._count_rows_by_key(rows=rows, key_field="bucket")

    def _selected_anchor_time_by_bucket(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        return self._maximum_iso_value_by_key(rows=rows, key_field="bucket")

    def _candidate_anchor_time_by_bucket(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for plan in plans:
            bucket = str(plan.bucket_id or "").strip()
            if not bucket:
                continue
            anchor = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if not isinstance(anchor, datetime):
                anchor = (plan.historical_coverage or {}).get(
                    "latest_available_historical_bar_at"
                )
            if isinstance(anchor, datetime):
                result[bucket] = anchor.isoformat()
        return dict(sorted(result.items()))

    def _rejected_bucket_anchor_time_by_bucket(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for plan in plans:
            if plan.status == "ready":
                continue
            bucket = str(plan.bucket_id or "").strip()
            if not bucket:
                continue
            anchor = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if not isinstance(anchor, datetime):
                anchor = (plan.historical_coverage or {}).get(
                    "latest_available_historical_bar_at"
                )
            if isinstance(anchor, datetime):
                result[bucket] = anchor.isoformat()
        return dict(sorted(result.items()))

    def _bucket_rejection_reasons(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for plan in plans:
            if plan.status == "ready":
                continue
            bucket = str(plan.bucket_id or "").strip()
            if not bucket:
                continue
            result[bucket] = str(plan.reason or "unknown")
        return dict(sorted(result.items()))

    def _maximum_iso_value_by_key(
        self,
        *,
        rows: list[dict[str, Any]],
        key_field: str,
    ) -> dict[str, str]:
        result: dict[str, datetime] = {}
        for row in rows:
            key = str(row.get(key_field, "") or "").strip()
            value = self._coerce_datetime(row.get("end_at"))
            if not key or not isinstance(value, datetime):
                continue
            current = result.get(key)
            if current is None or value > current:
                result[key] = value
        return {key: value.isoformat() for key, value in sorted(result.items())}

    def _count_rows_by_key(
        self,
        *,
        rows: list[dict[str, Any]],
        key_field: str,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get(key_field, "") or "").strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def _maximum_datetime_from_iso_map(self, value: dict[str, str]) -> datetime | None:
        datetimes = [self._coerce_datetime(item) for item in value.values()]
        valid = [item for item in datetimes if isinstance(item, datetime)]
        return max(valid) if valid else None

    def _freshness_gap(
        self,
        newer: datetime | None,
        older: datetime | None,
    ) -> timedelta | None:
        if not isinstance(newer, datetime) or not isinstance(older, datetime):
            return None
        if newer < older:
            return timedelta(0)
        return newer - older

    def _format_timedelta_or_unknown(self, value: timedelta | None) -> str:
        if not isinstance(value, timedelta):
            return "unknown"
        return self._format_timedelta(value)

    def _global_anchor_constraint(
        self,
        *,
        plans: list[TimeframePlan],
        selection_anchor_end_at: datetime,
        latest_by_symbol: dict[str, str],
    ) -> dict[str, str]:
        for plan in plans:
            latest_valid = (plan.historical_coverage or {}).get("latest_valid_replay_window_end")
            if not isinstance(latest_valid, datetime) or latest_valid != selection_anchor_end_at:
                continue
            asset_class = self._infer_asset_class_for_plan(
                plan=plan,
                latest_by_symbol=latest_by_symbol,
            )
            symbol = self._constraining_symbol_for_plan(plan=plan, latest_valid=latest_valid)
            return {
                "asset_class": asset_class,
                "timeframe": plan.timeframe,
                "symbol": symbol,
            }
        return {"asset_class": "", "timeframe": "", "symbol": ""}

    def _constraining_symbol_for_plan(
        self,
        *,
        plan: TimeframePlan,
        latest_valid: datetime,
    ) -> str:
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if not callable(list_historical_bars):
            return ""
        rows = list_historical_bars(
            timeframe=plan.timeframe,
            sources=["alpaca_market_data", "alpaca_crypto_data"],
            symbols=[*self.config.discovery_equity_symbols, *self.config.discovery_crypto_symbols],
        )
        horizon = (plan.historical_coverage or {}).get("max_required_future_horizon")
        if not isinstance(horizon, timedelta):
            return ""
        target_latest = latest_valid + horizon
        matching_symbols = sorted(
            {
                str(row.get("symbol", "") or "").strip()
                for row in rows
                if isinstance(row.get("bar_timestamp"), datetime)
                and row.get("bar_timestamp") == target_latest
                and str(row.get("symbol", "") or "").strip()
            }
        )
        return matching_symbols[0] if matching_symbols else ""

    def _simulated_replay_selection_modes(
        self,
        *,
        plans: list[TimeframePlan],
        latest_by_symbol: dict[str, str],
        global_anchor_end_at: datetime,
    ) -> dict[str, Any]:
        asset_class_anchor_time = self._simulated_anchor_time_by_asset_class()
        asset_class_and_timeframe_anchor_time = (
            self._simulated_anchor_time_by_asset_class_and_timeframe(plans=plans)
        )
        freshness_gain_by_asset_class = self._freshness_gain_map(
            anchors=asset_class_anchor_time,
            global_anchor_end_at=global_anchor_end_at,
        )
        freshness_gain_by_asset_class_and_timeframe = self._freshness_gain_map(
            anchors=asset_class_and_timeframe_anchor_time,
            global_anchor_end_at=global_anchor_end_at,
        )
        strategy_sets = self._strategy_isolated_replay_sets(
            latest_by_symbol=latest_by_symbol,
            freshness_gain_by_asset_class=freshness_gain_by_asset_class,
            freshness_gain_by_asset_class_and_timeframe=freshness_gain_by_asset_class_and_timeframe,
        )
        alternative_modes_available = bool(
            len(asset_class_anchor_time) > 1
            or len(asset_class_and_timeframe_anchor_time) > 1
        )
        return {
            "alternative_modes_available": alternative_modes_available,
            "asset_class_anchor_time": asset_class_anchor_time,
            "asset_class_and_timeframe_anchor_time": asset_class_and_timeframe_anchor_time,
            "freshness_gain_by_asset_class": freshness_gain_by_asset_class,
            "freshness_gain_by_asset_class_and_timeframe": (
                freshness_gain_by_asset_class_and_timeframe
            ),
            **strategy_sets,
        }

    def _simulated_anchor_time_by_asset_class(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for asset_class in ("crypto", "equity"):
            coverage = self._coverage_for_asset_class_timeframe(
                asset_class=asset_class,
                timeframe=self.config.research_replay_timeframe,
            )
            latest_valid = coverage.get("latest_valid_replay_window_end")
            if isinstance(latest_valid, datetime):
                result[asset_class] = latest_valid.isoformat()
        return result

    def _simulated_anchor_time_by_asset_class_and_timeframe(
        self,
        *,
        plans: list[TimeframePlan],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        timeframes = self._ordered_unique([plan.timeframe for plan in plans])
        for timeframe in timeframes:
            for asset_class in ("crypto", "equity"):
                coverage = self._coverage_for_asset_class_timeframe(
                    asset_class=asset_class,
                    timeframe=timeframe,
                )
                latest_valid = coverage.get("latest_valid_replay_window_end")
                if isinstance(latest_valid, datetime):
                    result[f"{asset_class}/{timeframe}"] = latest_valid.isoformat()
        return result

    def _coverage_for_asset_class_timeframe(
        self,
        *,
        asset_class: str,
        timeframe: str,
    ) -> dict[str, Any]:
        normalized_asset_class = str(asset_class or "").strip().lower()
        if normalized_asset_class == "crypto":
            symbols = list(self.config.discovery_crypto_symbols)
            sources = ["alpaca_crypto_data"]
        elif normalized_asset_class == "equity":
            symbols = list(self.config.discovery_equity_symbols)
            sources = ["alpaca_market_data"]
        else:
            symbols = [
                *self.config.discovery_equity_symbols,
                *self.config.discovery_crypto_symbols,
            ]
            sources = ["alpaca_market_data", "alpaca_crypto_data"]
        return self._timeframe_historical_coverage_for_symbols(
            timeframe=timeframe,
            symbols=symbols,
            sources=sources,
        )

    def _timeframe_historical_coverage_for_symbols(
        self,
        *,
        timeframe: str,
        symbols: list[str],
        sources: list[str],
    ) -> dict[str, Any]:
        supported_windows = self._supported_checkpoint_windows_for_timeframe(timeframe=timeframe)
        max_future_horizon = timedelta(
            minutes=max(0, self._max_checkpoint_window_minutes_for_timeframe(timeframe=timeframe))
        )
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if not callable(list_historical_bars):
            return {
                "supported_checkpoint_windows": list(supported_windows),
                "max_required_future_horizon": max_future_horizon,
                "earliest_available_historical_bar_at": None,
                "latest_available_historical_bar_at": None,
                "latest_valid_replay_window_end": None,
                "window_anchor_mode": "latest_historical_bar_minus_future_horizon",
                "has_historical_bars": False,
                "fallback_mode": "no_usage_ledger_historical_bar_listing",
            }
        rows = list_historical_bars(
            timeframe=timeframe,
            sources=sources,
            symbols=symbols,
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

    def _freshness_gain_map(
        self,
        *,
        anchors: dict[str, str],
        global_anchor_end_at: datetime,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in sorted(anchors.items()):
            anchor = self._coerce_datetime(value)
            result[key] = self._format_timedelta_or_unknown(
                self._freshness_gap(anchor, global_anchor_end_at)
            )
        return result

    def _strategy_isolated_replay_sets(
        self,
        *,
        latest_by_symbol: dict[str, str],
        freshness_gain_by_asset_class: dict[str, str],
        freshness_gain_by_asset_class_and_timeframe: dict[str, str],
    ) -> dict[str, list[str]]:
        helped_asset_classes = {
            key for key, value in freshness_gain_by_asset_class.items() if value not in {"0s", "unknown"}
        }
        helped_asset_timeframes = {
            key
            for key, value in freshness_gain_by_asset_class_and_timeframe.items()
            if value not in {"0s", "unknown"}
        }
        blocked_by_mixed = bool(helped_asset_timeframes) and bool(self.config.discovery_equity_symbols)
        helped: list[str] = []
        unaffected: list[str] = []
        blocked: list[str] = []
        for profile in self._research_profiles():
            strategy_key = f"{profile.strategy_id}/{profile.profile_id}"
            profile_asset_classes = {str(item).lower() for item in profile.asset_classes}
            gains_asset = bool(profile_asset_classes.intersection(helped_asset_classes))
            gains_asset_timeframe = any(
                key.split("/", 1)[0] in profile_asset_classes for key in helped_asset_timeframes
            )
            if gains_asset or gains_asset_timeframe:
                helped.append(strategy_key)
                if blocked_by_mixed:
                    blocked.append(strategy_key)
            else:
                unaffected.append(strategy_key)
        _ = latest_by_symbol
        return {
            "strategies_helped_by_isolated_replay": sorted(self._ordered_unique(helped)),
            "strategies_unaffected_by_isolated_replay": sorted(self._ordered_unique(unaffected)),
            "strategies_blocked_by_mixed_global_anchor": sorted(self._ordered_unique(blocked)),
        }

    def _plain_english_replay_anchor_explanation(
        self,
        *,
        max_future_horizon: timedelta,
        global_anchor_constraint: dict[str, str],
        global_anchor_end_at: datetime,
        freshness_lost_to_global_anchor: str,
        simulated_modes: dict[str, Any] | None = None,
    ) -> str:
        selection_mode = str(
            getattr(self.config, "replay_window_selection_mode", "global") or "global"
        )
        asset_class = global_anchor_constraint.get("asset_class") or "unknown_asset_class"
        timeframe = global_anchor_constraint.get("timeframe") or "unknown_timeframe"
        symbol = global_anchor_constraint.get("symbol") or "unknown_symbol"
        if selection_mode == "asset_class_and_timeframe":
            return (
                "Newest raw bars are not immediately replay-eligible because replay needs "
                f"{self._format_timedelta(max_future_horizon)} of future outcome data. "
                "crypto/15Min is using its own replay anchor and is no longer held back by "
                "crypto/1Hour or mixed/1Hour coverage."
            )
        message = (
            "Newest raw bars are not immediately replay-eligible because replay needs "
            f"{self._format_timedelta(max_future_horizon)} of future outcome data. "
            "The current global selector is additionally constrained by "
            f"{asset_class}/{timeframe}/{symbol}, so fresher crypto 15Min data is being held back "
            f"by older coverage. Additional freshness lost to the global anchor: {freshness_lost_to_global_anchor}."
        )
        simulated = dict(simulated_modes or {})
        simulated_asset_time = dict(
            simulated.get("asset_class_and_timeframe_anchor_time", {}) or {}
        )
        crypto_15min = simulated_asset_time.get("crypto/15Min", "")
        gain = (
            dict(simulated.get("freshness_gain_by_asset_class_and_timeframe", {}) or {}).get(
                "crypto/15Min", ""
            )
        )
        if crypto_15min and freshness_lost_to_global_anchor not in {"0s", "unknown"}:
            message += (
                " In asset_class_and_timeframe mode, crypto 15Min could replay up to "
                f"{crypto_15min} while 1Hour/mixed remains anchored at "
                f"{global_anchor_end_at.isoformat()}."
            )
        if crypto_15min and gain not in {"", "0s", "unknown"}:
            message += f" Potential freshness gain for crypto 15Min: {gain}."
        return message

    def _diagnostic_timeframes(self) -> list[str]:
        return self._ordered_unique(
            [
                self.config.research_replay_timeframe,
                getattr(
                    self.config,
                    "historical_replay_default_timeframe",
                    self.config.research_replay_timeframe,
                ),
                "15Min",
                "1Hour",
                "1Day",
            ]
        )

    def _infer_asset_class_for_plan(
        self,
        *,
        plan: TimeframePlan,
        latest_by_symbol: dict[str, str] | None,
    ) -> str:
        if str(plan.asset_class or "").strip():
            return str(plan.asset_class)
        if self.config.discovery_equity_symbols and self.config.discovery_crypto_symbols:
            if latest_by_symbol is None:
                return "mixed"
            latest_bar = (plan.historical_coverage or {}).get("latest_available_historical_bar_at")
            if not isinstance(latest_bar, datetime):
                return "mixed"
            latest_text = latest_bar.isoformat()
            crypto_matches = any(
                latest_by_symbol.get(symbol) == latest_text
                for symbol in self.config.discovery_crypto_symbols
            )
            equity_matches = any(
                latest_by_symbol.get(symbol) == latest_text
                for symbol in self.config.discovery_equity_symbols
            )
            if crypto_matches and equity_matches:
                return "mixed"
            if crypto_matches:
                return "crypto"
            if equity_matches:
                return "equity"
            return "mixed"
        if self.config.discovery_crypto_symbols:
            return "crypto"
        if self.config.discovery_equity_symbols:
            return "equity"
        return "unknown"

    def _explain_latest_bar_gap(
        self,
        *,
        plans: list[TimeframePlan],
        latest_after: datetime,
        selection_anchor_end_at: datetime,
        latest_by_symbol: dict[str, str],
    ) -> str:
        if selection_anchor_end_at >= latest_after:
            return "latest_available_bar_timestamp_used_without_gap"
        latest_by_asset_class = self._latest_available_bar_per_asset_class(plans=plans)
        if len(set(latest_by_asset_class.values())) > 1:
            return (
                "latest_available_bar_not_used_because_selector_uses_global_oldest_valid_anchor_across_asset_classes"
            )
        return (
            "latest_available_bar_not_used_because_future_checkpoint_completeness_requires_older_anchor"
        )

    def _join_reasons(self, reasons: list[str]) -> str:
        return "|".join(
            reason
            for reason in self._ordered_unique(reasons)
            if str(reason).strip()
        )

    def _default_pre_replay_refresh_state(self, *, as_of: datetime) -> dict[str, Any]:
        return {
            "pre_replay_refresh_enabled": (
                "yes"
                if bool(
                    getattr(self.config, "pre_replay_historical_refresh_enabled", False)
                )
                else "no"
            ),
            "pre_replay_refresh_dry_run": (
                "yes"
                if bool(getattr(self.config, "pre_replay_historical_refresh_dry_run", True))
                else "no"
            ),
            "pre_replay_refresh_ran": "no",
            "pre_replay_refresh_mode": "disabled",
            "pre_replay_refresh_asset_classes": [],
            "pre_replay_refresh_symbols": {
                "equity": list(self.config.discovery_equity_symbols),
                "crypto": list(self.config.discovery_crypto_symbols),
            },
            "pre_replay_refresh_safety_guard": (
                "historical_backfill_only_no_orders_no_auto_approvals"
            ),
            "latest_bar_before_refresh": "",
            "latest_bar_after_refresh": "",
            "bars_inserted_by_refresh": 0,
            "bars_updated_by_refresh": 0,
            "refresh_attempted_symbols": {"equity": [], "crypto": []},
            "refresh_success_symbols": {"equity": [], "crypto": []},
            "refresh_failed_symbols": {"equity": [], "crypto": []},
            "refresh_skipped_symbols": {"equity": [], "crypto": []},
            "refresh_skip_reasons": {"equity": [], "crypto": []},
            "provider_error_count": 0,
            "provider_errors": [],
            "refresh_error_count": 0,
            "refresh_errors": [],
            "refresh_duration_ms": 0,
            "refresh_completed_at": as_of.isoformat(),
        }

    def _run_pre_replay_historical_refresh(self, *, as_of: datetime) -> dict[str, Any]:
        state = self._default_pre_replay_refresh_state(as_of=as_of)
        state["latest_bar_before_refresh"] = self._iso_or_blank(
            self._latest_historical_bar_for_symbols(
                symbols=[
                    *self.config.discovery_equity_symbols,
                    *self.config.discovery_crypto_symbols,
                ]
            )
        )
        enabled = bool(getattr(self.config, "pre_replay_historical_refresh_enabled", False))
        dry_run = bool(getattr(self.config, "pre_replay_historical_refresh_dry_run", True))
        state["pre_replay_refresh_mode"] = "dry_run" if enabled and dry_run else (
            "write" if enabled else "disabled"
        )
        asset_classes = []
        if self.config.discovery_equity_symbols:
            asset_classes.append("equity")
        if self.config.discovery_crypto_symbols:
            asset_classes.append("crypto")
        state["pre_replay_refresh_asset_classes"] = asset_classes
        if not enabled:
            state["latest_bar_after_refresh"] = state["latest_bar_before_refresh"]
            return state

        started_perf = perf_counter()
        state["pre_replay_refresh_ran"] = "yes"
        try:
            # Safety boundary: pre-replay refresh is limited to the historical
            # backfill/storage path. It must not route broker orders, enable
            # paper/live, or mutate promotion thresholds.
            report = HistoricalBackfillRunner(
                config=self.config,
                usage_ledger=self.usage_ledger,
            ).run(
                days=self.config.research_replay_days,
                timeframe=self.config.research_replay_timeframe,
                equity_symbols=self.config.discovery_equity_symbols,
                crypto_symbols=self.config.discovery_crypto_symbols,
                dry_run=dry_run,
            )
            snapshot = dict(report.state_snapshot or {})
            equity = dict(snapshot.get("historical_equity_backfill", {}) or {})
            crypto = dict(snapshot.get("historical_crypto_backfill", {}) or {})
            state["refresh_attempted_symbols"] = {
                "equity": list(equity.get("attempted_symbols", []) or []),
                "crypto": list(crypto.get("attempted_symbols", []) or []),
            }
            state["refresh_success_symbols"] = {
                "equity": list(equity.get("success_symbols", []) or []),
                "crypto": list(crypto.get("success_symbols", []) or []),
            }
            state["refresh_failed_symbols"] = {
                "equity": list(equity.get("failed_symbols", []) or []),
                "crypto": list(crypto.get("failed_symbols", []) or []),
            }
            state["refresh_skipped_symbols"] = {
                "equity": list(equity.get("skipped_symbols", []) or []),
                "crypto": list(crypto.get("skipped_symbols", []) or []),
            }
            state["refresh_skip_reasons"] = {
                "equity": list(equity.get("skip_reasons", []) or []),
                "crypto": list(crypto.get("skip_reasons", []) or []),
            }
            state["provider_error_count"] = int(
                equity.get("provider_error_count", 0) or 0
            ) + int(crypto.get("provider_error_count", 0) or 0)
            state["provider_errors"] = [
                *list(equity.get("provider_errors", []) or []),
                *list(crypto.get("provider_errors", []) or []),
            ]
            if not dry_run:
                state["bars_inserted_by_refresh"] = int(
                    equity.get("bars_inserted", 0) or 0
                ) + int(crypto.get("bars_inserted", 0) or 0)
                state["bars_updated_by_refresh"] = int(
                    equity.get("bars_updated", 0) or 0
                ) + int(crypto.get("bars_updated", 0) or 0)
            if getattr(report, "persistence_error", ""):
                state["refresh_errors"] = [str(report.persistence_error)]
                state["refresh_error_count"] = 1
        except Exception as exc:
            state["refresh_errors"] = [f"{type(exc).__name__}: {exc}"]
            state["refresh_error_count"] = 1
        finally:
            state["refresh_duration_ms"] = int((perf_counter() - started_perf) * 1000)
            state["latest_bar_after_refresh"] = self._iso_or_blank(
                self._latest_historical_bar_for_symbols(
                    symbols=[
                        *self.config.discovery_equity_symbols,
                        *self.config.discovery_crypto_symbols,
                    ]
                )
            ) or state["latest_bar_before_refresh"]
        return state

    def _latest_historical_bar_for_symbols(
        self,
        *,
        symbols: list[str],
        timeframes: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> datetime | None:
        latest_timestamp: datetime | None = None
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if not callable(list_historical_bars):
            return None
        for timeframe in (timeframes or self._diagnostic_timeframes()):
            rows = list_historical_bars(
                timeframe=timeframe,
                sources=sources or ["alpaca_market_data", "alpaca_crypto_data"],
                symbols=symbols,
            )
            timestamps = [
                row.get("bar_timestamp")
                for row in rows
                if isinstance(row.get("bar_timestamp"), datetime)
            ]
            if timestamps:
                candidate = max(timestamps)
                if latest_timestamp is None or candidate > latest_timestamp:
                    latest_timestamp = candidate
        return latest_timestamp

    def _historical_asset_class_freshness(
        self,
        *,
        asset_class: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        expected_sources = {
            "equity": ["alpaca_market_data"],
            "crypto": ["alpaca_crypto_data"],
        }
        expected_symbols = {
            "equity": list(self.config.discovery_equity_symbols),
            "crypto": list(self.config.discovery_crypto_symbols),
        }
        threshold = max(
            timedelta(minutes=30),
            self._timeframe_delta(self.config.research_replay_timeframe) * 2,
        )
        latest_timestamp: datetime | None = None
        timeframes = self._ordered_unique(
            [
                self.config.research_replay_timeframe,
                getattr(
                    self.config,
                    "historical_replay_default_timeframe",
                    self.config.research_replay_timeframe,
                ),
            ]
        )
        list_historical_bars = getattr(self.usage_ledger, "list_historical_bars", None)
        if callable(list_historical_bars):
            for timeframe in timeframes:
                rows = list_historical_bars(
                    timeframe=timeframe,
                    sources=expected_sources.get(asset_class, []),
                    symbols=expected_symbols.get(asset_class, []),
                )
                timestamps = [
                    row.get("bar_timestamp")
                    for row in rows
                    if isinstance(row.get("bar_timestamp"), datetime)
                ]
                if timestamps:
                    candidate = max(timestamps)
                    if latest_timestamp is None or candidate > latest_timestamp:
                        latest_timestamp = candidate
        if latest_timestamp is None:
            return {
                "latest_available_historical_bar_at": "",
                "age": "unknown",
                "fresh": "no",
                "threshold_used": self._format_timedelta(threshold),
                "reason": "no_historical_bars_for_asset_class",
            }
        age = as_of - latest_timestamp
        return {
            "latest_available_historical_bar_at": latest_timestamp.isoformat(),
            "age": self._format_timedelta(age),
            "fresh": "yes" if age <= threshold else "no",
            "threshold_used": self._format_timedelta(threshold),
            "reason": "ok" if age <= threshold else "historical_bars_older_than_replay_freshness_threshold",
        }

    def _replay_setting_snapshot(self) -> dict[str, Any]:
        shadow_checkpoint_windows = tuple(
            getattr(self.config, "shadow_checkpoint_windows", ("15m", "1h", "1d", "7d"))
            or ("15m", "1h", "1d", "7d")
        )
        return {
            "research_replay_timeframe": {
                "value": str(self.config.research_replay_timeframe),
                "env_var": "RESEARCH_REPLAY_TIMEFRAME",
                "raw_value": str(os.getenv("RESEARCH_REPLAY_TIMEFRAME", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("RESEARCH_REPLAY_TIMEFRAME", "") or "").strip()
                    else "default"
                ),
            },
            "research_replay_days": {
                "value": int(self.config.research_replay_days),
                "env_var": "RESEARCH_REPLAY_DAYS",
                "raw_value": str(os.getenv("RESEARCH_REPLAY_DAYS", "") or ""),
                "source": "env" if str(os.getenv("RESEARCH_REPLAY_DAYS", "") or "").strip() else "default",
            },
            "research_max_replay_timestamps": {
                "value": int(self.config.research_max_replay_timestamps),
                "env_var": "RESEARCH_MAX_REPLAY_TIMESTAMPS",
                "raw_value": str(os.getenv("RESEARCH_MAX_REPLAY_TIMESTAMPS", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("RESEARCH_MAX_REPLAY_TIMESTAMPS", "") or "").strip()
                    else "default"
                ),
            },
            "research_min_windows": {
                "value": int(self.config.research_min_windows),
                "env_var": "RESEARCH_MIN_WINDOWS",
                "raw_value": str(os.getenv("RESEARCH_MIN_WINDOWS", "") or ""),
                "source": "env" if str(os.getenv("RESEARCH_MIN_WINDOWS", "") or "").strip() else "default",
            },
            "shadow_checkpoint_windows": {
                "value": list(shadow_checkpoint_windows),
                "env_var": "SHADOW_CHECKPOINT_WINDOWS",
                "raw_value": str(os.getenv("SHADOW_CHECKPOINT_WINDOWS", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("SHADOW_CHECKPOINT_WINDOWS", "") or "").strip()
                    else "default"
                ),
            },
            "discovery_equity_symbols": {
                "value": list(self.config.discovery_equity_symbols),
                "env_var": "DISCOVERY_EQUITY_SYMBOLS",
                "raw_value": str(os.getenv("DISCOVERY_EQUITY_SYMBOLS", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("DISCOVERY_EQUITY_SYMBOLS", "") or "").strip()
                    else "default"
                ),
            },
            "discovery_crypto_symbols": {
                "value": list(self.config.discovery_crypto_symbols),
                "env_var": "DISCOVERY_CRYPTO_SYMBOLS",
                "raw_value": str(os.getenv("DISCOVERY_CRYPTO_SYMBOLS", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("DISCOVERY_CRYPTO_SYMBOLS", "") or "").strip()
                    else "default"
                ),
            },
            "research_cycle_env_path": {
                "value": str(getattr(self.config, "research_cycle_env_path", "") or ""),
                "env_var": "RESEARCH_CYCLE_ENABLED",
                "raw_value": str(getattr(self.config, "research_cycle_enabled_env_file_value", "") or ""),
                "source": str(getattr(self.config, "research_cycle_enabled_value_source", "") or "runtime_config"),
            },
            "rolling_replay_cursor_enabled": {
                "value": bool(getattr(self.config, "rolling_replay_cursor_enabled", False)),
                "env_var": "ROLLING_REPLAY_CURSOR_ENABLED",
                "raw_value": str(os.getenv("ROLLING_REPLAY_CURSOR_ENABLED", "") or ""),
                "source": (
                    "env"
                    if str(os.getenv("ROLLING_REPLAY_CURSOR_ENABLED", "") or "").strip()
                    else "default"
                ),
            },
        }

    def _research_cycle_singleton_dir(self) -> Path:
        configured = str(getattr(self.config, "research_cycle_singleton_dir", "") or "").strip()
        if configured:
            return Path(configured)
        return Path("/tmp/ghostfrog-centaur-research-cycle.lock")

    def _heartbeat_service_singleton_dir(self) -> Path:
        return Path("/tmp/ghostfrog-centaur-heartbeat-service.lock")

    def _acquire_research_cycle_singleton(self) -> dict[str, Any]:
        lock_dir = self._research_cycle_singleton_dir()
        pid_file = lock_dir / "pid"
        state: dict[str, Any] = {
            "lock_dir": lock_dir,
            "pid_file": pid_file,
            "owned": False,
        }
        existing_heartbeat = "yes" if self._lock_dir_has_running_pid(self._heartbeat_service_singleton_dir()) else "no"
        existing_research_cycle = "no"
        try:
            lock_dir.mkdir()
        except FileExistsError:
            existing_lock = self._read_lock_metadata(pid_file)
            existing_pid = str(existing_lock.get("pid", "") or "")
            # Reclaim locks left behind by earlier cycles in this same long-lived
            # process (for example the unittest runner) while still failing closed
            # if another OS process currently owns the research cycle singleton.
            if (
                existing_pid
                and existing_pid != str(os.getpid())
                and self._pid_is_running(existing_pid)
                and self._lock_matches_running_process(existing_lock)
            ):
                existing_research_cycle = "yes"
                os.environ["CENTAUR_EXISTING_HEARTBEAT_PROCESS_DETECTED"] = existing_heartbeat
                os.environ["CENTAUR_EXISTING_RESEARCH_CYCLE_PROCESS_DETECTED"] = existing_research_cycle
                os.environ["CENTAUR_CURRENT_PROCESS_IS_FORCED_ONE_SHOT"] = (
                    "yes" if self.cycle_origin == "forced_one_shot" else "no"
                )
                raise ResearchCycleAlreadyRunningError(
                    "Another research cycle is already running; skipping overlapping forced one-shot."
                )
            pid_file.unlink(missing_ok=True)
            lock_dir.rmdir()
            lock_dir.mkdir()
        self._write_lock_metadata(pid_file)
        state["owned"] = True
        os.environ["CENTAUR_COMMAND_SOURCE"] = self.command_source
        os.environ["CENTAUR_EXISTING_HEARTBEAT_PROCESS_DETECTED"] = existing_heartbeat
        os.environ["CENTAUR_EXISTING_RESEARCH_CYCLE_PROCESS_DETECTED"] = existing_research_cycle
        os.environ["CENTAUR_CURRENT_PROCESS_IS_FORCED_ONE_SHOT"] = (
            "yes" if self.cycle_origin == "forced_one_shot" else "no"
        )
        return state

    def _release_research_cycle_singleton(self, state: dict[str, Any]) -> None:
        if not state.get("owned"):
            return
        pid_file = state.get("pid_file")
        lock_dir = state.get("lock_dir")
        if isinstance(pid_file, Path):
            pid_file.unlink(missing_ok=True)
        if isinstance(lock_dir, Path):
            try:
                lock_dir.rmdir()
            except OSError:
                pass

    def _lock_dir_has_running_pid(self, lock_dir: Path) -> bool:
        pid_file = lock_dir / "pid"
        pid_text = str(self._read_lock_metadata(pid_file).get("pid", "") or "")
        return bool(pid_text) and self._pid_is_running(pid_text)

    def _pid_is_running(self, pid_text: str) -> bool:
        try:
            os.kill(int(pid_text), 0)
        except (OSError, ValueError):
            return False
        return True

    def _write_lock_metadata(self, pid_file: Path) -> None:
        payload = {
            "pid": os.getpid(),
            "process_started_at": self._process_started_at_signature(os.getpid()),
        }
        pid_file.write_text(json.dumps(payload), encoding="utf-8")

    def _read_lock_metadata(self, pid_file: Path) -> dict[str, str]:
        if not pid_file.exists():
            return {}
        raw = pid_file.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {"pid": raw}
        if not isinstance(decoded, dict):
            return {}
        return {
            "pid": str(decoded.get("pid", "") or ""),
            "process_started_at": str(decoded.get("process_started_at", "") or ""),
        }

    def _lock_matches_running_process(self, lock_metadata: dict[str, str]) -> bool:
        pid_text = str(lock_metadata.get("pid", "") or "")
        if not pid_text:
            return False
        try:
            pid = int(pid_text)
        except ValueError:
            return False
        actual_started_at = self._process_started_at_signature(pid)
        locked_started_at = str(lock_metadata.get("process_started_at", "") or "")
        if locked_started_at:
            return bool(actual_started_at) and actual_started_at == locked_started_at
        return pid != os.getpid()

    def _process_started_at_signature(self, pid: int) -> str:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True,
                check=False,
                text=True,
            )
        except (OSError, PermissionError):
            return f"pid:{int(pid)}:unverified"
        if result.returncode != 0:
            return f"pid:{int(pid)}:unverified"
        return result.stdout.strip() or f"pid:{int(pid)}:unverified"

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
        if recommendation == "paper_candidate":
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
        mode = str(getattr(self.config, "replay_window_selection_mode", "global") or "global")
        if mode == "asset_class_and_timeframe":
            return self._build_asset_class_and_timeframe_plans(
                inventory=inventory,
                end_at=end_at,
            )
        if mode == "asset_class":
            return self._build_asset_class_plans(
                inventory=inventory,
                end_at=end_at,
            )
        return self._build_global_timeframe_plans(
            inventory=inventory,
            end_at=end_at,
        )

    def _build_global_timeframe_plans(
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
                    bucket_id=f"global/{timeframe}",
                    asset_class=self._infer_asset_class_for_plan(
                        plan=TimeframePlan(
                            timeframe=timeframe,
                            status="ready",
                            reason="ok",
                            available_symbols=available_symbols,
                            available_timeframes=available_timeframes,
                            historical_coverage=coverage,
                        ),
                        latest_by_symbol=self._latest_available_bar_per_symbol(),
                    ),
                    equity_symbols=tuple(self.config.discovery_equity_symbols),
                    crypto_symbols=tuple(self.config.discovery_crypto_symbols),
                    windows=windows,
                    readiness=readiness,
                    historical_coverage=coverage,
                )
            )
        return plans

    def _build_asset_class_plans(
        self,
        *,
        inventory: dict[str, Any],
        end_at: datetime,
    ) -> list[TimeframePlan]:
        return self._build_bucketed_plans(
            inventory=inventory,
            end_at=end_at,
            bucket_mode="asset_class",
        )

    def _build_asset_class_and_timeframe_plans(
        self,
        *,
        inventory: dict[str, Any],
        end_at: datetime,
    ) -> list[TimeframePlan]:
        return self._build_bucketed_plans(
            inventory=inventory,
            end_at=end_at,
            bucket_mode="asset_class_and_timeframe",
        )

    def _build_bucketed_plans(
        self,
        *,
        inventory: dict[str, Any],
        end_at: datetime,
        bucket_mode: str,
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
            if bucket_mode == "asset_class":
                bucket_specs = self._asset_class_bucket_specs(timeframe=timeframe)
            else:
                bucket_specs = self._asset_class_and_timeframe_bucket_specs(timeframe=timeframe)
            for bucket_id, asset_class, equity_symbols, crypto_symbols in bucket_specs:
                plans.append(
                    self._build_bucket_plan(
                        timeframe=timeframe,
                        bucket_id=bucket_id,
                        asset_class=asset_class,
                        equity_symbols=equity_symbols,
                        crypto_symbols=crypto_symbols,
                        available_symbols=available_symbols,
                        available_timeframes=available_timeframes,
                        end_at=end_at,
                    )
                )
        return plans

    def _asset_class_bucket_specs(
        self,
        *,
        timeframe: str,
    ) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
        _ = timeframe
        buckets: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
        if self.config.discovery_crypto_symbols:
            buckets.append(
                (
                    "crypto",
                    "crypto",
                    tuple(),
                    tuple(self.config.discovery_crypto_symbols),
                )
            )
        if self.config.discovery_equity_symbols:
            buckets.append(
                (
                    "equity",
                    "equity",
                    tuple(self.config.discovery_equity_symbols),
                    tuple(),
                )
            )
        return buckets

    def _asset_class_and_timeframe_bucket_specs(
        self,
        *,
        timeframe: str,
    ) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
        buckets: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
        if self.config.discovery_crypto_symbols:
            buckets.append(
                (
                    f"crypto/{timeframe}",
                    "crypto",
                    tuple(),
                    tuple(self.config.discovery_crypto_symbols),
                )
            )
        if self.config.discovery_equity_symbols:
            buckets.append(
                (
                    f"equity/{timeframe}",
                    "equity",
                    tuple(self.config.discovery_equity_symbols),
                    tuple(),
                )
            )
        return buckets

    def _build_bucket_plan(
        self,
        *,
        timeframe: str,
        bucket_id: str,
        asset_class: str,
        equity_symbols: tuple[str, ...],
        crypto_symbols: tuple[str, ...],
        available_symbols: list[str],
        available_timeframes: list[str],
        end_at: datetime,
    ) -> TimeframePlan:
        bucket_symbols = [*equity_symbols, *crypto_symbols]
        if not bucket_symbols:
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason="bucket_has_no_configured_symbols",
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
            )
        coverage = self._timeframe_historical_coverage_for_symbols(
            timeframe=timeframe,
            symbols=bucket_symbols,
            sources=self._sources_for_asset_class(asset_class=asset_class),
        )
        readiness_report = self.bars_report.build_report(
            days=self.config.research_replay_days,
            timeframe=timeframe,
            equity_symbols=equity_symbols,
            crypto_symbols=crypto_symbols,
            end_at=self._plan_anchor_end_at(
                plan=TimeframePlan(
                    timeframe=timeframe,
                    status="pending",
                    reason="pending",
                    available_symbols=available_symbols,
                    available_timeframes=available_timeframes,
                    bucket_id=bucket_id,
                    asset_class=asset_class,
                    equity_symbols=equity_symbols,
                    crypto_symbols=crypto_symbols,
                    historical_coverage=coverage,
                ),
                fallback_end_at=end_at,
            ),
        )
        readiness = dict(readiness_report.get("replay_readiness", {}) or {})
        if timeframe not in available_timeframes:
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason="timeframe_not_present_in_historical_store",
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                readiness=readiness,
                historical_coverage=coverage,
            )
        if not bool(coverage.get("has_historical_bars")):
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason="no_matching_historical_rows_for_requested_symbols",
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                readiness=readiness,
                historical_coverage=coverage,
            )
        latest_valid_end = coverage.get("latest_valid_replay_window_end")
        if not isinstance(latest_valid_end, datetime):
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason="not_enough_future_data_for_checkpoint_windows",
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                readiness=readiness,
                historical_coverage=coverage,
            )
        if not bool(readiness.get("can_replay_requested_range")):
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason=str(readiness.get("reason", "cannot_replay")),
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                readiness=readiness,
                historical_coverage=coverage,
            )
        windows = tuple(
            self._select_windows(
                end_at=latest_valid_end,
                earliest_start_at=coverage.get("earliest_available_historical_bar_at"),
                eligible_timestamps=int(readiness.get("eligible_timestamps", 0) or 0),
            )
        )
        if not windows:
            return TimeframePlan(
                timeframe=timeframe,
                status="skipped",
                reason="no_safe_replay_windows",
                available_symbols=available_symbols,
                available_timeframes=available_timeframes,
                bucket_id=bucket_id,
                asset_class=asset_class,
                equity_symbols=equity_symbols,
                crypto_symbols=crypto_symbols,
                readiness=readiness,
                historical_coverage=coverage,
            )
        return TimeframePlan(
            timeframe=timeframe,
            status="ready",
            reason="ok",
            available_symbols=available_symbols,
            available_timeframes=available_timeframes,
            bucket_id=bucket_id,
            asset_class=asset_class,
            equity_symbols=equity_symbols,
            crypto_symbols=crypto_symbols,
            windows=windows,
            readiness=readiness,
            historical_coverage=coverage,
        )

    def _sources_for_asset_class(self, *, asset_class: str) -> list[str]:
        normalized = str(asset_class or "").strip().lower()
        if normalized == "crypto":
            return ["alpaca_crypto_data"]
        if normalized == "equity":
            return ["alpaca_market_data"]
        return ["alpaca_market_data", "alpaca_crypto_data"]

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

    def _diagnostic_selection_anchor_end_at(
        self,
        *,
        plans: list[TimeframePlan],
        fallback_end_at: datetime,
    ) -> datetime:
        latest_valid_values = [
            coverage.get("latest_valid_replay_window_end")
            for coverage in (plan.historical_coverage or {} for plan in plans)
            if isinstance(coverage.get("latest_valid_replay_window_end"), datetime)
        ]
        if latest_valid_values:
            return min(latest_valid_values)
        latest_available_values = [
            coverage.get("latest_available_historical_bar_at")
            for coverage in (plan.historical_coverage or {} for plan in plans)
            if isinstance(coverage.get("latest_available_historical_bar_at"), datetime)
        ]
        if latest_available_values:
            return min(latest_available_values)
        return fallback_end_at

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

    def _serialize_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(readiness)
        for key in ("requested_start_at", "requested_end_at", "data_range_end"):
            serialized[key] = self._iso_or_blank(serialized.get(key))
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

    def _coerce_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_timedelta(self, value: timedelta) -> str:
        total_seconds = int(max(0.0, value.total_seconds()))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        if minutes or hours or days:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return "".join(parts)

    def _timeframe_delta(self, timeframe: str) -> timedelta:
        normalized = str(timeframe or "").strip().lower()
        if normalized.endswith("min"):
            return timedelta(minutes=max(1, int(normalized[:-3] or "1")))
        if normalized.endswith("hour"):
            return timedelta(hours=max(1, int(normalized[:-4] or "1")))
        if normalized.endswith("day"):
            return timedelta(days=max(1, int(normalized[:-3] or "1")))
        return timedelta(minutes=15)

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
        paper_blocker_labels: list[str] = []
        live_blocker_labels: list[str] = []
        if not windows_ok:
            paper_blocker_labels.append("insufficient_replay_windows")
            live_blocker_labels.append("insufficient_replay_windows")
        if not sample_ok:
            paper_blocker_labels.append("insufficient_sample_size")
            live_blocker_labels.append("insufficient_sample_size")
        if not return_ok:
            paper_blocker_labels.append("net_return_below_threshold")
            live_blocker_labels.append("net_return_below_threshold")
        if not win_ok:
            paper_blocker_labels.append("win_rate_below_threshold")
            live_blocker_labels.append("win_rate_below_threshold")
        paper_policy_notes: list[str] = []
        if not self.config.include_backtest_evidence_in_paper_fitness:
            paper_policy_notes.append("paper_allocation_excludes_backtest_evidence")
        if not self.config.include_backtest_evidence_in_live_fitness:
            live_blocker_labels.append("live_allocation_excludes_backtest_evidence")

        recommendation = "research_only"
        if windows_ok and sample_ok and return_ok and win_ok:
            recommendation = "paper_candidate"
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
                *paper_blocker_labels,
                *[
                    f"timeframe:{item.get('timeframe', '-')}/{item.get('reason', '-')}"
                    for item in skipped_timeframes
                ],
            ],
            "paper_blocker_reasons": [
                *paper_blocker_labels,
                *[
                    f"timeframe:{item.get('timeframe', '-')}/{item.get('reason', '-')}"
                    for item in skipped_timeframes
                ],
            ],
            "paper_policy_notes": paper_policy_notes,
            "live_blocker_reasons": [
                *live_blocker_labels,
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
            "paper_path_blocked": bool(paper_blocker_labels or skipped_timeframes),
            "live_path_blocked": bool(live_blocker_labels or skipped_timeframes),
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
                "paper_blocker_reasons": list(decision.get("paper_blocker_reasons", [])),
                "paper_policy_notes": list(decision.get("paper_policy_notes", [])),
                "live_blocker_reasons": list(decision.get("live_blocker_reasons", [])),
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
                "cycle_origin": self.cycle_origin,
                "parent_process_mode": self.parent_process_mode,
                "command_source": self.command_source,
                "force_mode": self.force_mode,
                "selected_symbol_universe": {
                    "equity": list(self.config.discovery_equity_symbols),
                    "crypto": list(self.config.discovery_crypto_symbols),
                },
                "replay_setting_sources": self._replay_setting_snapshot(),
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
                "selection_anchor_end_at": self._iso_or_blank(
                    diagnostics.get("selection_anchor_end_at")
                ),
                "pre_replay_refresh_enabled": str(
                    diagnostics.get("pre_replay_refresh_enabled", "no") or "no"
                ),
                "pre_replay_refresh_dry_run": str(
                    diagnostics.get("pre_replay_refresh_dry_run", "yes") or "yes"
                ),
                "pre_replay_refresh_ran": str(
                    diagnostics.get("pre_replay_refresh_ran", "no") or "no"
                ),
                "pre_replay_refresh_mode": str(
                    diagnostics.get("pre_replay_refresh_mode", "disabled") or "disabled"
                ),
                "pre_replay_refresh_asset_classes": list(
                    diagnostics.get("pre_replay_refresh_asset_classes", []) or []
                ),
                "pre_replay_refresh_symbols": dict(
                    diagnostics.get("pre_replay_refresh_symbols", {}) or {}
                ),
                "pre_replay_refresh_safety_guard": str(
                    diagnostics.get(
                        "pre_replay_refresh_safety_guard",
                        "historical_backfill_only_no_orders_no_auto_approvals",
                    )
                    or "historical_backfill_only_no_orders_no_auto_approvals"
                ),
                "latest_bar_before_refresh": self._iso_or_blank(
                    diagnostics.get("latest_bar_before_refresh")
                ),
                "latest_bar_after_refresh": self._iso_or_blank(
                    diagnostics.get("latest_bar_after_refresh")
                ),
                "bars_inserted_by_refresh": int(
                    diagnostics.get("bars_inserted_by_refresh", 0) or 0
                ),
                "bars_updated_by_refresh": int(
                    diagnostics.get("bars_updated_by_refresh", 0) or 0
                ),
                "refresh_attempted_symbols": dict(
                    diagnostics.get("refresh_attempted_symbols", {}) or {}
                ),
                "refresh_success_symbols": dict(
                    diagnostics.get("refresh_success_symbols", {}) or {}
                ),
                "refresh_failed_symbols": dict(
                    diagnostics.get("refresh_failed_symbols", {}) or {}
                ),
                "refresh_skipped_symbols": dict(
                    diagnostics.get("refresh_skipped_symbols", {}) or {}
                ),
                "refresh_skip_reasons": dict(
                    diagnostics.get("refresh_skip_reasons", {}) or {}
                ),
                "provider_error_count": int(
                    diagnostics.get("provider_error_count", 0) or 0
                ),
                "provider_errors": list(diagnostics.get("provider_errors", []) or []),
                "refresh_error_count": int(
                    diagnostics.get("refresh_error_count", 0) or 0
                ),
                "refresh_errors": list(diagnostics.get("refresh_errors", []) or []),
                "refresh_duration_ms": int(
                    diagnostics.get("refresh_duration_ms", 0) or 0
                ),
                "ingestion_ran_this_cycle": str(
                    diagnostics.get("ingestion_ran_this_cycle", "no") or "no"
                ),
                "bars_inserted_this_cycle": int(
                    diagnostics.get("bars_inserted_this_cycle", 0) or 0
                ),
                "bars_updated_this_cycle": int(
                    diagnostics.get("bars_updated_this_cycle", 0) or 0
                ),
                "latest_bar_before_ingestion": self._iso_or_blank(
                    diagnostics.get("latest_bar_before_ingestion")
                ),
                "latest_bar_after_ingestion": self._iso_or_blank(
                    diagnostics.get("latest_bar_after_ingestion")
                ),
                "replay_windows_selected_from_latest_available_data": str(
                    diagnostics.get(
                        "replay_windows_selected_from_latest_available_data",
                        "unknown",
                    )
                    or "unknown"
                ),
                "latest_raw_bar_at": str(diagnostics.get("latest_raw_bar_at", "") or ""),
                "rolling_replay_mode_enabled": str(
                    diagnostics.get("rolling_replay_mode_enabled", "no") or "no"
                ),
                "rolling_replay_cursor_enabled": str(
                    diagnostics.get("rolling_replay_cursor_enabled", "no") or "no"
                ),
                "replay_mode": str(diagnostics.get("replay_mode", "") or ""),
                "learning_progress_this_cycle": str(
                    diagnostics.get("learning_progress_this_cycle", "no") or "no"
                ),
                "max_future_outcome_horizon": str(
                    diagnostics.get("max_future_outcome_horizon", "") or ""
                ),
                "latest_replay_eligible_bar_at": str(
                    diagnostics.get("latest_replay_eligible_bar_at", "") or ""
                ),
                "latest_available_bar_per_asset_class": dict(
                    diagnostics.get("latest_available_bar_per_asset_class", {}) or {}
                ),
                "latest_available_bar_per_symbol": dict(
                    diagnostics.get("latest_available_bar_per_symbol", {}) or {}
                ),
                "latest_replay_eligible_bar_per_timeframe": dict(
                    diagnostics.get("latest_replay_eligible_bar_per_timeframe", {}) or {}
                ),
                "latest_replay_eligible_bar_per_asset_class": dict(
                    diagnostics.get("latest_replay_eligible_bar_per_asset_class", {}) or {}
                ),
                "latest_replay_eligible_at_by_bucket": dict(
                    diagnostics.get("latest_replay_eligible_at_by_bucket", {}) or {}
                ),
                "previous_replay_eligible_at_by_bucket": dict(
                    diagnostics.get("previous_replay_eligible_at_by_bucket", {}) or {}
                ),
                "replay_eligible_advance_delta_by_bucket": dict(
                    diagnostics.get("replay_eligible_advance_delta_by_bucket", {}) or {}
                ),
                "last_replayed_until_by_bucket": dict(
                    diagnostics.get("last_replayed_until_by_bucket", {}) or {}
                ),
                "unseen_replay_range_available_by_bucket": dict(
                    diagnostics.get("unseen_replay_range_available_by_bucket", {}) or {}
                ),
                "next_unseen_replay_start_by_bucket": dict(
                    diagnostics.get("next_unseen_replay_start_by_bucket", {}) or {}
                ),
                "next_unseen_replay_end_by_bucket": dict(
                    diagnostics.get("next_unseen_replay_end_by_bucket", {}) or {}
                ),
                "candidate_replay_windows_considered": list(
                    diagnostics.get("candidate_replay_windows_considered", []) or []
                ),
                "candidate_replay_windows_rejected": list(
                    diagnostics.get("candidate_replay_windows_rejected", []) or []
                ),
                "selected_replay_windows": list(
                    diagnostics.get("selected_replay_windows", []) or []
                ),
                "selected_replay_window_reason": str(
                    diagnostics.get("selected_replay_window_reason", "") or ""
                ),
                "max_allowed_replay_window_end": str(
                    diagnostics.get("max_allowed_replay_window_end", "") or ""
                ),
                "global_anchor_enabled": str(
                    diagnostics.get("global_anchor_enabled", "") or ""
                ),
                "global_anchor_time": str(
                    diagnostics.get("global_anchor_time", "") or ""
                ),
                "global_anchor_constrained_by_asset_class": str(
                    diagnostics.get("global_anchor_constrained_by_asset_class", "") or ""
                ),
                "global_anchor_constrained_by_timeframe": str(
                    diagnostics.get("global_anchor_constrained_by_timeframe", "") or ""
                ),
                "global_anchor_constrained_by_symbol": str(
                    diagnostics.get("global_anchor_constrained_by_symbol", "") or ""
                ),
                "freshness_lost_to_future_outcome_horizon": str(
                    diagnostics.get("freshness_lost_to_future_outcome_horizon", "") or ""
                ),
                "freshness_lost_to_global_anchor": str(
                    diagnostics.get("freshness_lost_to_global_anchor", "") or ""
                ),
                "selected_replay_window_end_by_timeframe": dict(
                    diagnostics.get("selected_replay_window_end_by_timeframe", {}) or {}
                ),
                "selected_replay_window_end_by_asset_class": dict(
                    diagnostics.get("selected_replay_window_end_by_asset_class", {}) or {}
                ),
                "selected_replay_window_end_by_bucket": dict(
                    diagnostics.get("selected_replay_window_end_by_bucket", {}) or {}
                ),
                "accepted_replay_window_count_by_timeframe": dict(
                    diagnostics.get("accepted_replay_window_count_by_timeframe", {}) or {}
                ),
                "accepted_replay_window_count_by_asset_class": dict(
                    diagnostics.get("accepted_replay_window_count_by_asset_class", {}) or {}
                ),
                "selected_anchor_time_by_bucket": dict(
                    diagnostics.get("selected_anchor_time_by_bucket", {}) or {}
                ),
                "candidate_anchor_time_by_bucket": dict(
                    diagnostics.get("candidate_anchor_time_by_bucket", {}) or {}
                ),
                "rejected_bucket_anchor_time_by_bucket": dict(
                    diagnostics.get("rejected_bucket_anchor_time_by_bucket", {}) or {}
                ),
                "freshness_gain_vs_global_by_bucket": dict(
                    diagnostics.get("freshness_gain_vs_global_by_bucket", {}) or {}
                ),
                "windows_selected_by_bucket": dict(
                    diagnostics.get("windows_selected_by_bucket", {}) or {}
                ),
                "windows_rejected_by_bucket": dict(
                    diagnostics.get("windows_rejected_by_bucket", {}) or {}
                ),
                "bucket_rejection_reasons": dict(
                    diagnostics.get("bucket_rejection_reasons", {}) or {}
                ),
                "replay_selection_mode": str(
                    diagnostics.get("replay_selection_mode", "") or ""
                ),
                "alternative_replay_selection_modes_available": str(
                    diagnostics.get(
                        "alternative_replay_selection_modes_available",
                        "",
                    )
                    or ""
                ),
                "simulated_asset_class_anchor_time": dict(
                    diagnostics.get("simulated_asset_class_anchor_time", {}) or {}
                ),
                "simulated_asset_class_and_timeframe_anchor_time": dict(
                    diagnostics.get(
                        "simulated_asset_class_and_timeframe_anchor_time",
                        {},
                    )
                    or {}
                ),
                "simulated_freshness_gain_by_asset_class": dict(
                    diagnostics.get(
                        "simulated_freshness_gain_by_asset_class",
                        {},
                    )
                    or {}
                ),
                "simulated_freshness_gain_by_asset_class_and_timeframe": dict(
                    diagnostics.get(
                        "simulated_freshness_gain_by_asset_class_and_timeframe",
                        {},
                    )
                    or {}
                ),
                "strategies_helped_by_isolated_replay": list(
                    diagnostics.get("strategies_helped_by_isolated_replay", []) or []
                ),
                "strategies_unaffected_by_isolated_replay": list(
                    diagnostics.get("strategies_unaffected_by_isolated_replay", []) or []
                ),
                "strategies_blocked_by_mixed_global_anchor": list(
                    diagnostics.get("strategies_blocked_by_mixed_global_anchor", []) or []
                ),
                "minimum_required_window_completeness": str(
                    diagnostics.get("minimum_required_window_completeness", "") or ""
                ),
                "lookback_window_policy": str(
                    diagnostics.get("lookback_window_policy", "") or ""
                ),
                "warmup_buffer_policy": str(
                    diagnostics.get("warmup_buffer_policy", "") or ""
                ),
                "market_hours_policy": str(
                    diagnostics.get("market_hours_policy", "") or ""
                ),
                "weekend_policy": str(
                    diagnostics.get("weekend_policy", "") or ""
                ),
                "asset_class_window_policy": str(
                    diagnostics.get("asset_class_window_policy", "") or ""
                ),
                "reason_latest_bars_not_used_for_replay": str(
                    diagnostics.get("reason_latest_bars_not_used_for_replay", "") or ""
                ),
                "plain_english_replay_anchor_explanation": str(
                    diagnostics.get("plain_english_replay_anchor_explanation", "") or ""
                ),
                "reason_if_not": str(diagnostics.get("reason_if_not", "") or ""),
                "selected_window_ids_current": dict(
                    diagnostics.get("selected_window_ids_current", {}) or {}
                ),
                "selected_window_ids_previous": dict(
                    diagnostics.get("selected_window_ids_previous", {}) or {}
                ),
                "selected_window_set_changed": str(
                    diagnostics.get("selected_window_set_changed", "") or ""
                ),
                "new_replay_windows_selected_count": int(
                    diagnostics.get("new_replay_windows_selected_count", 0) or 0
                ),
                "duplicate_replay_windows_skipped_count": int(
                    diagnostics.get("duplicate_replay_windows_skipped_count", 0) or 0
                ),
                "replay_evidence_new_rows_inserted": int(
                    diagnostics.get("replay_evidence_new_rows_inserted", 0) or 0
                ),
                "replay_evidence_duplicate_rows_skipped": int(
                    diagnostics.get("replay_evidence_duplicate_rows_skipped", 0) or 0
                ),
                "reason_replay_window_not_advancing": str(
                    diagnostics.get("reason_replay_window_not_advancing", "") or ""
                ),
                "reason_no_learning_progress": str(
                    diagnostics.get("reason_no_learning_progress", "") or ""
                ),
                "asset_class_freshness_status": dict(
                    diagnostics.get("asset_class_freshness_status", {}) or {}
                ),
                "window_anchor_mode": str(diagnostics.get("window_anchor_mode", "") or ""),
                "timeframe_historical_coverage": dict(
                    diagnostics.get("timeframe_historical_coverage", {}) or {}
                ),
                "selected_symbol_universe": {
                    "equity": list(self.config.discovery_equity_symbols),
                    "crypto": list(self.config.discovery_crypto_symbols),
                },
                "timeframes_used": [plan.timeframe for plan in plans if plan.status == "ready"],
                "timeframes_skipped": [
                    {"timeframe": plan.timeframe, "reason": plan.reason}
                    for plan in plans
                    if plan.status != "ready"
                ],
                "timeframe_plans": [
                    {
                        "timeframe": plan.timeframe,
                        "status": plan.status,
                        "reason": plan.reason,
                        "available_symbols": list(plan.available_symbols),
                        "available_timeframes": list(plan.available_timeframes),
                        "readiness": self._serialize_readiness(dict(plan.readiness or {})),
                        "historical_coverage": self._serialize_coverage(
                            dict(plan.historical_coverage or {})
                        ),
                        "windows": [
                            {
                                "start_at": window.start_at.isoformat(),
                                "end_at": window.end_at.isoformat(),
                            }
                            for window in plan.windows
                        ],
                    }
                    for plan in plans
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
                "replay_window_rejection_reasons": sorted(
                    {
                        str(item.get("reason", "") or "").strip()
                        for item in list(diagnostics.get("replay_window_rejections", []) or [])
                        if str(item.get("reason", "") or "").strip()
                    }
                ),
                "replay_window_candidate_count": len(
                    list(diagnostics.get("replay_window_candidates", []) or [])
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
