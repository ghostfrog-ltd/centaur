from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

import app.framework.engine.pipelines as pipelines
from app.framework.runtime.models import TickContext


class FakeLedger:
    def __init__(self, *, recently_sent: bool = False) -> None:
        self.recently_sent = recently_sent
        self.notification_events: list[dict[str, object]] = []
        self.api_events: list[dict[str, object]] = []
        self.notification_checks: list[dict[str, object]] = []

    def notification_recently_sent(self, **kwargs) -> bool:
        self.notification_checks.append(kwargs)
        return self.recently_sent

    def record_notification_event(self, **kwargs) -> None:
        self.notification_events.append(kwargs)

    def record_api_call(self, **kwargs) -> dict[str, object]:
        self.api_events.append(kwargs)
        return {
            "usage_date": kwargs["requested_at"].date().isoformat(),
            "source": kwargs["source"],
            "endpoint": kwargs["endpoint"],
            "request_count": kwargs.get("request_count", 1),
            "success": kwargs.get("success", True),
            "estimated_cost_usd": kwargs.get("estimated_cost_usd", 0.0) or 0.0,
        }


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        slack_alerts_enabled=True,
        slack_webhook_url="https://hooks.slack.test/services/example",
        slack_alert_dedupe_minutes=360,
        slack_request_timeout_seconds=5,
        slack_hourly_status_enabled=False,
        slack_hourly_status_interval_minutes=60,
        live_equity_pdt_review_reminders_enabled=True,
        live_equity_pdt_review_reminder_start_date="2026-06-04",
        live_equity_pdt_review_reminder_interval_minutes=30,
    )


class SlackNotificationTests(unittest.TestCase):
    def test_sends_live_exit_error_and_pdt_guard_alerts(self) -> None:
        sent_messages: list[str] = []
        ledger = FakeLedger()
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 1, 17, 30).astimezone(),
            config=_config(),
            usage_ledger=ledger,
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12"},
                },
                "live_exit_management": {
                    "errors": [
                        {
                            "symbol": "QCOM",
                            "error": "trade denied due to pattern day trading protection",
                        }
                    ]
                },
            },
            metadata={
                "slack_post_message": lambda _webhook, text: sent_messages.append(text)
            },
        )

        result = pipelines.slack_notifications(context)

        self.assertEqual(result["alerts_sent"], 2)
        self.assertEqual(len(sent_messages), 2)
        self.assertTrue(any("Live exit error for QCOM" in item for item in sent_messages))
        self.assertTrue(
            any("equity entries are blocked by PDT guard" in item for item in sent_messages)
        )
        self.assertEqual(len(ledger.notification_events), 2)
        self.assertEqual(len(ledger.api_events), 2)

    def test_dedupes_recently_sent_alerts(self) -> None:
        sent_messages: list[str] = []
        ledger = FakeLedger(recently_sent=True)
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 1, 17, 30).astimezone(),
            config=_config(),
            usage_ledger=ledger,
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12"},
                }
            },
            metadata={
                "slack_post_message": lambda _webhook, text: sent_messages.append(text)
            },
        )

        result = pipelines.slack_notifications(context)

        self.assertEqual(result["alerts_sent"], 0)
        self.assertEqual(result["alerts_deduped"], 1)
        self.assertEqual(sent_messages, [])
        self.assertEqual(ledger.notification_events, [])

    def test_june_four_equity_review_reminder_repeats_every_thirty_minutes(self) -> None:
        sent_messages: list[str] = []
        ledger = FakeLedger()
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 4, 9, 5).astimezone(),
            config=_config(),
            usage_ledger=ledger,
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12"},
                }
            },
            metadata={
                "slack_post_message": lambda _webhook, text: sent_messages.append(text)
            },
        )

        result = pipelines.slack_notifications(context)

        self.assertEqual(result["alerts_sent"], 2)
        self.assertTrue(
            any("Action required: review live equity PDT unblock" in item for item in sent_messages)
        )
        checks_by_key = {
            str(item["event_key"]): item for item in ledger.notification_checks
        }
        review_check = checks_by_key["alpaca_intraday_margin_review_due_20260604"]
        seconds = (context.started_at - review_check["since"]).total_seconds()
        self.assertEqual(seconds, 30 * 60)

    def test_june_four_equity_review_reminder_can_be_turned_off(self) -> None:
        sent_messages: list[str] = []
        ledger = FakeLedger()
        config = _config()
        config.live_equity_pdt_review_reminders_enabled = False
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 4, 9, 5).astimezone(),
            config=config,
            usage_ledger=ledger,
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12"},
                }
            },
            metadata={
                "slack_post_message": lambda _webhook, text: sent_messages.append(text)
            },
        )

        result = pipelines.slack_notifications(context)

        self.assertEqual(result["alerts_sent"], 1)
        self.assertFalse(
            any("Action required: review live equity PDT unblock" in item for item in sent_messages)
        )

    def test_hourly_status_sends_liveness_summary_with_hour_dedupe(self) -> None:
        sent_messages: list[str] = []
        ledger = FakeLedger()
        config = _config()
        config.slack_hourly_status_enabled = True
        context = TickContext(
            tick_id="tick-123",
            started_at=datetime(2026, 6, 3, 13, 5).astimezone(),
            config=config,
            usage_ledger=ledger,
            state={
                "market_gate": {
                    "reason": "crypto_only_window",
                    "equity_scan_ready": False,
                    "crypto_scan_ready": True,
                },
                "risk_cfo": {
                    "decision": "hold",
                    "reason": "no_shadow_proposals",
                    "open_positions": 8,
                    "open_orders": 0,
                    "available_slots": 2,
                },
                "execution": {
                    "orders_submitted": 0,
                    "execution_status": "idle",
                },
                "daily_protection": {
                    "system_status": "active",
                    "equity_drawdown_usd": 0.25,
                    "max_daily_drawdown_usd": 2.0,
                },
                "alpaca_account": {
                    "summary": {
                        "equity": 100010.13,
                        "open_position_unrealized_pl": -1.64,
                    }
                },
            },
            metadata={
                "slack_post_message": lambda _webhook, text: sent_messages.append(text)
            },
        )

        result = pipelines.slack_notifications(context)

        self.assertEqual(result["alerts_sent"], 1)
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Centaur hourly status", sent_messages[0])
        self.assertIn("tick=tick-123", sent_messages[0])
        self.assertIn("orders_submitted=0", sent_messages[0])
        self.assertEqual(ledger.notification_events[0]["event_key"], "centaur_hourly_status")
        seconds = (context.started_at - ledger.notification_checks[0]["since"]).total_seconds()
        self.assertEqual(seconds, 60 * 60)


if __name__ == "__main__":
    unittest.main()
