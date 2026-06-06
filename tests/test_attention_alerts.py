from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from app.framework.reporting.promotion_gate import PromotionGateReport
from app.framework.runtime.attention_alerts import (
    approval_request_id,
    build_event_id,
    create_attention_alert,
    send_due_attention_alerts,
)
from app.heartbeat import support


class _AlertLedger:
    def __init__(self) -> None:
        self.alerts: dict[str, dict[str, object]] = {}
        self.notification_events: list[dict[str, object]] = []
        self.resolve_calls: list[dict[str, object]] = []

    def upsert_attention_alert(self, *, alert: dict[str, object]) -> None:
        existing = self.alerts.get(alert["event_id"], {})
        self.alerts[alert["event_id"]] = {**existing, **alert}

    def get_attention_alert(self, *, event_id: str):
        return self.alerts.get(event_id)

    def list_due_attention_alerts(self, *, due_at: datetime):
        rows = []
        for alert in self.alerts.values():
            if (
                bool(alert.get("requires_attention"))
                and str(alert.get("attention_status", "")) == "open"
                and isinstance(alert.get("next_slack_due_at"), datetime)
                and alert["next_slack_due_at"] <= due_at
            ):
                rows.append(alert)
        return rows

    def mark_attention_alert_sent(
        self,
        *,
        event_id: str,
        sent_at: datetime,
        next_due_at: datetime | None,
        slack_send_count: int,
        slack_error: str = "",
    ) -> None:
        alert = self.alerts[event_id]
        alert["updated_at"] = sent_at
        alert["first_slack_sent_at"] = alert.get("first_slack_sent_at") or sent_at
        alert["last_slack_sent_at"] = sent_at
        alert["next_slack_due_at"] = next_due_at
        alert["slack_send_count"] = slack_send_count
        alert["slack_sent"] = True
        alert["slack_error"] = slack_error

    def record_notification_event(self, **kwargs) -> None:
        self.notification_events.append(kwargs)

    def latest_real_heartbeat_research_cycle_summary(self) -> dict[str, object]:
        return {
            "latest_real_heartbeat_tick_id": "heartbeat-123",
            "latest_real_research_cycle_id": "researchcycle-123",
            "strategy_profiles_discovered": 9,
            "strategy_profiles_evaluated": 9,
            "usable_decisions_count": 0,
            "paper_candidates_created": 0,
            "paper_removal_candidates_created": 0,
            "blockers": ["no_replay_runs"],
        }

    def resolve_attention_alerts_for_approval_request(
        self,
        *,
        approval_request_id: str,
        status: str,
        reason: str,
    ) -> None:
        self.resolve_calls.append(
            {
                "approval_request_id": approval_request_id,
                "status": status,
                "reason": reason,
            }
        )

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str):
        return {
            "strategy_id": strategy_id,
            "profile_id": profile_id,
            "stage": "paper_candidate",
            "paper_approved": 0,
            "live_approved": 0,
            "paper_execution_profile": 0,
            "research_only_profile": 1,
            "max_paper_notional_usd": 0.0,
            "max_open_trades": 0,
            "cooldown_minutes": 0,
        }

    def approve_strategy_for_paper(self, **_kwargs) -> None:
        return None

    def reject_strategy_promotion(self, **_kwargs) -> None:
        return None

    def record_strategy_promotion_evaluation(self, **_kwargs) -> None:
        return None


class AttentionAlertTests(unittest.TestCase):
    def test_attention_alert_sends_immediately_and_repeats_when_due(self) -> None:
        ledger = _AlertLedger()
        now = datetime.now().astimezone()
        event_id = build_event_id(event_type="paper_candidate", strategy_id="s", profile_id="p")
        create_attention_alert(
            usage_ledger=ledger,
            now=now,
            event_id=event_id,
            severity="warning",
            event_type="paper_candidate",
            title="Broker paper approval required",
            message="Still blocked.",
            evidence_summary={},
            recommended_action="Approve or reject.",
            requires_attention=True,
            strategy_id="s",
            profile_id="p",
            approval_request_id_value=approval_request_id(strategy_id="s", profile_id="p"),
        )
        sent_messages: list[str] = []
        context = SimpleNamespace(
            tick_id="t1",
            started_at=now,
            config=SimpleNamespace(
                slack_alerts_enabled=True,
                slack_attention_repeat_enabled=True,
                slack_attention_repeat_minutes=15,
                slack_attention_max_repeats=0,
                slack_request_timeout_seconds=5,
                slack_webhook_url="https://hooks.slack.test/services/example",
            ),
            usage_ledger=ledger,
        )
        first = send_due_attention_alerts(
            context=context,
            sender=lambda _webhook, text: sent_messages.append(text),
        )
        self.assertEqual(first["alerts_sent"], 1)
        self.assertEqual(ledger.alerts[event_id]["slack_send_count"], 1)
        self.assertNotIn("hooks.slack.test", sent_messages[0])

        context.started_at = now + timedelta(minutes=10)
        early = send_due_attention_alerts(
            context=context,
            sender=lambda _webhook, text: sent_messages.append(text),
        )
        self.assertEqual(early["alerts_sent"], 0)
        self.assertEqual(ledger.alerts[event_id]["slack_send_count"], 1)

        context.started_at = now + timedelta(minutes=16)
        later = send_due_attention_alerts(
            context=context,
            sender=lambda _webhook, text: sent_messages.append(text),
        )
        self.assertEqual(later["alerts_sent"], 1)
        self.assertEqual(ledger.alerts[event_id]["slack_send_count"], 2)

    def test_resolved_alert_stops_repeating_and_info_alert_does_not_repeat(self) -> None:
        ledger = _AlertLedger()
        now = datetime.now().astimezone()
        attention_id = build_event_id(event_type="attention")
        create_attention_alert(
            usage_ledger=ledger,
            now=now,
            event_id=attention_id,
            severity="critical",
            event_type="attention",
            title="Needs attention",
            message="Still open.",
            evidence_summary={},
            recommended_action="Review.",
            requires_attention=True,
        )
        info_id = build_event_id(event_type="info")
        create_attention_alert(
            usage_ledger=ledger,
            now=now,
            event_id=info_id,
            severity="info",
            event_type="info",
            title="Info only",
            message="Completed.",
            evidence_summary={},
            recommended_action="None.",
            requires_attention=False,
        )
        context = SimpleNamespace(
            tick_id="t1",
            started_at=now,
            config=SimpleNamespace(
                slack_alerts_enabled=True,
                slack_attention_repeat_enabled=True,
                slack_attention_repeat_minutes=15,
                slack_attention_max_repeats=0,
                slack_request_timeout_seconds=5,
                slack_webhook_url="https://hooks.slack.test/services/example",
            ),
            usage_ledger=ledger,
        )
        send_due_attention_alerts(context=context, sender=lambda *_args: None)
        ledger.alerts[attention_id]["attention_status"] = "resolved"
        context.started_at = now + timedelta(minutes=30)
        result = send_due_attention_alerts(context=context, sender=lambda *_args: None)
        self.assertEqual(result["alerts_sent"], 0)
        self.assertEqual(int(ledger.alerts[info_id]["slack_send_count"]), 0)

    def test_slack_failure_records_error_without_crashing(self) -> None:
        ledger = _AlertLedger()
        now = datetime.now().astimezone()
        event_id = build_event_id(event_type="paper_candidate", strategy_id="s", profile_id="p")
        create_attention_alert(
            usage_ledger=ledger,
            now=now,
            event_id=event_id,
            severity="warning",
            event_type="paper_candidate",
            title="Broker paper approval required",
            message="Still blocked.",
            evidence_summary={},
            recommended_action="Approve or reject.",
            requires_attention=True,
        )
        context = SimpleNamespace(
            tick_id="t1",
            started_at=now,
            config=SimpleNamespace(
                slack_alerts_enabled=True,
                slack_attention_repeat_enabled=True,
                slack_attention_repeat_minutes=15,
                slack_attention_max_repeats=0,
                slack_request_timeout_seconds=5,
                slack_webhook_url="https://hooks.slack.test/services/example",
            ),
            usage_ledger=ledger,
        )
        result = send_due_attention_alerts(
            context=context,
            sender=lambda _webhook, _text: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        self.assertEqual(result["errors"], 1)
        self.assertIn("RuntimeError: boom", ledger.alerts[event_id]["slack_error"])

    def test_research_cycle_failure_slack_message_includes_source_and_cycle_diagnostics(self) -> None:
        ledger = _AlertLedger()
        now = datetime.now().astimezone()
        event_id = build_event_id(event_type="research_cycle_failure")
        create_attention_alert(
            usage_ledger=ledger,
            now=now,
            event_id=event_id,
            severity="critical",
            event_type="research_cycle_failure",
            title="Research cycle produced no usable decisions",
            message="Research cycle could not produce any usable replay decisions.",
            evidence_summary={
                "tick_id": "heartbeat-122",
                "cycle_id": "researchcycle-122",
                "source": "real_heartbeat",
                "strategy_profiles_discovered": 9,
                "strategy_profiles_evaluated": 9,
                "usable_decisions_count": 0,
                "paper_candidates_created": 0,
                "paper_removal_candidates_created": 0,
                "open_reason": "Waiting for a later real heartbeat research cycle to produce usable decisions.",
            },
            recommended_action="Inspect research-cycle logs and historical data readiness.",
            requires_attention=True,
            source="real_heartbeat",
        )
        sent_messages: list[str] = []
        context = SimpleNamespace(
            tick_id="t1",
            started_at=now,
            config=SimpleNamespace(
                slack_alerts_enabled=True,
                slack_attention_repeat_enabled=True,
                slack_attention_repeat_minutes=15,
                slack_attention_max_repeats=0,
                slack_request_timeout_seconds=5,
                slack_webhook_url="https://hooks.slack.test/services/example",
            ),
            usage_ledger=ledger,
        )
        send_due_attention_alerts(
            context=context,
            sender=lambda _webhook, text: sent_messages.append(text),
        )
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Tick id: heartbeat-122", sent_messages[0])
        self.assertIn("Cycle id: researchcycle-122", sent_messages[0])
        self.assertIn("Source: real_heartbeat", sent_messages[0])
        self.assertIn("Latest real heartbeat tick id: heartbeat-123", sent_messages[0])
        self.assertIn("Latest real research cycle id: researchcycle-123", sent_messages[0])

    def test_approve_and_reject_resolve_related_alert(self) -> None:
        ledger = _AlertLedger()
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="s",
            profile_id="p",
            parameters={},
        )
        reporter.evaluate = lambda **_kwargs: {"recommendation": "paper_sim_candidate", "blocker_reasons": []}
        reporter.approve_paper(
            strategy_id="s",
            profile_id="p",
            max_paper_notional_usd=10.0,
            max_open_trades=1,
            cooldown_minutes=60,
            confirmed=True,
        )
        reporter.reject(strategy_id="s", profile_id="p", reason="no")
        self.assertEqual(ledger.resolve_calls[0]["status"], "resolved")
        self.assertEqual(ledger.resolve_calls[1]["status"], "rejected")
        self.assertEqual(
            ledger.resolve_calls[0]["approval_request_id"],
            approval_request_id(strategy_id="s", profile_id="p"),
        )

    def test_runtime_sync_creates_attention_alerts_only_for_manual_gates(self) -> None:
        ledger = _AlertLedger()
        now = datetime.now().astimezone()
        context = SimpleNamespace(
            tick_id="t-sync",
            started_at=now,
            config=SimpleNamespace(),
            usage_ledger=ledger,
            state={
                "risk_cfo": {
                    "rejected_candidates": [
                        {
                            "strategy_id": "s",
                            "profile_id": "p",
                            "reason": "paper_promotion_required",
                        }
                    ]
                },
                "live_risk_cfo": {
                    "reason": "live_execution_disabled",
                    "watch_candidates": 1,
                },
            },
        )
        alerts = support._sync_attention_alerts(context)

        self.assertEqual(len(alerts), 2)
        self.assertIn(
            build_event_id(
                event_type="paper_approval_missing",
                strategy_id="s",
                profile_id="p",
                approval_id=approval_request_id(strategy_id="s", profile_id="p"),
            ),
            ledger.alerts,
        )
        self.assertIn(
            build_event_id(event_type="live_execution_requested_while_disabled"),
            ledger.alerts,
        )

        quiet_context = SimpleNamespace(
            tick_id="t-quiet",
            started_at=now,
            config=SimpleNamespace(),
            usage_ledger=_AlertLedger(),
            state={
                "risk_cfo": {"rejected_candidates": []},
                "live_risk_cfo": {"reason": "ok", "watch_candidates": 0},
            },
        )
        quiet_alerts = support._sync_attention_alerts(quiet_context)
        self.assertEqual(quiet_alerts, [])


if __name__ == "__main__":
    unittest.main()
