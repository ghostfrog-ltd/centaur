"""Heartbeat step implementation owned by `33_notifications_slack`."""

from __future__ import annotations

from app.heartbeat.support import (
    Any,
    PipelineResult,
    SlackNotificationError,
    SlackWebhookClient,
    TickContext,
    _build_slack_alerts,
    _format_slack_alert,
    timedelta,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Send one-way operator alerts to Slack with persisted dedupe.

    Slack is intentionally notification-only. This step reports broker/risk
    conditions but never accepts commands or mutates trading state.
    """
    if not bool(getattr(context.config, "slack_alerts_enabled", False)):
        result = {"channel": "slack", "mode": "disabled", "alerts_built": 0}
        context.state["slack_notifications"] = result
        return result
    webhook_url = str(getattr(context.config, "slack_webhook_url", "") or "").strip()
    if not webhook_url:
        result = {
            "channel": "slack",
            "mode": "not_configured",
            "alerts_built": 0,
            "reason": "slack_webhook_url_missing",
        }
        context.state["slack_notifications"] = result
        return result

    alerts = _build_slack_alerts(context)
    if not alerts:
        result = {"channel": "slack", "mode": "idle", "alerts_built": 0}
        context.state["slack_notifications"] = result
        return result

    sender = context.metadata.get("slack_post_message")
    client = None
    if not callable(sender):
        client = SlackWebhookClient(
            webhook_url=webhook_url,
            timeout_seconds=int(
                getattr(context.config, "slack_request_timeout_seconds", 5) or 5
            ),
        )

    sent: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for alert in alerts:
        event_key = str(alert.get("event_key", "")).strip()
        dedupe_minutes = max(
            1,
            int(
                alert.get("dedupe_minutes")
                or getattr(context.config, "slack_alert_dedupe_minutes", 360)
                or 360
            ),
        )
        dedupe_since = context.started_at - timedelta(minutes=dedupe_minutes)
        if context.usage_ledger.notification_recently_sent(
            channel="slack",
            event_key=event_key,
            since=dedupe_since,
        ):
            skipped.append(
                {
                    "event_key": event_key,
                    "reason": "deduped",
                    "dedupe_minutes": dedupe_minutes,
                }
            )
            continue
        text = _format_slack_alert(alert)
        try:
            if callable(sender):
                sender(webhook_url, text)
            elif client is not None:
                client.post_message(text)
            context.usage_ledger.record_notification_event(
                tick_id=context.tick_id,
                channel="slack",
                event_key=event_key,
                level=str(alert.get("level", "info")),
                summary=str(alert.get("summary", "")),
                detail=str(alert.get("detail", "")),
                status="sent",
                metadata={"dedupe_minutes": dedupe_minutes},
                sent_at=context.started_at,
            )
            context.record_api_usage(
                source="slack",
                endpoint="incoming_webhook",
                success=True,
                metadata={"event_key": event_key},
            )
            sent.append({"event_key": event_key})
        except (SlackNotificationError, Exception) as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            context.usage_ledger.record_notification_event(
                tick_id=context.tick_id,
                channel="slack",
                event_key=event_key,
                level=str(alert.get("level", "info")),
                summary=str(alert.get("summary", "")),
                detail=str(alert.get("detail", "")),
                status="error",
                error=error_text,
                metadata={"dedupe_minutes": dedupe_minutes},
                sent_at=context.started_at,
            )
            context.record_api_usage(
                source="slack",
                endpoint="incoming_webhook",
                success=False,
                metadata={"event_key": event_key, "error": error_text},
            )
            errors.append({"event_key": event_key, "error": error_text})

    result = {
        "channel": "slack",
        "mode": "alerts",
        "alerts_built": len(alerts),
        "alerts_sent": len(sent),
        "alerts_deduped": len(skipped),
        "errors": len(errors),
    }
    if sent:
        result["sent"] = sent
    if skipped:
        result["skipped"] = skipped
    if errors:
        result["first_error"] = errors[0]["error"]
    context.state["slack_notifications"] = result
    return result
