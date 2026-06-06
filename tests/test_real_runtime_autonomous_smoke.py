from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

import app.framework.runtime.autonomous_learning as autonomous_learning_module
import app.framework.runtime.attention_alerts as attention_alerts_module
from app.framework.runtime.attention_alerts import approval_request_id, build_event_id
from app.framework.runtime.models import TickContext
import app.framework.engine.pipelines as pipelines_module
from app.framework.engine.pipelines import build_default_pipeline


@dataclass(frozen=True)
class _SmokeProfile:
    strategy_id: str
    profile_id: str
    asset_classes: tuple[str, ...]
    parameters: dict[str, object] = field(
        default_factory=lambda: {"research_only": True}
    )


class _SmokeStrategy:
    def __init__(self, profiles: list[_SmokeProfile]) -> None:
        self._profiles = list(profiles)

    def build_profiles(self, _config) -> list[_SmokeProfile]:
        return list(self._profiles)


class _SmokeLedger:
    def __init__(self) -> None:
        self.tick_runs: list[object] = []
        self.decisions: list[dict[str, object]] = []
        self.promotion_updates: list[dict[str, object]] = []
        self.alerts: dict[str, dict[str, object]] = {}
        self.notification_events: list[dict[str, object]] = []
        self.api_calls: list[dict[str, object]] = []
        self.backend = "sqlite"
        self.backend_detail = "test"
        self.paper_trade_orders_recorded = 0
        self.live_trade_orders_recorded = 0

    def record_tick_run(self, report: object) -> bool:
        self.tick_runs.append(report)
        return True

    def record_research_cycle_decisions(self, *, decisions: list[dict[str, object]]) -> int:
        self.decisions.extend(decisions)
        return len(decisions)

    def record_strategy_promotion_evaluation(self, **kwargs) -> None:
        self.promotion_updates.append(kwargs)

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str):
        for row in reversed(self.promotion_updates):
            if (
                str(row.get("strategy_id", "")) == strategy_id
                and str(row.get("profile_id", "")) == profile_id
            ):
                return {
                    "strategy_id": strategy_id,
                    "profile_id": profile_id,
                    "stage": row.get("stage", "research_only"),
                    "paper_approved": 0,
                    "live_approved": 0,
                    "paper_execution_profile": 0,
                    "research_only_profile": 1,
                    "max_paper_notional_usd": 0.0,
                    "max_open_trades": 0,
                    "cooldown_minutes": 0,
                    "rejected": 0,
                }
        return None

    def get_attention_alert(self, *, event_id: str):
        return self.alerts.get(event_id)

    def upsert_attention_alert(self, *, alert: dict[str, object]) -> None:
        existing = self.alerts.get(str(alert["event_id"]), {})
        normalized = {**existing, **alert}
        normalized["evidence_summary_json"] = dict(alert.get("evidence_summary", {}) or {})
        self.alerts[str(alert["event_id"])] = normalized

    def list_due_attention_alerts(self, *, due_at: datetime):
        return [
            alert
            for alert in self.alerts.values()
            if bool(alert.get("requires_attention"))
            and str(alert.get("attention_status", "")) == "open"
            and isinstance(alert.get("next_slack_due_at"), datetime)
            and alert["next_slack_due_at"] <= due_at
        ]

    def mark_attention_alert_sent(
        self,
        *,
        event_id: str,
        sent_at: datetime,
        next_due_at: datetime | None,
        slack_send_count: int,
        slack_error: str = "",
    ) -> None:
        row = self.alerts[event_id]
        row["updated_at"] = sent_at
        row["first_slack_sent_at"] = row.get("first_slack_sent_at") or sent_at
        row["last_slack_sent_at"] = sent_at
        row["next_slack_due_at"] = next_due_at
        row["slack_send_count"] = slack_send_count
        row["slack_sent"] = True
        row["slack_error"] = slack_error

    def record_notification_event(self, **kwargs) -> None:
        self.notification_events.append(kwargs)

    def notification_recently_sent(self, **_kwargs) -> bool:
        return False

    def record_api_call(self, **kwargs):
        self.api_calls.append(kwargs)
        return kwargs


class _RuntimeSmokeResearchRunner:
    last_strategy_pairs: list[tuple[str, str]] = []
    last_paper_sim_eligibility_pairs: list[tuple[str, str]] = []

    def __init__(self, *, config=None, usage_ledger=None) -> None:
        self.config = config
        self.usage_ledger = usage_ledger

    def run(self):
        started_at = datetime.now().astimezone()
        cycle_id = "researchcycle-runtime-smoke"
        decisions: list[dict[str, object]] = []
        for index, (strategy_id, profile_id) in enumerate(self.last_strategy_pairs, start=1):
            recommendation = "research_only"
            outcomes_recorded = 0
            blocker_reasons = [
                "paper_allocation_excludes_backtest_evidence",
                "live_allocation_excludes_backtest_evidence",
            ]
            if index == 1:
                recommendation = "paper_sim_candidate"
                outcomes_recorded = 16
            elif index == 2:
                recommendation = "promising_research"
                blocker_reasons.append("needs_more_replay_evidence_first")
            elif index == 3:
                recommendation = "rejected_research"
                blocker_reasons.append("net_return_below_threshold")
            else:
                blocker_reasons.append("needs_more_replay_evidence_first")
            decisions.append(
                {
                    "cycle_id": cycle_id,
                    "created_at": started_at,
                    "strategy_id": strategy_id,
                    "profile_id": profile_id,
                    "asset_class": "crypto" if "crypto" in strategy_id else "equity",
                    "symbol_universe": ["AVAX/USD", "SOL/USD"] if "crypto" in strategy_id else ["AAPL"],
                    "timeframe": "15Min",
                    "replay_window_start": started_at - timedelta(days=5),
                    "replay_window_end": started_at,
                    "windows_tested_count": 4,
                    "candidates_evaluated": 32,
                    "signals_generated": max(1, outcomes_recorded),
                    "proposals_created": max(8, outcomes_recorded),
                    "outcomes_recorded": outcomes_recorded,
                    "gross_return_summary": {"avg_pct": 0.24 if outcomes_recorded else 0.01},
                    "estimated_cost_assumptions": {
                        "simulated_crypto_fee_bps": 10.0,
                        "simulated_crypto_slippage_bps": 8.0,
                        "simulated_crypto_spread_bps": 12.0,
                    },
                    "net_return_summary": {
                        "avg_pct": 0.18 if outcomes_recorded else 0.01,
                        "avg_max_adverse_excursion_pct": -0.09 if outcomes_recorded else -0.03,
                    },
                    "win_rate_summary": {"avg": 0.62 if outcomes_recorded else 0.5},
                    "sample_size_status": "sufficient" if outcomes_recorded else "insufficient",
                    "data_integrity_status": "pass",
                    "recommendation": recommendation,
                    "blocker_reasons": blocker_reasons,
                    "source_environment": "backtest",
                    "execution_provider": "simulator",
                    "paper_fitness_includes_backtest": False,
                    "live_fitness_includes_backtest": False,
                    "research_only_profile": True,
                }
            )
        type(self).last_paper_sim_eligibility_pairs = [
            (str(item["strategy_id"]), str(item["profile_id"])) for item in decisions
        ]
        self.usage_ledger.record_research_cycle_decisions(decisions=decisions)
        for decision in decisions:
            stage = str(decision["recommendation"])
            if stage == "paper_sim_candidate" and int(decision["outcomes_recorded"]) > 0:
                stage = "paper_candidate"
                approval_id = approval_request_id(
                    strategy_id=str(decision["strategy_id"]),
                    profile_id=str(decision["profile_id"]),
                )
                self.usage_ledger.upsert_attention_alert(
                    alert={
                        "event_id": build_event_id(
                            event_type="paper_candidate",
                            strategy_id=str(decision["strategy_id"]),
                            profile_id=str(decision["profile_id"]),
                            approval_id=approval_id,
                        ),
                        "created_at": started_at,
                        "updated_at": started_at,
                        "severity": "warning",
                        "event_type": "paper_candidate",
                        "title": "Broker paper approval required",
                        "message": "Broker paper remains blocked until manual approval.",
                        "evidence_summary": {"stage": "paper_candidate"},
                        "recommended_action": "Approve or reject the broker paper request.",
                        "requires_attention": True,
                        "attention_status": "open",
                        "slack_sent": False,
                        "slack_send_count": 0,
                        "next_slack_due_at": started_at,
                        "strategy_id": str(decision["strategy_id"]),
                        "profile_id": str(decision["profile_id"]),
                        "approval_request_id": approval_id,
                    }
                )
            elif stage == "rejected_research":
                stage = "rejected"
            self.usage_ledger.record_strategy_promotion_evaluation(
                strategy_id=decision["strategy_id"],
                profile_id=decision["profile_id"],
                stage=stage,
                recommendation=decision["recommendation"],
                blocker_reasons_json=list(decision["blocker_reasons"]),
                paper_approved=0,
                live_approved=0,
            )
        state_snapshot = {
            "research_cycle": {
                "status": "ok",
                "timeframes_used": ["15Min"],
                "timeframes_skipped": [{"timeframe": "1Min", "reason": "timeframe_not_present_in_historical_store"}],
                "decisions": decisions,
                "live_execution_remains_disabled": True,
            }
        }
        return SimpleNamespace(
            tick_id=cycle_id,
            state_snapshot=state_snapshot,
        )


class RealRuntimeAutonomousSmokeTests(unittest.TestCase):
    def test_real_heartbeat_path_runs_all_profiles_and_queues_slack_without_orders(self) -> None:
        strategy_profiles = [
            _SmokeProfile("crypto_pullback.downside_reversal_watch", "downside_reversal_watch", ("crypto",)),
            _SmokeProfile("crypto_pullback.downside_continuation_watch", "downside_continuation_watch", ("crypto",)),
            _SmokeProfile("crypto_pullback.extreme_drop_reversal_watch", "extreme_drop_reversal_watch", ("crypto",)),
            _SmokeProfile("mean_reversion.snapback", "snapback", ("equity",)),
            _SmokeProfile("mean_reversion.pullback", "pullback", ("equity",)),
            _SmokeProfile("trend_follow.breakout", "breakout", ("equity",)),
            _SmokeProfile("trend_follow.continuation", "continuation", ("equity",)),
            _SmokeProfile("volatility.reversal", "reversal", ("crypto",)),
            _SmokeProfile("volatility.compression_break", "compression_break", ("crypto",)),
        ]
        smoke_strategies = [_SmokeStrategy([profile]) for profile in strategy_profiles]
        _RuntimeSmokeResearchRunner.last_strategy_pairs = [
            (profile.strategy_id, profile.profile_id) for profile in strategy_profiles
        ]
        _RuntimeSmokeResearchRunner.last_paper_sim_eligibility_pairs = []

        original_registry_builder = autonomous_learning_module.build_strategy_registry
        original_runner = autonomous_learning_module.ResearchCycleRunner
        original_slack_client = pipelines_module.SlackWebhookClient
        original_attention_slack_client = attention_alerts_module.SlackWebhookClient
        autonomous_learning_module.build_strategy_registry = lambda: smoke_strategies
        autonomous_learning_module.ResearchCycleRunner = _RuntimeSmokeResearchRunner
        posted_messages: list[str] = []

        class _FakeSlackClient:
            def __init__(self, *, webhook_url: str, timeout_seconds: int) -> None:
                _ = (webhook_url, timeout_seconds)

            def post_message(self, text: str) -> None:
                posted_messages.append(text)

        pipelines_module.SlackWebhookClient = _FakeSlackClient
        attention_alerts_module.SlackWebhookClient = _FakeSlackClient
        try:
            steps = build_default_pipeline()
            control_step = steps[0]
            slack_step = steps[-1]
            ledger = _SmokeLedger()
            context = TickContext(
                tick_id="tick-runtime-smoke",
                started_at=datetime.now().astimezone(),
                config=SimpleNamespace(
                    research_cycle_enabled=True,
                    include_backtest_evidence_in_paper_fitness=False,
                    include_backtest_evidence_in_live_fitness=False,
                    slack_alerts_enabled=False,
                    slack_webhook_url="https://hooks.slack.test/services/example",
                    slack_attention_repeat_enabled=True,
                    slack_attention_repeat_minutes=15,
                    slack_attention_max_repeats=0,
                    slack_request_timeout_seconds=5,
                ),
                usage_ledger=ledger,
                state={},
                metadata={"slack_post_message": lambda _webhook, text: posted_messages.append(text)},
            )

            control_result = control_step.runner(context)

            self.assertEqual(control_step.name, "control.heartbeat")
            self.assertEqual(control_result["status"], "alive")
            autonomous_state = context.state["autonomous_learning"]
            self.assertEqual(autonomous_state["status"], "ok")
            self.assertTrue(autonomous_state["triggered"])
            self.assertEqual(int(autonomous_state["strategy_profiles_discovered"]), 9)
            self.assertEqual(int(autonomous_state["strategy_profiles_evaluated"]), 9)
            self.assertEqual(int(autonomous_state["strategy_profiles_skipped"]), 0)
            self.assertEqual(len(ledger.decisions), 9)
            self.assertEqual(len(_RuntimeSmokeResearchRunner.last_paper_sim_eligibility_pairs), 9)
            self.assertTrue(
                any(
                    str(item.get("stage", "")) == "paper_candidate"
                    for item in ledger.promotion_updates
                )
            )
            self.assertEqual(autonomous_state["broker_orders_created"], 0)
            self.assertEqual(autonomous_state["live_orders_created"], 0)
            self.assertEqual(autonomous_state["auto_paper_approved"], 0)
            self.assertEqual(autonomous_state["auto_live_approved"], 0)
            self.assertTrue(
                any(
                    item.get("paper_candidate_alert_open")
                    for item in autonomous_state.get("strategy_profiles", [])
                )
            )

            context.config.slack_alerts_enabled = True
            context.started_at = context.started_at + timedelta(minutes=1)
            slack_result = slack_step.runner(context)

            self.assertEqual(slack_step.name, "notifications.slack")
            self.assertGreaterEqual(int(slack_result.get("attention_alerts_sent", 0) or 0), 1)
            self.assertTrue(posted_messages)
            self.assertTrue(any("ATTENTION REQUIRED" in message for message in posted_messages))
            self.assertTrue(
                any(
                    "Broker paper: BLOCKED until manual approval" in message
                    for message in posted_messages
                )
            )
            self.assertEqual(ledger.paper_trade_orders_recorded, 0)
            self.assertEqual(ledger.live_trade_orders_recorded, 0)
        finally:
            autonomous_learning_module.build_strategy_registry = original_registry_builder
            autonomous_learning_module.ResearchCycleRunner = original_runner
            pipelines_module.SlackWebhookClient = original_slack_client
            attention_alerts_module.SlackWebhookClient = original_attention_slack_client


if __name__ == "__main__":
    unittest.main()
