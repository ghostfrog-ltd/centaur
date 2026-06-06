from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.framework.runtime.slack import SlackNotificationError, SlackWebhookClient


def approval_request_id(*, strategy_id: str, profile_id: str) -> str:
    return f"{str(strategy_id).strip()}::{str(profile_id).strip()}"


def build_event_id(
    *,
    event_type: str,
    strategy_id: str = "",
    profile_id: str = "",
    approval_id: str = "",
) -> str:
    parts = [str(event_type).strip(), str(strategy_id).strip(), str(profile_id).strip(), str(approval_id).strip()]
    return "|".join(part for part in parts if part)


def create_attention_alert(
    *,
    usage_ledger: Any,
    now: datetime,
    event_id: str,
    severity: str,
    event_type: str,
    title: str,
    message: str,
    evidence_summary: dict[str, Any],
    recommended_action: str,
    requires_attention: bool,
    strategy_id: str = "",
    profile_id: str = "",
    approval_request_id_value: str = "",
    source: str = "",
) -> dict[str, Any]:
    get_existing = getattr(usage_ledger, "get_attention_alert", None)
    existing = {}
    if callable(get_existing):
        existing = get_existing(event_id=event_id) or {}
    merged_evidence = dict((existing or {}).get("evidence_summary_json", {}) or {})
    merged_evidence.update(dict(evidence_summary or {}))
    if source:
        merged_evidence["source"] = source
    row = {
        "event_id": event_id,
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
        "severity": severity,
        "event_type": event_type,
        "strategy_id": strategy_id,
        "profile_id": profile_id,
        "title": title,
        "message": message,
        "evidence_summary": merged_evidence,
        "recommended_action": recommended_action,
        "approval_request_id": approval_request_id_value,
        "requires_attention": requires_attention,
        "attention_status": "open",
        "first_slack_sent_at": existing.get("first_slack_sent_at") if existing else None,
        "last_slack_sent_at": existing.get("last_slack_sent_at") if existing else None,
        "next_slack_due_at": now if requires_attention else None,
        "slack_send_count": int(existing.get("slack_send_count", 0) or 0) if existing else 0,
        "slack_sent": bool(existing.get("slack_sent")) if existing else False,
        "slack_error": str(existing.get("slack_error", "") or "") if existing else "",
        "resolved_at": None,
        "resolved_reason": "",
    }
    upsert = getattr(usage_ledger, "upsert_attention_alert", None)
    if callable(upsert):
        upsert(alert=row)
        if callable(get_existing):
            return get_existing(event_id=event_id) or row
    return row


def send_due_attention_alerts(
    *,
    context: Any,
    sender: Any | None = None,
) -> dict[str, Any]:
    if not bool(getattr(context.config, "slack_alerts_enabled", False)):
        return {"alerts_sent": 0, "errors": 0}
    if not bool(getattr(context.config, "slack_attention_repeat_enabled", True)):
        return {"alerts_sent": 0, "errors": 0}
    webhook_url = str(getattr(context.config, "slack_webhook_url", "") or "").strip()
    if not webhook_url:
        return {"alerts_sent": 0, "errors": 0, "reason": "slack_webhook_url_missing"}
    list_due = getattr(context.usage_ledger, "list_due_attention_alerts", None)
    mark_sent = getattr(context.usage_ledger, "mark_attention_alert_sent", None)
    if not callable(list_due) or not callable(mark_sent):
        return {"alerts_sent": 0, "errors": 0, "reason": "attention_alert_storage_unavailable"}
    due_alerts = list(list_due(due_at=context.started_at))
    if not due_alerts:
        return {"alerts_sent": 0, "errors": 0}

    client = None
    if not callable(sender):
        client = SlackWebhookClient(
            webhook_url=webhook_url,
            timeout_seconds=int(getattr(context.config, "slack_request_timeout_seconds", 5) or 5),
        )
    sent = 0
    errors = 0
    for alert in due_alerts:
        alert = _refresh_alert_for_send(context=context, alert=alert)
        text = _format_attention_slack_message(alert=alert, now=context.started_at)
        try:
            if callable(sender):
                sender(webhook_url, text)
            elif client is not None:
                client.post_message(text)
            next_due = _next_due_at(
                now=context.started_at,
                repeat_minutes=int(getattr(context.config, "slack_attention_repeat_minutes", 15) or 15),
                max_repeats=int(getattr(context.config, "slack_attention_max_repeats", 0) or 0),
                current_count=int(alert.get("slack_send_count", 0) or 0) + 1,
            )
            mark_sent(
                event_id=str(alert.get("event_id", "")),
                sent_at=context.started_at,
                next_due_at=next_due,
                slack_send_count=int(alert.get("slack_send_count", 0) or 0) + 1,
                slack_error="",
            )
            context.usage_ledger.record_notification_event(
                tick_id=context.tick_id,
                channel="slack",
                event_key=str(alert.get("event_id", "")),
                level=str(alert.get("severity", "warning")),
                summary=str(alert.get("title", "")),
                detail=str(alert.get("message", "")),
                status="sent",
                metadata={"attention_alert": True},
                sent_at=context.started_at,
            )
            sent += 1
        except (SlackNotificationError, Exception) as exc:
            mark_sent(
                event_id=str(alert.get("event_id", "")),
                sent_at=context.started_at,
                next_due_at=context.started_at
                + timedelta(minutes=int(getattr(context.config, "slack_attention_repeat_minutes", 15) or 15)),
                slack_send_count=int(alert.get("slack_send_count", 0) or 0),
                slack_error=f"{type(exc).__name__}: {exc}",
            )
            errors += 1
    return {"alerts_sent": sent, "errors": errors}


def _next_due_at(
    *,
    now: datetime,
    repeat_minutes: int,
    max_repeats: int,
    current_count: int,
) -> datetime | None:
    if max_repeats > 0 and current_count >= max_repeats:
        return None
    return now + timedelta(minutes=max(1, repeat_minutes))


def _format_attention_slack_message(*, alert: dict[str, Any], now: datetime) -> str:
    created_at = alert.get("created_at")
    open_minutes = 0
    if isinstance(created_at, datetime):
        open_minutes = max(0, int((now - created_at).total_seconds() // 60))
    evidence = _alert_evidence(alert)
    lines = [
        "ATTENTION REQUIRED — still unresolved",
        "",
        f"Event: {alert.get('title', '-')}",
    ]
    if alert.get("strategy_id"):
        lines.append(f"Strategy: {alert.get('strategy_id')}")
    if alert.get("profile_id"):
        lines.append(f"Profile: {alert.get('profile_id')}")
    if evidence.get("stage"):
        lines.append(f"Stage: {evidence.get('stage')}")
    lines.extend(
        [
            f"Tick id: {evidence.get('tick_id', '-')}",
            f"Cycle id: {evidence.get('cycle_id', '-')}",
            f"Source: {evidence.get('source', '-')}",
            f"Created at: {_fmt_dt(alert.get('created_at'))}",
            f"Last checked at: {evidence.get('last_checked_at', '-')}",
            f"Latest real heartbeat tick id: {evidence.get('latest_real_heartbeat_tick_id', '-')}",
            f"Latest real research cycle id: {evidence.get('latest_real_research_cycle_id', '-')}",
            f"Strategy profiles discovered: {evidence.get('strategy_profiles_discovered', '-')}",
            f"Strategy profiles evaluated: {evidence.get('strategy_profiles_evaluated', '-')}",
            f"Usable decisions count: {evidence.get('usable_decisions_count', '-')}",
            f"Paper candidates created: {evidence.get('paper_candidates_created', '-')}",
            f"Paper removal candidates created: {evidence.get('paper_removal_candidates_created', '-')}",
            f"Why still open: {evidence.get('open_reason', '-')}",
        ]
    )
    lines.extend(
        [
            f"Open for: {open_minutes} minutes",
            f"Reminder count: {int(alert.get('slack_send_count', 0) or 0) + 1}",
            "",
            "Broker paper: BLOCKED until manual approval",
            "Live execution: DISABLED",
            "",
            "Recommended action:",
            str(alert.get("recommended_action", "") or "Review and resolve this alert."),
        ]
    )
    approval_cmd = str(evidence.get("approval_command", "") or "")
    reject_cmd = str(evidence.get("reject_command", "") or "")
    if approval_cmd:
        lines.extend(["", "Approval command:", approval_cmd])
    if reject_cmd:
        lines.extend(["", "Reject command:", reject_cmd])
    message = str(alert.get("message", "") or "").strip()
    if message:
        lines.extend(["", message])
    return "\n".join(lines)


def _refresh_alert_for_send(*, context: Any, alert: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(alert)
    evidence = _alert_evidence(refreshed)
    evidence["last_checked_at"] = _fmt_dt(context.started_at)
    event_type = str(refreshed.get("event_type", "") or "")
    if event_type == "research_cycle_failure":
        evidence["source"] = str(evidence.get("source", "") or "real_heartbeat")
        latest_real = _latest_real_heartbeat_research_cycle(context=context)
        if latest_real:
            evidence.update(latest_real)
            evidence.setdefault(
                "tick_id",
                str(latest_real.get("latest_real_heartbeat_tick_id", "") or "-"),
            )
            evidence.setdefault(
                "open_reason",
                "Waiting for a later real heartbeat research cycle to produce usable decisions.",
            )
    refreshed["evidence_summary_json"] = evidence
    upsert = getattr(context.usage_ledger, "upsert_attention_alert", None)
    if callable(upsert):
        refreshed_for_store = dict(refreshed)
        refreshed_for_store["evidence_summary"] = evidence
        upsert(alert=refreshed_for_store)
    return refreshed


def _latest_real_heartbeat_research_cycle(*, context: Any) -> dict[str, Any]:
    getter = getattr(context.usage_ledger, "latest_real_heartbeat_research_cycle_summary", None)
    if not callable(getter):
        return {}
    return dict(getter() or {})


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "-")


def _alert_evidence(alert: dict[str, Any]) -> dict[str, Any]:
    raw = alert.get("evidence_summary_json", None)
    if raw is None:
        raw = alert.get("evidence_summary", {})
    evidence = dict(raw or {})
    if not evidence.get("source"):
        event_type = str(alert.get("event_type", "") or "")
        if event_type == "research_cycle_failure":
            evidence["source"] = "real_heartbeat"
    return evidence
