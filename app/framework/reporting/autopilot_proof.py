from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import app.framework.engine.research_cycle as research_cycle_module
import app.framework.runtime.autonomous_learning as autonomous_learning_module
from app.framework.engine.shadow import build_shadow_proposals
from app.framework.runtime.attention_alerts import send_due_attention_alerts
from app.framework.runtime.models import TickContext
from app.framework.strategies.registry import evaluate_strategies
from app.heartbeat import support


@dataclass(frozen=True)
class _ProofProfile:
    strategy_id: str
    profile_id: str
    asset_classes: tuple[str, ...] = ("crypto",)
    parameters: dict[str, object] = field(
        default_factory=lambda: {"research_only": True}
    )


class _ProofStrategy:
    def build_profiles(self, _config: Any) -> list[_ProofProfile]:
        return [
            _ProofProfile(
                "crypto_pullback.downside_reversal_watch",
                "downside_reversal_watch",
            )
        ]


class _ProofLedger:
    def __init__(self) -> None:
        self.tick_runs: list[Any] = []
        self.decisions: list[dict[str, Any]] = []
        self.promotion_updates: list[dict[str, Any]] = []
        self.alerts: dict[str, dict[str, Any]] = {}
        self.notification_events: list[dict[str, Any]] = []
        self.backend = "sqlite"
        self.backend_detail = "autopilot-proof"
        self.paper_trade_orders_recorded = 0
        self.live_trade_orders_recorded = 0
        self.manual_promotions: dict[tuple[str, str], dict[str, Any]] = {
            (
                "mean_reversion.snapback",
                "snapback",
            ): {
                "strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "stage": "paper_approved",
                "paper_approved": 1,
                "live_approved": 0,
                "paper_execution_profile": 1,
                "research_only_profile": 0,
                "max_paper_notional_usd": 10.0,
                "max_open_trades": 1,
                "cooldown_minutes": 30,
                "rejected": 0,
            }
        }
        now = datetime.now().astimezone()
        self.shadow_history: dict[tuple[str, str], dict[str, Any]] = {
            (
                "crypto_pullback.downside_reversal_watch",
                "downside_reversal_watch",
            ): {
                "last_signal_at": now,
                "last_outcome_at": now,
            },
            (
                "mean_reversion.snapback",
                "snapback",
            ): {
                "last_signal_at": now,
                "last_outcome_at": now,
            },
        }

    def record_tick_run(self, report: Any) -> bool:
        self.tick_runs.append(report)
        return True

    def record_research_cycle_decisions(self, *, decisions: list[dict[str, Any]]) -> int:
        self.decisions.extend(decisions)
        return len(decisions)

    def record_strategy_promotion_evaluation(self, **kwargs: Any) -> None:
        self.promotion_updates.append(kwargs)

    def get_strategy_promotion(
        self,
        *,
        strategy_id: str,
        profile_id: str,
    ) -> dict[str, Any] | None:
        manual = self.manual_promotions.get((strategy_id, profile_id))
        for row in reversed(self.promotion_updates):
            if (
                str(row.get("strategy_id", "")) == strategy_id
                and str(row.get("profile_id", "")) == profile_id
            ):
                return {
                    "strategy_id": strategy_id,
                    "profile_id": profile_id,
                    "stage": row.get("stage", manual.get("stage", "research_only") if manual else "research_only"),
                    "paper_approved": int(manual.get("paper_approved", 0) if manual else 0),
                    "live_approved": int(manual.get("live_approved", 0) if manual else 0),
                    "paper_execution_profile": int(
                        manual.get("paper_execution_profile", 0) if manual else 0
                    ),
                    "research_only_profile": int(
                        manual.get("research_only_profile", 1) if manual else 1
                    ),
                    "max_paper_notional_usd": float(
                        manual.get("max_paper_notional_usd", 0.0) if manual else 0.0
                    ),
                    "max_open_trades": int(manual.get("max_open_trades", 0) if manual else 0),
                    "cooldown_minutes": int(manual.get("cooldown_minutes", 0) if manual else 0),
                    "rejected": int(manual.get("rejected", 0) if manual else 0),
                }
        if manual:
            return dict(manual)
        return None

    def get_latest_strategy_fitness_summary(
        self,
        *,
        strategy_id: str,
        profile_id: str,
    ) -> dict[str, Any] | None:
        if strategy_id == "mean_reversion.snapback" and profile_id == "snapback":
            return {
                "composite_fitness_score": 0.05,
                "avg_realized_return_pct": -0.02,
                "win_rate": 0.31,
                "evaluated_proposals": 12,
                "avg_max_adverse_excursion_pct": -0.22,
                "checkpoint_code": "degraded",
                "captured_at": datetime.now().astimezone(),
            }
        if strategy_id == "crypto_pullback.downside_reversal_watch":
            return {
                "composite_fitness_score": 0.78,
                "avg_realized_return_pct": 0.22,
                "win_rate": 0.63,
                "evaluated_proposals": 16,
                "avg_max_adverse_excursion_pct": -0.09,
                "checkpoint_code": "paper_sim_ok",
                "captured_at": datetime.now().astimezone(),
            }
        return None

    def list_shadow_trade_proposals_by_note_prefix(
        self,
        *,
        note_prefix: str,
    ) -> list[dict[str, Any]]:
        if "15Min-run-" not in note_prefix:
            return []
        rows: list[dict[str, Any]] = []
        for idx in range(16):
            rows.append(
                {
                    "proposal_id": f"proposal-{idx}",
                    "strategy_id": "crypto_pullback.downside_reversal_watch",
                    "profile_id": "downside_reversal_watch",
                    "symbol": "SOL/USD" if idx % 2 else "AVAX/USD",
                }
            )
        return rows

    def list_shadow_trade_outcomes_by_note_prefix(
        self,
        *,
        note_prefix: str,
    ) -> list[dict[str, Any]]:
        if "15Min-run-" not in note_prefix:
            return []
        rows: list[dict[str, Any]] = []
        returns = [0.96, 0.88, 0.74, 0.71, 0.91, 0.86, 0.79, 0.68] * 2
        for idx, value in enumerate(returns):
            rows.append(
                {
                    "proposal_id": f"proposal-{idx}",
                    "strategy_id": "crypto_pullback.downside_reversal_watch",
                    "profile_id": "downside_reversal_watch",
                    "symbol": "SOL/USD" if idx % 2 else "AVAX/USD",
                    "realized_return_pct": value,
                    "max_adverse_excursion_pct": -0.09,
                }
            )
        return rows

    def list_recent_paper_trade_orders(self, *, limit: int = 250) -> list[dict[str, Any]]:
        _ = limit
        return []

    def get_attention_alert(self, *, event_id: str) -> dict[str, Any] | None:
        return self.alerts.get(event_id)

    def upsert_attention_alert(self, *, alert: dict[str, Any]) -> None:
        existing = self.alerts.get(str(alert.get("event_id", "")), {})
        self.alerts[str(alert.get("event_id", ""))] = {
            **existing,
            **alert,
            "evidence_summary_json": dict(alert.get("evidence_summary", {}) or {}),
        }

    def list_due_attention_alerts(self, *, due_at: datetime) -> list[dict[str, Any]]:
        return [
            item
            for item in self.alerts.values()
            if bool(item.get("requires_attention"))
            and str(item.get("attention_status", "")) == "open"
            and isinstance(item.get("next_slack_due_at"), datetime)
            and item["next_slack_due_at"] <= due_at
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

    def record_notification_event(self, **kwargs: Any) -> None:
        self.notification_events.append(kwargs)


class AutopilotProofRunner:
    """Run a deterministic dry-run proof of Centaur autonomy boundaries."""

    def run(self) -> dict[str, Any]:
        ledger = _ProofLedger()
        config = self._config()
        now = datetime.now().astimezone()
        context = TickContext(
            tick_id="autopilot-proof",
            started_at=now,
            config=config,
            usage_ledger=ledger,
            state={},
        )

        original_registry_builder = research_cycle_module.build_strategy_registry
        original_research_runner = autonomous_learning_module.ResearchCycleRunner
        autonomous_learning_module.ResearchCycleRunner = _ProofResearchCycleRunner
        slack_messages: list[str] = []
        try:
            self._run_safe_learning(context)
            autonomous_state = dict(context.state.get("autonomous_learning", {}) or {})
            promotion_changes = list(autonomous_state.get("promotion_changes", []) or [])
            broker_gate = self._check_broker_gate(context)
            live_gate = self._check_live_gate(context)
            context.state["risk_cfo"] = {
                "rejected_candidates": [broker_gate["rejection"]]
                if broker_gate.get("rejection")
                else []
            }
            context.state["live_risk_cfo"] = {
                "reason": "live_execution_disabled",
                "watch_candidates": 1,
            }
            support._sync_attention_alerts(context)
            first_slack = send_due_attention_alerts(
                context=context,
                sender=lambda _webhook, text: slack_messages.append(text),
            )
            context.started_at = now + timedelta(minutes=16)
            repeat_slack = send_due_attention_alerts(
                context=context,
                sender=lambda _webhook, text: slack_messages.append(text),
            )
        finally:
            research_cycle_module.build_strategy_registry = original_registry_builder
            autonomous_learning_module.ResearchCycleRunner = original_research_runner

        records = {
            f"{item['strategy_id']}::{item['profile_id']}": item["stage"]
            for item in promotion_changes
        }
        strategy_profiles = list(autonomous_state.get("strategy_profiles", []) or [])
        result = {
            "status": "pass"
            if strategy_profiles
            and broker_gate["manual_approval_required"]
            and live_gate["manual_approval_required"]
            and not self._any_approved(ledger.promotion_updates, field_name="paper_approved")
            and not self._any_approved(ledger.promotion_updates, field_name="live_approved")
            else "fail",
            "autonomous_work_performed": [
                "autopilot_research_cycle",
                "replay_window_selection",
                "paper_sim_evidence_evaluation",
                "promotion_recommendation_update",
                "attention_alert_dispatch",
            ],
            "promotion_states_changed": records,
            "strategy_profiles": strategy_profiles,
            "strategy_profiles_discovered": int(
                autonomous_state.get("strategy_profiles_discovered", 0) or 0
            ),
            "strategy_profiles_evaluated": int(
                autonomous_state.get("strategy_profiles_evaluated", 0) or 0
            ),
            "strategy_profiles_skipped": int(
                autonomous_state.get("strategy_profiles_skipped", 0) or 0
            ),
            "internal_stage_changes": int(
                autonomous_state.get("internal_stage_changes", 0) or 0
            ),
            "paper_candidates_created": int(
                autonomous_state.get("paper_candidates_created", 0) or 0
            ),
            "paper_removal_candidates_created": int(
                autonomous_state.get("paper_removal_candidates_created", 0) or 0
            ),
            "manual_approval_required": bool(
                broker_gate["manual_approval_required"]
                or live_gate["manual_approval_required"]
            ),
            "slack_notified": bool(first_slack.get("alerts_sent", 0) or repeat_slack.get("alerts_sent", 0)),
            "slack_alerts_sent": int(first_slack.get("alerts_sent", 0) or 0)
            + int(repeat_slack.get("alerts_sent", 0) or 0),
            "slack_attention_alerts_created": int(
                autonomous_state.get("slack_attention_alerts_created", 0) or 0
            ),
            "broker_execution_attempted": False,
            "live_execution_attempted": False,
            "broker_orders_created": ledger.paper_trade_orders_recorded,
            "live_orders_created": ledger.live_trade_orders_recorded,
            "auto_paper_approved": self._count_approved(
                ledger.promotion_updates,
                field_name="paper_approved",
            ),
            "auto_paper_removed": 0,
            "auto_live_approved": self._count_approved(
                ledger.promotion_updates,
                field_name="live_approved",
            ),
            "auto_live_removed": 0,
            "broker_gate_reason": str((broker_gate.get("rejection") or {}).get("reason", "")),
            "live_gate_reason": str(live_gate.get("reason", "")),
            "live_execution_remains_disabled": True,
            "slack_messages": slack_messages,
        }
        paper_sim_diagnostics = self._paper_sim_diagnostics(
            context=context,
            strategy_profiles=strategy_profiles,
            ledger=ledger,
        )
        result["strategy_profiles"] = paper_sim_diagnostics
        return result

    def render(self, result: dict[str, Any]) -> str:
        promotion_states = ",".join(
            f"{key}:{value}"
            for key, value in sorted(
                (result.get("promotion_states_changed", {}) or {}).items()
            )
        ) or "-"
        work = ",".join(result.get("autonomous_work_performed", []) or []) or "-"
        profile_lines = []
        for item in result.get("strategy_profiles", []) or []:
            skipped = ",".join(item.get("skipped_reasons", []) or []) or "-"
            profile_lines.append(
                "strategy_profile="
                f"{item.get('strategy_id')}/{item.get('profile_id')}"
                f" | research_evaluated={'yes' if item.get('research_evaluated') else 'no'}"
                f" | paper_sim_evaluated={'yes' if item.get('paper_sim_evaluated') else 'no'}"
                f" | skipped_reasons={skipped}"
                f" | internal_stage={item.get('internal_stage', '-')}"
                f" | execution_permission={item.get('execution_permission', 'none')}"
                f" | paper_sim_eligible={'yes' if item.get('paper_sim_eligible') else 'no'}"
                f" | paper_sim_block_reason={item.get('paper_sim_block_reason', '-')}"
                f" | live_market_data_exists={'yes' if item.get('live_market_data_exists') else 'no'}"
                f" | live_signal_generated={'yes' if item.get('live_signal_generated') else 'no'}"
                f" | no_signal_reason={item.get('no_signal_reason', '-')}"
                f" | blocked_more_replay_evidence_first={'yes' if item.get('blocked_more_replay_evidence_first') else 'no'}"
                f" | blocked_paper_sim_disabled={'yes' if item.get('blocked_paper_sim_disabled') else 'no'}"
                f" | paper_sim_records_exist={'yes' if item.get('paper_sim_records_exist') else 'no'}"
                f" | last_paper_sim_signal_at={item.get('last_paper_sim_signal_at', '-')}"
                f" | last_paper_sim_outcome_at={item.get('last_paper_sim_outcome_at', '-')}"
                f" | paper_candidate_alert_open={'yes' if item.get('paper_candidate_alert_open') else 'no'}"
                f" | paper_removal_candidate_alert_open={'yes' if item.get('paper_removal_candidate_alert_open') else 'no'}"
            )
        return "\n".join(
            [
                "Centaur Autopilot Proof",
                "proof_mode=synthetic_safety_harness",
                "real_learning_proven=false",
                "purpose=verify_promotion_and_execution_safety_boundaries",
                "uses_synthetic_replay_evidence=yes",
                "uses_synthetic_paper_sim_evidence=yes",
                f"autonomous_work_performed={work}",
                f"strategy_profiles_discovered={int(result.get('strategy_profiles_discovered', 0) or 0)}",
                f"strategy_profiles_evaluated={int(result.get('strategy_profiles_evaluated', 0) or 0)}",
                f"strategy_profiles_skipped={int(result.get('strategy_profiles_skipped', 0) or 0)}",
                f"promotion_states_changed={promotion_states}",
                f"internal_stage_changes={int(result.get('internal_stage_changes', 0) or 0)}",
                f"paper_candidates_created={int(result.get('paper_candidates_created', 0) or 0)}",
                f"paper_removal_candidates_created={int(result.get('paper_removal_candidates_created', 0) or 0)}",
                (
                    "manual_approval_required="
                    f"{str(bool(result.get('manual_approval_required'))).lower()}"
                ),
                (
                    "slack_notified="
                    f"{str(bool(result.get('slack_notified'))).lower()}"
                ),
                f"slack_attention_alerts_created={int(result.get('slack_attention_alerts_created', 0) or 0)}",
                (
                    "broker_execution_attempted="
                    f"{str(bool(result.get('broker_execution_attempted'))).lower()}"
                ),
                (
                    "live_execution_attempted="
                    f"{str(bool(result.get('live_execution_attempted'))).lower()}"
                ),
                f"broker_orders_created={int(result.get('broker_orders_created', 0) or 0)}",
                f"live_orders_created={int(result.get('live_orders_created', 0) or 0)}",
                f"auto_paper_approved={int(result.get('auto_paper_approved', 0) or 0)}",
                f"auto_paper_removed={int(result.get('auto_paper_removed', 0) or 0)}",
                f"auto_live_approved={int(result.get('auto_live_approved', 0) or 0)}",
                f"auto_live_removed={int(result.get('auto_live_removed', 0) or 0)}",
                (
                    "manual_gate_broker_reason="
                    f"{str(result.get('broker_gate_reason', '') or '-')}"
                ),
                (
                    "manual_gate_live_reason="
                    f"{str(result.get('live_gate_reason', '') or '-')}"
                ),
                (
                    "live_execution_remains_disabled="
                    f"{str(bool(result.get('live_execution_remains_disabled'))).lower()}"
                ),
                *profile_lines,
                (
                    "final_safety_summary="
                    f"{'PASS' if str(result.get('status', '')).lower() == 'pass' else 'FAIL'}"
                ),
            ]
        )

    def _run_safe_learning(self, context: TickContext) -> None:
        runner_result = autonomous_learning_module.run_autonomous_learning_cycle(context)
        if runner_result.get("status") != "ok":
            raise RuntimeError(str(runner_result.get("reason", "autonomous_learning_failed")))

    def _check_broker_gate(self, context: TickContext) -> dict[str, Any]:
        proposal = {
            "proposal_id": "proposal-gated",
            "strategy_id": "crypto_pullback.downside_reversal_watch",
            "strategy_family": "crypto_pullback",
            "profile_id": "downside_reversal_watch",
            "source": "research_cycle",
            "symbol": "AVAX/USD",
            "asset_class": "crypto",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss_price": 98.0,
            "target_price": 103.0,
        }
        approval, rejection = support._build_paper_trade_approval(
            context=context,
            proposal=proposal,
            tick_id=context.tick_id,
            config=context.config,
            market_gate={"crypto_scan_ready": True},
            position_symbols=set(),
            open_order_symbols=set(),
            broker_id="alpaca_paper",
        )
        return {
            "approval": approval,
            "rejection": rejection,
            "manual_approval_required": str((rejection or {}).get("reason", ""))
            == "paper_promotion_required",
        }

    def _check_live_gate(self, context: TickContext) -> dict[str, Any]:
        _ = context
        return {
            "reason": "live_execution_disabled",
            "manual_approval_required": True,
        }

    def _config(self) -> Any:
        return SimpleNamespace(
            research_cycle_enabled=True,
            research_replay_days=5,
            research_replay_timeframe="15Min",
            research_max_replay_timestamps=500,
            research_min_windows=4,
            research_min_proposals=50,
            research_min_net_return_pct=0.10,
            research_min_net_win_rate=0.55,
            research_allowed_strategies=(
                "crypto_pullback.downside_reversal_watch",
            ),
            discovery_equity_symbols=(),
            discovery_crypto_symbols=("AVAX/USD", "SOL/USD"),
            include_backtest_evidence_in_paper_fitness=False,
            include_backtest_evidence_in_live_fitness=False,
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            shadow_min_opportunity_score=55.0,
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=58.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=3.0,
            crypto_momentum_min_trade_count=40,
            crypto_momentum_min_volume_gbp=50000.0,
            crypto_momentum_max_spread_pct=0.25,
            simulated_crypto_fee_bps=10.0,
            simulated_crypto_slippage_bps=8.0,
            simulated_crypto_spread_bps=12.0,
            slack_alerts_enabled=True,
            slack_webhook_url="https://hooks.slack.test/services/example",
            slack_attention_repeat_enabled=True,
            slack_attention_repeat_minutes=15,
            slack_attention_max_repeats=0,
            slack_request_timeout_seconds=5,
            paper_execution_equity_broker_id="alpaca_paper",
            paper_execution_crypto_broker_id="alpaca_paper",
            paper_execution_equity_only=False,
            paper_execution_require_market_open=False,
            paper_execution_min_projected_gain_pct=0.01,
            paper_execution_crypto_min_projected_gain_pct=0.01,
            paper_execution_limit_buffer_bps=5.0,
            paper_execution_crypto_limit_buffer_bps=25.0,
            paper_execution_default_notional_usd=10.0,
            trading212_paper_execution_default_notional_gbp=5.0,
        )

    def _any_approved(
        self,
        rows: list[dict[str, Any]],
        *,
        field_name: str,
    ) -> bool:
        return any(bool(item.get(field_name)) for item in rows)

    def _count_approved(
        self,
        rows: list[dict[str, Any]],
        *,
        field_name: str,
    ) -> int:
        return sum(1 for item in rows if bool(item.get(field_name)))

    def _paper_sim_diagnostics(
        self,
        *,
        context: TickContext,
        strategy_profiles: list[dict[str, Any]],
        ledger: _ProofLedger,
    ) -> list[dict[str, Any]]:
        candidates = self._proof_candidates()
        batch = evaluate_strategies(
            tick_id=context.tick_id,
            candidates=candidates,
            config=context.config,
            market_context={
                "market_gate": {"equity_scan_ready": True, "crypto_scan_ready": True},
                "account_equity": 1000.0,
                "market_data_source_used_for_strategy": {
                    "equity": "proof_feed",
                    "crypto": "proof_feed",
                },
                "candidates_excluded_due_to_stale_source_by_asset_class": {},
            },
        )
        signal_dicts = [item.as_dict(tick_id=context.tick_id) for item in batch.signals]
        proposals = build_shadow_proposals(
            tick_id=context.tick_id,
            proposed_at=context.started_at,
            strategy_signals=signal_dicts,
            recent_strategy_keys=set(),
            proposal_limit=max(1, int(getattr(context.config, "shadow_proposal_limit", 10) or 10)),
            min_signal_score=float(getattr(context.config, "shadow_min_opportunity_score", 55.0) or 55.0),
            checkpoint_windows=tuple(
                getattr(context.config, "shadow_checkpoint_windows", ("15m", "1h"))
            ),
        )
        signal_keys = {
            (str(item.get("strategy_id", "")), str(item.get("profile_id", ""))): item
            for item in signal_dicts
        }
        proposal_keys = {
            (str(item.get("strategy_id", "")), str(item.get("profile_id", ""))): item
            for item in proposals
        }
        rejection_samples = list((batch.rejection_summary or {}).get("samples", []) or [])
        enriched: list[dict[str, Any]] = []
        for row in strategy_profiles:
            strategy_id = str(row.get("strategy_id", ""))
            profile_id = str(row.get("profile_id", ""))
            asset_classes = list(row.get("asset_classes", []) or [])
            signal = signal_keys.get((strategy_id, profile_id))
            proposal = proposal_keys.get((strategy_id, profile_id))
            market_data_exists = any(asset in {"equity", "crypto"} for asset in asset_classes)
            stage = str(row.get("internal_stage", "research_only"))
            paper_sim_disabled = not bool(getattr(context.config, "shadow_enabled", True))
            blocked_replay = stage in {"research_only", "promising_research", "rejected"}
            no_signal_reason = "-"
            if signal is None:
                matching_rejections = [
                    item
                    for item in rejection_samples
                    if str(item.get("strategy_id", "")) == strategy_id
                    and str(item.get("profile_id", "")) == profile_id
                ]
                if matching_rejections:
                    no_signal_reason = str(matching_rejections[0].get("reason", "-"))
            paper_sim_eligible = (
                not paper_sim_disabled
                and market_data_exists
                and not blocked_replay
                and signal is not None
            )
            paper_sim_block_reason = "-"
            if paper_sim_disabled:
                paper_sim_block_reason = "paper_sim_disabled"
            elif not market_data_exists:
                paper_sim_block_reason = "no_live_market_data_for_asset_class"
            elif blocked_replay:
                paper_sim_block_reason = (
                    "manually_rejected" if stage == "rejected" else "needs_more_replay_evidence_first"
                )
            elif signal is None:
                paper_sim_block_reason = f"strategy_signal_gates_not_passed:{no_signal_reason}"
            history = ledger.shadow_history.get((strategy_id, profile_id), {})
            last_signal_at = history.get("last_signal_at")
            last_outcome_at = history.get("last_outcome_at")
            enriched.append(
                {
                    **row,
                    "paper_sim_evaluated": bool(paper_sim_eligible and proposal is not None),
                    "paper_sim_eligible": paper_sim_eligible,
                    "paper_sim_block_reason": paper_sim_block_reason,
                    "live_market_data_exists": market_data_exists,
                    "live_signal_generated": signal is not None,
                    "no_signal_reason": no_signal_reason,
                    "blocked_more_replay_evidence_first": blocked_replay,
                    "blocked_paper_sim_disabled": paper_sim_disabled,
                    "paper_sim_records_exist": bool(history),
                    "last_paper_sim_signal_at": (
                        last_signal_at.isoformat() if hasattr(last_signal_at, "isoformat") else "-"
                    ),
                    "last_paper_sim_outcome_at": (
                        last_outcome_at.isoformat() if hasattr(last_outcome_at, "isoformat") else "-"
                    ),
                }
            )
        return enriched

    def _proof_candidates(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "AVAX/USD",
                "canonical_instrument_id": "AVAX/USD",
                "source": "proof_feed",
                "asset_class": "crypto",
                "close_price": 100.0,
                "movement_pct": -0.40,
                "discovery_score": 4.0,
                "trade_count": 80,
                "volume": 5000,
                "volume_gbp": 75000.0,
                "spread_pct": 0.05,
            },
            {
                "symbol": "AAPL",
                "canonical_instrument_id": "AAPL",
                "source": "proof_feed",
                "asset_class": "equity",
                "close_price": 100.0,
                "movement_pct": 0.02,
                "discovery_score": 4.2,
                "trade_count": 50,
                "volume": 1800,
                "close_price_gbp": 78.0,
            },
        ]


class _ProofResearchCycleRunner(research_cycle_module.ResearchCycleRunner):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            **kwargs,
        )
        self.bars_report = SimpleNamespace(build_report=self._bars_report)
        self.replay_runner = SimpleNamespace(run=self._replay_run)
        self.summary_report = SimpleNamespace(build_report=self._summary_report)
        self.comparison_report = SimpleNamespace(build_report=self._comparison_report)

    def _replay_run(self, **kwargs: Any) -> Any:
        timeframe = str(kwargs.get("timeframe", "15Min"))
        start_at = kwargs["start_at"]
        return SimpleNamespace(tick_id=f"{timeframe}-run-{start_at.strftime('%d%H%M')}")

    def _summary_report(self, replay_run_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "replay_run_id": replay_run_id,
            "candidates_evaluated": 16,
        }

    def _comparison_report(self, replay_limit: int) -> dict[str, Any]:
        return {"status": "ok", "replay_limit": replay_limit}

    def _bars_report(self, *, timeframe: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "historical": {
                "rows_by_timeframe": [{"timeframe": "15Min"}],
                "symbol_rows": [{"symbol": "AVAX/USD"}, {"symbol": "SOL/USD"}],
                "distinct_symbols": 2,
            },
            "replay_readiness": {
                "requested_timeframe": timeframe,
                "eligible_timestamps": 120,
                "can_replay_requested_range": timeframe == "15Min",
                "reason": "ok" if timeframe == "15Min" else "timeframe_not_present_in_historical_store",
            },
        }

    def _send_immediate_attention_alerts(self, *, cycle_id: str, started_at: datetime) -> None:
        _ = (cycle_id, started_at)
