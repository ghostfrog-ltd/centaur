from __future__ import annotations

from datetime import datetime
from typing import Any

from app.framework.engine.research_cycle import ResearchCycleRunner
from app.framework.runtime.attention_alerts import (
    approval_request_id,
    build_event_id,
    create_attention_alert,
)
from app.framework.strategies.registry import build_strategy_registry


def run_autonomous_learning_cycle(context: Any) -> dict[str, Any]:
    """Run the safe autonomous learning lane without enabling execution.

    This hook is intentionally limited to replay research and evidence
    generation. It must never approve broker paper, enable live trading, or
    place orders on its own.
    """

    diagnostics = _base_diagnostics(context=context)
    diagnostics["autonomous_learning_called"] = True
    diagnostics["research_cycle_enabled"] = bool(
        getattr(context.config, "research_cycle_enabled", False)
    )
    diagnostics["research_cycle_enabled_raw_value"] = str(
        getattr(context.config, "research_cycle_enabled_raw_value", "") or ""
    )
    diagnostics["research_cycle_enabled_env_file_value"] = str(
        getattr(context.config, "research_cycle_enabled_env_file_value", "") or ""
    )
    diagnostics["research_cycle_enabled_value_source"] = str(
        getattr(context.config, "research_cycle_enabled_value_source", "") or ""
    )
    diagnostics["research_cycle_env_path"] = str(
        getattr(context.config, "research_cycle_env_path", "") or ""
    )
    diagnostics["forced_research_cycle"] = _force_research_cycle_requested(context=context)
    if not diagnostics["research_cycle_enabled"]:
        diagnostics["research_cycle_skipped_reason"] = "research_disabled"
        result = {
            "status": "disabled",
            "triggered": False,
            "reason": "research_cycle_disabled",
            "broker_orders_created": 0,
            "live_orders_created": 0,
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            **diagnostics,
        }
        _store_runtime_snapshot(context=context, result=result)
        return result

    due_state = _research_cycle_due_state(context=context)
    diagnostics["research_cycle_due"] = bool(due_state.get("due"))
    diagnostics["research_cycle_skipped_reason"] = str(due_state.get("reason", "") or "")
    diagnostics["research_cycle_last_started_at"] = str(due_state.get("last_started_at", "") or "")
    diagnostics["research_cycle_min_interval_minutes"] = int(
        due_state.get("min_interval_minutes", 0) or 0
    )
    if not diagnostics["research_cycle_due"]:
        result = {
            "status": "skipped",
            "triggered": False,
            "reason": diagnostics["research_cycle_skipped_reason"] or "not_due_yet",
            "broker_orders_created": 0,
            "live_orders_created": 0,
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            **diagnostics,
        }
        _store_runtime_snapshot(context=context, result=result)
        return result

    try:
        diagnostics["research_cycle_started"] = True
        report = _build_research_cycle_runner(context=context).run()
    except Exception as exc:
        now = getattr(context, "started_at", None)
        if not isinstance(now, datetime):
            now = datetime.now().astimezone()
        create_attention_alert(
            usage_ledger=context.usage_ledger,
            now=now,
            event_id=build_event_id(event_type="research_cycle_failure"),
            severity="critical",
            event_type="research_cycle_failure",
            title="Autonomous research cycle failed",
            message=(
                "Autopilot could not complete the safe research cycle. "
                "Broker paper and live remain blocked."
            ),
            evidence_summary={"error": f"{type(exc).__name__}: {exc}"},
            recommended_action="Inspect research-cycle logs and historical data readiness.",
            requires_attention=True,
            source="real_heartbeat",
        )
        diagnostics["attention_alerts_created"] = 1
        diagnostics["research_cycle_skipped_reason"] = "cycle_failed_before_persistence"
        result = {
            "status": "error",
            "triggered": True,
            "reason": f"{type(exc).__name__}: {exc}",
            "broker_orders_created": 0,
            "live_orders_created": 0,
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            **diagnostics,
        }
        _store_runtime_snapshot(context=context, result=result)
        return result

    research_state = dict((report.state_snapshot or {}).get("research_cycle", {}) or {})
    decision_rows = list(research_state.get("decisions", []) or [])
    diagnostics["research_cycle_completed"] = True
    diagnostics["research_cycle_source"] = str(
        ((report.state_snapshot or {}).get("run", {}) or {}).get("source", "real_heartbeat")
        or "real_heartbeat"
    )
    diagnostics["research_cycle_id"] = str(report.tick_id or "")
    diagnostics["research_decisions_written"] = int(
        research_state.get("research_decisions_written", 0) or 0
    )
    diagnostics["usable_decisions_count"] = len(decision_rows)
    if getattr(report, "persistence_error", None):
        diagnostics["research_cycle_skipped_reason"] = "storage_write_failed"
    elif diagnostics["research_cycle_source"] != "real_heartbeat":
        diagnostics["research_cycle_skipped_reason"] = "wrong_source_tag"
    elif not decision_rows:
        diagnostics["research_cycle_skipped_reason"] = "no_usable_decisions"
    decision_index = {
        (
            str(item.get("strategy_id", "")),
            str(item.get("profile_id", "")),
        ): item
        for item in decision_rows
    }
    profile_catalog = _discover_strategy_profiles(config=context.config)
    strategy_profiles: list[dict[str, Any]] = []
    internal_stage_changes = 0
    paper_candidates_created = 0
    paper_removal_candidates_created = 0
    slack_attention_alerts_created = 0
    for profile_row in profile_catalog:
        strategy_id = str(profile_row.get("strategy_id", ""))
        profile_id = str(profile_row.get("profile_id", ""))
        decision = decision_index.get((strategy_id, profile_id), {})
        current_record = {}
        promotion_getter = getattr(context.usage_ledger, "get_strategy_promotion", None)
        if callable(promotion_getter):
            current_record = dict(
                promotion_getter(strategy_id=strategy_id, profile_id=profile_id) or {}
            )
        current_stage = _derive_internal_stage(decision=decision, promotion=current_record)
        execution_permission = "none"
        if bool(current_record.get("live_approved")):
            execution_permission = "live_approved"
        elif bool(current_record.get("paper_approved")):
            execution_permission = "paper_approved"
        alert_count = _create_manual_review_alerts(
            context=context,
            strategy_id=strategy_id,
            profile_id=profile_id,
            stage=current_stage,
        )
        paper_candidate_alert_open = _is_attention_alert_open(
            context=context,
            event_type="paper_candidate",
            strategy_id=strategy_id,
            profile_id=profile_id,
        )
        paper_removal_candidate_alert_open = _is_attention_alert_open(
            context=context,
            event_type="paper_removal_candidate",
            strategy_id=strategy_id,
            profile_id=profile_id,
        )
        research_evaluated = bool(decision)
        paper_sim_evaluated = bool(int(decision.get("outcomes_recorded", 0) or 0) > 0)
        skipped_reasons = list(decision.get("blocker_reasons", []) or [])
        if not research_evaluated:
            skipped_reasons.append("no_research_cycle_decision_recorded")
        if not paper_sim_evaluated:
            skipped_reasons.append("no_paper_sim_evidence_recorded")
        if current_stage != "research_only":
            internal_stage_changes += 1
        if current_stage == "paper_candidate":
            paper_candidates_created += 1
        if current_stage == "paper_removal_candidate":
            paper_removal_candidates_created += 1
        slack_attention_alerts_created += alert_count
        strategy_profiles.append(
            {
                **profile_row,
                "research_evaluated": research_evaluated,
                "paper_sim_evaluated": paper_sim_evaluated,
                "skipped_reasons": skipped_reasons,
                "internal_stage": current_stage,
                "execution_permission": execution_permission,
                "paper_candidate_alert_open": paper_candidate_alert_open,
                "paper_removal_candidate_alert_open": paper_removal_candidate_alert_open,
            }
        )
    promotion_changes = [
        {
            "strategy_id": str(item.get("strategy_id", "")),
            "profile_id": str(item.get("profile_id", "")),
            "recommendation": str(item.get("internal_stage", "research_only")),
            "stage": str(item.get("internal_stage", "research_only")),
        }
        for item in strategy_profiles
    ]
    result = {
        "status": "ok",
        "triggered": True,
        "research_cycle_id": report.tick_id,
        "decisions_recorded": len(decision_rows),
        "timeframes_used": list(research_state.get("timeframes_used", []) or []),
        "timeframes_skipped": list(research_state.get("timeframes_skipped", []) or []),
        "promotion_changes": promotion_changes,
        "manual_approval_required": any(
            str(item.get("stage", "")) in {"paper_candidate", "live_candidate"}
            for item in promotion_changes
        ),
        "strategy_profiles": strategy_profiles,
        "strategy_profiles_discovered": len(strategy_profiles),
        "strategy_profiles_evaluated": sum(
            1 for item in strategy_profiles if bool(item.get("research_evaluated"))
        ),
        "strategy_profiles_skipped": sum(
            1 for item in strategy_profiles if not bool(item.get("research_evaluated"))
        ),
        "internal_stage_changes": internal_stage_changes,
        "paper_candidates_created": paper_candidates_created,
        "paper_removal_candidates_created": paper_removal_candidates_created,
        "slack_attention_alerts_created": slack_attention_alerts_created,
        "broker_orders_created": 0,
        "live_orders_created": 0,
        "auto_paper_approved": 0,
        "auto_paper_removed": 0,
        "auto_live_approved": 0,
        "auto_live_removed": 0,
        "live_execution_remains_disabled": bool(
            research_state.get("live_execution_remains_disabled", True)
        ),
        "research_cycle_persisted": bool(getattr(report, "persisted_tick_run", False)),
        "research_cycle_persistence_error": str(getattr(report, "persistence_error", "") or ""),
        **diagnostics,
    }
    result["paper_candidates_created"] = paper_candidates_created
    result["paper_removal_candidates_created"] = paper_removal_candidates_created
    result["attention_alerts_created"] = max(
        int(result.get("attention_alerts_created", 0) or 0),
        slack_attention_alerts_created,
    )
    result["attention_alerts_resolved"] = 1 if decision_rows else 0
    _store_runtime_snapshot(context=context, result=result)
    return result


def _base_diagnostics(*, context: Any) -> dict[str, Any]:
    return {
        "autonomous_learning_called": False,
        "research_cycle_enabled": False,
        "research_cycle_due": False,
        "research_cycle_skipped_reason": "",
        "research_cycle_started": False,
        "research_cycle_completed": False,
        "research_cycle_source": "real_heartbeat",
        "research_cycle_id": "",
        "research_decisions_written": 0,
        "usable_decisions_count": 0,
        "paper_candidates_created": 0,
        "paper_removal_candidates_created": 0,
        "attention_alerts_resolved": 0,
        "attention_alerts_created": 0,
        "heartbeat_tick_id": str(getattr(context, "tick_id", "") or ""),
        "research_cycle_enabled_raw_value": "",
        "research_cycle_enabled_env_file_value": "",
        "research_cycle_enabled_value_source": "",
        "research_cycle_env_path": "",
        "research_cycle_last_started_at": "",
        "research_cycle_min_interval_minutes": 0,
        "forced_research_cycle": False,
    }


def _research_cycle_due_state(*, context: Any) -> dict[str, Any]:
    if _force_research_cycle_requested(context=context):
        latest = {}
        getter = getattr(context.usage_ledger, "latest_real_heartbeat_research_cycle_summary", None)
        if callable(getter):
            latest = dict(getter() or {})
        return {
            "due": True,
            "reason": "forced_interval_bypass",
            "last_started_at": str(latest.get("latest_real_research_cycle_started_at", "") or ""),
            "min_interval_minutes": max(
                0,
                int(getattr(context.config, "research_cycle_min_interval_minutes", 0) or 0),
            ),
        }
    min_interval_minutes = max(
        0,
        int(getattr(context.config, "research_cycle_min_interval_minutes", 0) or 0),
    )
    getter = getattr(context.usage_ledger, "latest_real_heartbeat_research_cycle_summary", None)
    latest = dict(getter() or {}) if callable(getter) else {}
    if min_interval_minutes <= 0 or not latest:
        return {
            "due": True,
            "reason": "",
            "last_started_at": str(latest.get("latest_real_research_cycle_started_at", "") or ""),
            "min_interval_minutes": min_interval_minutes,
        }
    last_started_at = _coerce_datetime(latest.get("latest_real_research_cycle_started_at"))
    now = getattr(context, "started_at", None)
    if not isinstance(now, datetime):
        now = datetime.now().astimezone()
    if last_started_at is None:
        return {
            "due": True,
            "reason": "",
            "last_started_at": str(latest.get("latest_real_research_cycle_started_at", "") or ""),
            "min_interval_minutes": min_interval_minutes,
        }
    elapsed_seconds = (now - last_started_at).total_seconds()
    if elapsed_seconds < float(min_interval_minutes * 60):
        return {
            "due": False,
            "reason": "not_due_yet",
            "last_started_at": last_started_at.isoformat(),
            "min_interval_minutes": min_interval_minutes,
        }
    return {
        "due": True,
        "reason": "",
        "last_started_at": last_started_at.isoformat(),
        "min_interval_minutes": min_interval_minutes,
    }


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _store_runtime_snapshot(*, context: Any, result: dict[str, Any]) -> None:
    context.state["autonomous_learning"] = result
    heartbeat = dict(context.state.get("heartbeat", {}) or {})
    heartbeat["autonomous_learning"] = {
        key: result.get(key)
        for key in (
            "status",
            "reason",
            "autonomous_learning_called",
            "research_cycle_enabled",
            "research_cycle_enabled_raw_value",
            "research_cycle_enabled_env_file_value",
            "research_cycle_enabled_value_source",
            "research_cycle_env_path",
            "forced_research_cycle",
            "research_cycle_due",
            "research_cycle_skipped_reason",
            "research_cycle_last_started_at",
            "research_cycle_min_interval_minutes",
            "research_cycle_started",
            "research_cycle_completed",
            "research_cycle_source",
            "research_cycle_id",
            "research_decisions_written",
            "usable_decisions_count",
            "paper_candidates_created",
            "paper_removal_candidates_created",
            "attention_alerts_resolved",
            "attention_alerts_created",
            "research_cycle_persisted",
            "research_cycle_persistence_error",
        )
    }
    context.state["heartbeat"] = heartbeat


def _force_research_cycle_requested(*, context: Any) -> bool:
    """Diagnostic-only override for the heartbeat interval gate.

    This flag must only bypass `RESEARCH_CYCLE_MIN_INTERVAL_MINUTES`. It must
    not alter broker/live safety checks, execution permissions, or manual
    approval requirements anywhere else in the control heartbeat.
    """

    diagnostics = dict(context.state.get("diagnostics", {}) or {})
    return bool(diagnostics.get("force_research_cycle"))


def _discover_strategy_profiles(*, config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in build_strategy_registry():
        try:
            profiles = strategy.build_profiles(config)
        except Exception:
            continue
        for profile in profiles:
            parameters = dict(getattr(profile, "parameters", {}) or {})
            rows.append(
                {
                    "strategy_id": str(profile.strategy_id),
                    "profile_id": str(profile.profile_id),
                    "asset_classes": list(getattr(profile, "asset_classes", ()) or ()),
                    "research_only_profile": bool(parameters.get("research_only")),
                    "paper_allowed": bool(parameters.get("paper_allowed")),
                    "live_allowed": bool(parameters.get("live_allowed")),
                }
            )
    return rows


def _build_research_cycle_runner(*, context: Any) -> ResearchCycleRunner:
    kwargs = {
        "config": context.config,
        "usage_ledger": context.usage_ledger,
        "source": "real_heartbeat",
        "parent_tick_id": str(getattr(context, "tick_id", "") or ""),
    }
    try:
        return ResearchCycleRunner(**kwargs)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument 'source'" not in message and "unexpected keyword argument 'parent_tick_id'" not in message:
            raise
        return ResearchCycleRunner(
            config=context.config,
            usage_ledger=context.usage_ledger,
        )


def _derive_internal_stage(
    *,
    decision: dict[str, Any],
    promotion: dict[str, Any],
) -> str:
    if bool(promotion.get("live_approved")):
        return "live_approved"
    recommendation = str(decision.get("recommendation", "research_only"))
    data_integrity_status = str(decision.get("data_integrity_status", "unknown"))
    if bool(promotion.get("paper_approved")):
        if recommendation in {"research_only", "rejected_research"} or data_integrity_status == "fail":
            return "paper_removal_candidate"
        return "paper_approved"
    if bool(promotion.get("rejected")):
        return "rejected"
    if recommendation == "paper_candidate":
        return "paper_candidate"
    if recommendation == "paper_sim_active":
        return "paper_sim_active"
    if recommendation == "paper_sim_candidate":
        if int(decision.get("outcomes_recorded", 0) or 0) > 0 and data_integrity_status == "pass":
            return "paper_candidate"
        return "paper_sim_candidate"
    if recommendation == "promising_research":
        return "promising_research"
    if recommendation in {
        "research_only",
        "rejected",
        "paper_removal_candidate",
        "live_candidate",
    }:
        return recommendation
    if recommendation == "rejected_research":
        return "rejected"
    return str(promotion.get("stage", "research_only") or "research_only")


def _create_manual_review_alerts(
    *,
    context: Any,
    strategy_id: str,
    profile_id: str,
    stage: str,
) -> int:
    now = getattr(context, "started_at", None)
    if not isinstance(now, datetime):
        now = datetime.now().astimezone()
    approval_id = approval_request_id(strategy_id=strategy_id, profile_id=profile_id)
    if stage == "paper_removal_candidate":
        create_attention_alert(
            usage_ledger=context.usage_ledger,
            now=now,
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
                f"{strategy_id}/{profile_id} needs manual review before any broker paper removal "
                "or unapproval is applied."
            ),
            evidence_summary={"stage": "paper_removal_candidate"},
            recommended_action="Approve or reject the broker paper removal request.",
            requires_attention=True,
            strategy_id=strategy_id,
            profile_id=profile_id,
            approval_request_id_value=approval_id,
            source="real_heartbeat",
        )
        return 1
    if stage == "live_candidate":
        create_attention_alert(
            usage_ledger=context.usage_ledger,
            now=now,
            event_id=build_event_id(
                event_type="live_candidate",
                strategy_id=strategy_id,
                profile_id=profile_id,
                approval_id=approval_id,
            ),
            severity="warning",
            event_type="live_candidate",
            title="Live approval review required",
            message=(
                f"{strategy_id}/{profile_id} reached live_candidate. "
                "Live execution remains blocked until Gary approves it."
            ),
            evidence_summary={"stage": "live_candidate"},
            recommended_action="Approve or reject the live approval request.",
            requires_attention=True,
            strategy_id=strategy_id,
            profile_id=profile_id,
            approval_request_id_value=approval_id,
            source="real_heartbeat",
        )
        return 1
    return 0


def _is_attention_alert_open(
    *,
    context: Any,
    event_type: str,
    strategy_id: str,
    profile_id: str,
) -> bool:
    getter = getattr(context.usage_ledger, "get_attention_alert", None)
    if not callable(getter):
        return False
    approval_id = approval_request_id(strategy_id=strategy_id, profile_id=profile_id)
    row = getter(
        event_id=build_event_id(
            event_type=event_type,
            strategy_id=strategy_id,
            profile_id=profile_id,
            approval_id=approval_id,
        )
    )
    return bool(row) and str((row or {}).get("attention_status", "")) == "open"
