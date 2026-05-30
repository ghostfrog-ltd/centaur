from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import RuntimeConfig, load_runtime_config
from .holding_window_advisor import HoldingWindowAdvisor
from .strategies import build_strategy_registry
from .threshold_advisor import ThresholdAdvisor
from .usage import UsageLedger


@dataclass(frozen=True, slots=True)
class LogFileStatus:
    path: Path
    exists: bool
    updated_at: datetime | None
    last_line: str


class StatusReporter:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def render(self, *, snapshot: dict[str, Any] | None = None) -> str:
        snapshot = snapshot or self.snapshot()
        now = snapshot["checked_at"]
        latest_tick = snapshot["latest_tick"]
        alerts = snapshot["alerts"]
        recent_orders = snapshot["recent_orders"]
        recent_proposals = snapshot["recent_proposals"]
        trade_diagnostics = snapshot["trade_diagnostics"]
        centaur_activity = snapshot["centaur_activity"]
        threshold_advice = snapshot["threshold_advice"]
        holding_window_advice = snapshot["holding_window_advice"]
        account_overview = snapshot["account_overview"]
        broker_accounts = snapshot["broker_accounts"]
        live_execution_overview = snapshot["live_execution_overview"]
        live_execution_intelligence = snapshot["live_execution_intelligence"]
        performance_comparison = snapshot["performance_comparison"]
        open_positions = snapshot["open_positions"]
        cost_overview = snapshot["cost_overview"]

        lines: list[str] = []
        lines.append("Centaur Status")
        lines.append(f"Checked: {self._fmt_dt(now)}")
        lines.append(
            (
                "Backend: "
                f"{self.usage_ledger.backend} | detail={self.usage_ledger.backend_detail}"
            )
        )
        lines.append(
            (
                "Paper mode: "
                f"enabled={'yes' if self.config.paper_execution_enabled else 'no'} | "
                f"kill_switch={'on' if self.config.paper_execution_kill_switch else 'off'} | "
                f"equity_market_open_required={'yes' if self.config.paper_execution_require_market_open else 'no'} | "
                f"crypto_overnight_enabled={'yes' if not self.config.paper_execution_equity_only else 'no'} | "
                f"equity_only={'yes' if self.config.paper_execution_equity_only else 'no'} | "
                f"notional=${self.config.paper_execution_default_notional_usd:.2f} | "
                f"profit_capture={self.config.paper_execution_profit_capture_pct * 100:.2f}% | "
                f"limit_buffer={self.config.paper_execution_limit_buffer_bps:.1f}bps | "
                f"crypto_limit_buffer={self.config.paper_execution_crypto_limit_buffer_bps:.1f}bps | "
                f"high_score_override={'on' if self.config.paper_execution_high_score_override_enabled else 'off'}"
                f"/{self.config.paper_execution_high_score_override_min_score:.1f}+"
                f"/{self.config.paper_execution_high_score_override_fitness_margin:.2f}fit | "
                f"max_daily_drawdown=${self.config.paper_execution_max_daily_drawdown_usd:.2f} | "
                f"stale_order_reaper={self.config.paper_execution_stale_order_minutes}m | "
                f"base_max_open_positions={self.config.paper_execution_max_open_positions} | "
                f"max_orders_per_tick={self.config.paper_execution_max_orders_per_tick} | "
                f"equity_broker={self.config.paper_execution_equity_broker_id} | "
                f"crypto_broker={self.config.paper_execution_crypto_broker_id}"
            )
        )
        allowed_strategies = ", ".join(self.config.paper_execution_allowed_strategies) or "none"
        lines.append(f"Allowed strategies: {allowed_strategies}")
        lines.append(
            (
                "Projected-gain floor: "
                f"equities={self.config.paper_execution_min_projected_gain_pct * 100:.2f}% | "
                f"crypto={self.config.paper_execution_crypto_min_projected_gain_pct * 100:.2f}%"
            )
        )

        if latest_tick is None:
            lines.append("")
            lines.append("Latest tick: none recorded yet")
        else:
            lines.extend(self._render_latest_tick(now=now, latest_tick=latest_tick))

        lines.append("")
        lines.append("Account:")
        for detail in self._render_account_overview(account_overview):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Broker accounts:")
        for detail in self._render_broker_accounts(now=now, broker_accounts=broker_accounts):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Live readiness:")
        for detail in self._render_live_execution_overview(live_execution_overview):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Live execution intelligence:")
        for detail in self._render_live_execution_intelligence(live_execution_intelligence):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Performance comparison:")
        for detail in self._render_performance_comparison(performance_comparison):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Alerts:")
        for alert in alerts:
            lines.append(self._render_alert_line(alert))

        lines.append("")
        lines.append("Recent paper orders:")
        if recent_orders:
            for order in recent_orders:
                lines.append(self._render_order_line(order))
        else:
            lines.append("- none")

        lines.append("")
        lines.append("Recent shadow proposals:")
        if recent_proposals:
            for proposal in recent_proposals[:5]:
                lines.append(self._render_proposal_line(proposal))
        else:
            lines.append("- none")

        lines.append("")
        lines.append("Trade diagnostics:")
        if trade_diagnostics:
            for detail in trade_diagnostics:
                lines.append(f"- {detail}")
        else:
            lines.append("- none")

        lines.append("")
        lines.append("Centaur activity:")
        for detail in self._render_centaur_activity(centaur_activity):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("GA threshold advice:")
        for detail in self._render_threshold_advice(threshold_advice):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Holding-window fitness:")
        for detail in self._render_holding_window_advice(holding_window_advice):
            lines.append(f"- {detail}")

        lines.append("")
        lines.append("Open paper positions:")
        if open_positions:
            for position in open_positions:
                lines.append(self._render_open_position_line(position))
        else:
            lines.append("- none")

        lines.append("")
        lines.append("API cost:")
        for detail in self._render_cost_overview(cost_overview):
            lines.append(f"- {detail}")

        wrapper_log = snapshot.get("wrapper_log")
        runtime_log = snapshot.get("runtime_log")
        if isinstance(wrapper_log, LogFileStatus) and isinstance(runtime_log, LogFileStatus):
            lines.append("")
            lines.append("Scheduler logs:")
            lines.append(self._render_log_line("wrapper", wrapper_log))
            lines.append(self._render_log_line("runtime", runtime_log))
        return "\n".join(lines)

    def print(self) -> None:
        print(self.render(), flush=True)

    def snapshot(
        self,
        *,
        include_visuals: bool = True,
        include_logs: bool = True,
    ) -> dict[str, Any]:
        checked_at = datetime.now().astimezone()
        recent_ticks = self.usage_ledger.list_recent_tick_runs(limit=60)
        latest_tick = self.usage_ledger.get_latest_tick_run()
        first_tick = self.usage_ledger.get_first_account_tick_run() or self.usage_ledger.get_first_tick_run()
        first_order = self.usage_ledger.get_first_paper_trade_order()
        recent_orders = self.usage_ledger.list_recent_paper_trade_orders(limit=5)
        recent_order_history = self.usage_ledger.list_recent_paper_trade_orders(limit=100)
        recent_broker_account_rows = self.usage_ledger.list_recent_broker_account_snapshots(limit=24)
        cost_overview = self._build_cost_overview(checked_at=checked_at)
        account_overview = self._build_account_overview(latest_tick=latest_tick)
        live_execution_overview = self._build_live_execution_overview()
        snapshot = {
            "checked_at": checked_at,
            "latest_tick": latest_tick,
            "recent_orders": recent_orders,
            "recent_proposals": self.usage_ledger.list_recent_shadow_trade_proposals(limit=5),
            "recent_ticks": recent_ticks,
            "trade_diagnostics": self._build_trade_diagnostics(latest_tick=latest_tick),
            "centaur_activity": self._build_centaur_activity(latest_tick=latest_tick),
            "threshold_advice": self._build_threshold_advice(),
            "holding_window_advice": self._build_holding_window_advice(),
            "account_overview": account_overview,
            "broker_accounts": self._build_broker_accounts(
                broker_snapshot_rows=recent_broker_account_rows,
            ),
            "live_execution_overview": live_execution_overview,
            "live_execution_intelligence": self._build_live_execution_intelligence(
                recent_orders=recent_order_history,
                live_execution_overview=live_execution_overview,
            ),
            "performance_comparison": self._build_performance_comparison(
                checked_at=checked_at,
                latest_tick=latest_tick,
                first_tick=first_tick,
                first_order=first_order,
                account_overview=account_overview,
            ),
            "open_positions": self._build_open_positions(
                latest_tick=latest_tick,
                recent_orders=recent_order_history,
            ),
            "alerts": self._build_alerts(
                now=checked_at,
                recent_ticks=recent_ticks,
                recent_orders=recent_orders,
            ),
            "cost_overview": cost_overview,
        }
        if include_visuals:
            strategy_events = self.usage_ledger.list_shadow_proposal_events(
                start_at=checked_at - timedelta(days=7),
                end_at=checked_at,
            )
            latest_fitness = self.usage_ledger.list_latest_strategy_fitness_snapshots(limit=64)
            training_volume = self.usage_ledger.list_strategy_training_volume()
            strategy_coverage = self._build_strategy_coverage(
                latest_fitness_rows=latest_fitness,
                proposal_events=strategy_events,
                training_volume_rows=training_volume,
            )
            strategy_leaderboard_notes = self._build_strategy_leaderboard_notes(
                strategy_rows=strategy_coverage
            )
            snapshot.update(
                {
                    "chart_ticks": recent_ticks[:24],
                    "chart_proposals": self.usage_ledger.list_recent_shadow_trade_proposals(limit=72),
                    "chart_fitness": latest_fitness[:8],
                    "chart_strategy_coverage": strategy_coverage,
                    "chart_strategy_proposals": strategy_coverage,
                    "chart_strategy_training": strategy_coverage,
                    "strategy_leaderboard_notes": strategy_leaderboard_notes,
                    "chart_breakout_activity": self._build_strategy_hourly_activity(
                        proposal_events=strategy_events,
                        strategy_id="momentum.volatility_breakout",
                        now=checked_at,
                        hours=24,
                    ),
                    "chart_cost_daily": cost_overview["daily_totals"],
                    "chart_cost_today": cost_overview["today_sources"],
                    "chart_cost_yesterday": cost_overview["yesterday_sources"],
                }
            )
        if include_logs:
            snapshot.update(
                {
                    "wrapper_log": self._get_log_status(Path.home() / "centaur_control_wrapper.log"),
                    "runtime_log": self._get_log_status(
                        Path.home() / ".centaur" / "runtime" / "control_tick.log"
                    ),
                }
            )
        return snapshot

    def _build_threshold_advice(self) -> dict[str, Any]:
        try:
            adviser = ThresholdAdvisor(
                config=self.config,
                usage_ledger=self.usage_ledger,
            )
            state = self.usage_ledger.get_strategy_threshold_adaptive_state() or {}
            state_threshold = state.get("effective_threshold")
            advice = adviser.build_advice(
                current_threshold=state_threshold
                if state_threshold is not None
                else self.config.strategy_allocation_suppress_threshold
            )
            advice["adaptive_enabled"] = self.config.strategy_threshold_adaptive_enabled
            advice["adaptive_state"] = {
                "effective_threshold": state.get("effective_threshold"),
                "crypto_threshold": self.config.strategy_allocation_crypto_suppress_threshold,
                "updated_at": self._fmt_dt(state.get("updated_at")),
                "source_tick_id": state.get("source_tick_id", ""),
                "reason": state.get("reason", ""),
                "floor": self.config.strategy_threshold_adaptive_floor,
                "ceiling": self.config.strategy_threshold_adaptive_ceiling,
                "band_width": self.config.strategy_threshold_adaptive_band_width,
                "cliff_safety_gap": self.config.strategy_threshold_adaptive_cliff_safety_gap,
                "max_step": self.config.strategy_threshold_adaptive_max_step,
                "cooldown_minutes": self.config.strategy_threshold_adaptive_cooldown_minutes,
                "min_ticks": self.config.strategy_threshold_adaptive_min_ticks,
                "min_confidence": self.config.strategy_threshold_adaptive_min_confidence,
            }
            return advice
        except Exception as exc:
            return {
                "status": "error",
                "mode": "recommendation_only",
                "current_threshold": self.config.strategy_allocation_suppress_threshold,
                "recommended_threshold": self.config.strategy_allocation_suppress_threshold,
                "crypto_threshold": self.config.strategy_allocation_crypto_suppress_threshold,
                "action": "hold",
                "confidence": "low",
                "adaptive_enabled": self.config.strategy_threshold_adaptive_enabled,
                "reason": f"GA threshold advice unavailable: {exc}",
            }

    def _build_holding_window_advice(self) -> dict[str, Any]:
        try:
            return HoldingWindowAdvisor(
                config=self.config,
                usage_ledger=self.usage_ledger,
            ).build_advice(strategy_id="mean_reversion.snapback")
        except Exception as exc:
            return {
                "status": "error",
                "mode": "recommendation_only",
                "strategy_id": "mean_reversion.snapback",
                "current_window": "1h",
                "reason": f"Holding-window advice unavailable: {exc}",
            }

    def _render_latest_tick(self, *, now: datetime, latest_tick: dict[str, Any]) -> list[str]:
        started_at = latest_tick.get("started_at")
        ended_at = latest_tick.get("ended_at")
        snapshot = latest_tick.get("state_snapshot_json", {})
        market_gate = self._as_dict(snapshot.get("market_gate"))
        strategy_signals = self._as_dict(snapshot.get("strategy_signals"))
        shadow_proposals = self._as_dict(snapshot.get("shadow_trade_proposals"))
        risk_cfo = self._as_dict(snapshot.get("risk_cfo"))
        execution = self._as_dict(snapshot.get("execution"))
        strategy_fitness = self._as_dict(snapshot.get("strategy_fitness"))
        daily_protection = self._as_dict(snapshot.get("daily_protection"))
        stale_order_reaper = self._as_dict(snapshot.get("stale_order_reaper"))

        tick_age = self._age_text(now, started_at)
        heartbeat = self._heartbeat_status(now=now, started_at=started_at)
        lines = [
            "",
            (
                "Latest tick: "
                f"{latest_tick.get('tick_id', '')} | "
                f"status={latest_tick.get('status', 'unknown')} | "
                f"started={self._fmt_dt(started_at)} | "
                f"ended={self._fmt_dt(ended_at)} | "
                f"age={tick_age} | "
                f"duration={self._fmt_seconds(latest_tick.get('duration_seconds'))} | "
                f"heartbeat={heartbeat}"
            ),
            (
                "Budget: "
                f"tick_requests={latest_tick.get('tick_api_request_count', 0)} | "
                f"tick_cost=${float(latest_tick.get('tick_estimated_cost_usd', 0) or 0):.6f} | "
                f"daily_requests={latest_tick.get('daily_api_request_count', 0)} | "
                f"daily_cost=${float(latest_tick.get('daily_estimated_cost_usd', 0) or 0):.6f} | "
                f"budget_status={latest_tick.get('budget_status', 'unknown')}"
            ),
            (
                "Market: "
                f"reason={market_gate.get('reason', 'unknown')} | "
                f"market_open={market_gate.get('market_open', False)} | "
                f"equity_scan_ready={market_gate.get('equity_scan_ready', False)} | "
                f"crypto_scan_ready={market_gate.get('crypto_scan_ready', False)}"
            ),
            (
                "Signals: "
                f"generated={strategy_signals.get('signals_generated', 0)} | "
                f"top_symbol={strategy_signals.get('top_symbol', '') or '-'} | "
                f"top_strategy={strategy_signals.get('top_strategy', '') or '-'} | "
                f"top_fitness_strategy={strategy_fitness.get('top_strategy', '') or '-'}"
            ),
            (
                "Shadow: "
                f"proposals_created={shadow_proposals.get('proposals_created', 0)} | "
                f"top_symbol={shadow_proposals.get('top_symbol', '') or '-'} | "
                f"top_strategy={shadow_proposals.get('top_strategy', '') or '-'}"
            ),
            (
                "CFO: "
                f"decision={risk_cfo.get('decision', 'unknown')} | "
                f"reason={risk_cfo.get('reason', 'unknown')} | "
                f"approved_trades={risk_cfo.get('approved_trades', 0)} | "
                f"open_positions={risk_cfo.get('open_positions', 0)} | "
                f"open_orders={risk_cfo.get('open_orders', 0)}"
            ),
            (
                "Execution: "
                f"status={execution.get('execution_status', 'unknown')} | "
                f"orders_submitted={execution.get('orders_submitted', 0)} | "
                f"orders_saved={execution.get('orders_saved', 0)}"
            ),
            (
                "Protection: "
                f"status={daily_protection.get('system_status', '-') or '-'} | "
                f"drawdown=${self._fmt_number(daily_protection.get('equity_drawdown_usd'), decimals=2)} | "
                f"limit=${self._fmt_number(daily_protection.get('max_daily_drawdown_usd'), decimals=2)} | "
                f"baseline=${self._fmt_number(daily_protection.get('baseline_equity'), decimals=2)}"
            ),
            (
                "Order maintenance: "
                f"stale_candidates={stale_order_reaper.get('stale_candidates', 0)} | "
                f"orders_canceled={stale_order_reaper.get('orders_canceled', 0)} | "
                f"stale_after={stale_order_reaper.get('stale_after_minutes', 0)}m"
            ),
        ]
        first_error = execution.get("first_error")
        if first_error:
            lines.append(f"Execution error: {first_error}")
        elif execution.get("orders_submitted", 0):
            submitted_symbols = execution.get("submitted_symbols", [])
            if isinstance(submitted_symbols, list) and submitted_symbols:
                symbols_text = ", ".join(str(symbol) for symbol in submitted_symbols[:3])
                lines.append(
                    "Execution detail: "
                    f"submitted_symbols={symbols_text} | "
                    f"latest_status={execution.get('latest_status', '-')}"
                )
        last_error = latest_tick.get("last_error")
        if last_error:
            lines.append(f"Last error: {last_error}")
        return lines

    def _build_trade_diagnostics(
        self,
        *,
        latest_tick: dict[str, Any] | None,
    ) -> list[str]:
        if latest_tick is None:
            return ["No persisted tick yet."]

        snapshot = self._as_dict(latest_tick.get("state_snapshot_json"))
        market_gate = self._as_dict(snapshot.get("market_gate"))
        strategy_signals = self._as_dict(snapshot.get("strategy_signals"))
        shadow_proposals = self._as_dict(snapshot.get("shadow_trade_proposals"))
        risk_cfo = self._as_dict(snapshot.get("risk_cfo"))
        execution = self._as_dict(snapshot.get("execution"))
        paper_exit_management = self._as_dict(snapshot.get("paper_exit_management"))
        daily_protection = self._as_dict(snapshot.get("daily_protection"))
        stale_order_reaper = self._as_dict(snapshot.get("stale_order_reaper"))

        decision = str(risk_cfo.get("decision", "hold")).strip().lower()
        reason = str(risk_cfo.get("reason", "unknown")).strip() or "unknown"
        if decision == "submit_paper":
            primary_line = f"CFO approved paper path | reason={reason}"
        else:
            primary_line = f"Primary blocker | reason={reason}"

        lines = [
            primary_line,
            (
                "Protection"
                f" | status={daily_protection.get('system_status', '-')}"
                f" | drawdown=${self._fmt_number(daily_protection.get('equity_drawdown_usd'), decimals=2)}"
                f" | limit=${self._fmt_number(daily_protection.get('max_daily_drawdown_usd'), decimals=2)}"
                f" | entries_blocked={daily_protection.get('entries_blocked', False)}"
            ),
            (
                "Market gate"
                f" | reason={market_gate.get('reason', '-')}"
                f" | market_open={market_gate.get('market_open', False)}"
                f" | equity_ready={market_gate.get('equity_scan_ready', False)}"
                f" | crypto_ready={market_gate.get('crypto_scan_ready', False)}"
            ),
            (
                "Flow"
                f" | signals={strategy_signals.get('signals_generated', 0)}"
                f" | proposals={shadow_proposals.get('proposals_created', 0)}"
                f" | approved={risk_cfo.get('approved_trades', 0)}"
                f" | rejected={risk_cfo.get('rejected_trades', 0)}"
            ),
            (
                "Capacity"
                f" | open_positions={risk_cfo.get('open_positions', 0)}"
                f" | open_orders={risk_cfo.get('open_orders', 0)}"
                f" | available_slots={risk_cfo.get('available_slots', 0)}"
            ),
        ]

        rejected = self._as_list(risk_cfo.get("rejected_candidates"))
        first_rejection = rejected[0] if rejected else {}
        if isinstance(first_rejection, dict) and first_rejection:
            lines.append(
                "First rejection"
                f" | symbol={str(first_rejection.get('symbol', '-') or '-').upper()}"
                f" | strategy={first_rejection.get('strategy_id', '-') or '-'}"
                f" | reason={first_rejection.get('reason', '-') or '-'}"
            )

        if stale_order_reaper:
            lines.append(
                "Stale reaper"
                f" | checked={stale_order_reaper.get('orders_checked', 0)}"
                f" | candidates={stale_order_reaper.get('stale_candidates', 0)}"
                f" | canceled={stale_order_reaper.get('orders_canceled', 0)}"
                + (
                    f" | first_error={self._truncate(str(stale_order_reaper.get('first_error', '-')), 120)}"
                    if stale_order_reaper.get("first_error")
                    else ""
                )
            )

        if int(execution.get("orders_submitted", 0) or 0) > 0:
            lines.append(
                "Execution"
                f" | status={execution.get('execution_status', '-')}"
                f" | submitted={execution.get('orders_submitted', 0)}"
                f" | symbols={', '.join(self._as_list(execution.get('submitted_symbols'))[:3]) or '-'}"
            )
        elif execution.get("first_error"):
            lines.append(
                "Execution issue"
                f" | status={execution.get('execution_status', '-')}"
                f" | detail={self._truncate(str(execution.get('first_error', '-')), 180)}"
            )

        skipped = self._as_list(paper_exit_management.get("skipped"))
        first_skip = skipped[0] if skipped else {}
        if paper_exit_management:
            lines.append(
                "Exit monitor"
                f" | mode={paper_exit_management.get('mode', '-')}"
                f" | positions_checked={paper_exit_management.get('positions_checked', 0)}"
                f" | exits_refreshed={paper_exit_management.get('exit_orders_refreshed', 0)}"
                f" | exits_submitted={paper_exit_management.get('exit_orders_submitted', 0)}"
                + (
                    f" | first_skip={first_skip.get('reason', '-')}"
                    if isinstance(first_skip, dict) and first_skip
                    else ""
                )
            )

        return lines

    def _build_centaur_activity(
        self,
        *,
        latest_tick: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if latest_tick is None:
            return {"status": "no_tick"}

        snapshot = self._as_dict(latest_tick.get("state_snapshot_json"))
        market_scan = self._as_dict(snapshot.get("market_scan"))
        market_result = self._as_dict(market_scan.get("result"))
        strategy_signals = self._as_dict(snapshot.get("strategy_signals"))
        allocation = self._as_dict(strategy_signals.get("allocation"))
        shadow_proposals = self._as_dict(snapshot.get("shadow_trade_proposals"))
        risk_cfo = self._as_dict(snapshot.get("risk_cfo"))
        tick_blockers = self._as_dict(snapshot.get("tick_blockers"))

        raw_preview = self._as_list(strategy_signals.get("raw_signal_preview"))
        suppressed_preview = self._as_list(strategy_signals.get("suppressed_signal_preview"))
        surviving_preview = self._as_list(strategy_signals.get("signals"))

        return {
            "status": "ok",
            "scan": {
                "mode": market_result.get("mode", "-"),
                "scan_ready": market_result.get("scan_ready", False),
                "candidates_found": market_result.get("candidates_found", 0),
                "selected_candidates": market_result.get("selected_candidates", 0),
                "bars_available": market_result.get("bars_available", 0),
                "top_symbol": market_result.get("top_symbol", "-"),
                "top_score": market_result.get("top_score"),
            },
            "flow": {
                "raw_signals": allocation.get("signals_in", 0),
                "surviving_signals": allocation.get(
                    "signals_out",
                    strategy_signals.get("signals_generated", 0),
                ),
                "suppressed_signals": allocation.get(
                    "suppressed",
                    strategy_signals.get("signals_suppressed", 0),
                ),
                "high_score_overrides": allocation.get(
                    "high_score_overrides",
                    strategy_signals.get("signals_high_score_overridden", 0),
                ),
                "proposals_created": shadow_proposals.get("proposals_created", 0),
                "cfo_reason": risk_cfo.get("reason", "-"),
            },
            "blockers": tick_blockers,
            "raw_signal_preview": raw_preview,
            "suppressed_signal_preview": suppressed_preview,
            "surviving_signal_preview": surviving_preview[:8],
        }

    def _render_centaur_activity(self, activity: dict[str, Any]) -> list[str]:
        if not activity or activity.get("status") == "no_tick":
            return ["No activity snapshot yet."]

        scan = self._as_dict(activity.get("scan"))
        flow = self._as_dict(activity.get("flow"))
        blockers = self._as_dict(activity.get("blockers"))
        lines = [
            (
                "Scan"
                f" | mode={scan.get('mode', '-')}"
                f" | candidates={scan.get('candidates_found', 0)}"
                f" | selected={scan.get('selected_candidates', 0)}"
                f" | bars={scan.get('bars_available', 0)}"
                f" | top={scan.get('top_symbol', '-')}"
                f" | score={self._fmt_number(scan.get('top_score'), decimals=2)}"
            ),
            (
                "Strategy flow"
                f" | raw={flow.get('raw_signals', 0)}"
                f" | survived={flow.get('surviving_signals', 0)}"
                f" | suppressed={flow.get('suppressed_signals', 0)}"
                f" | high_score_overrides={flow.get('high_score_overrides', 0)}"
                f" | proposals={flow.get('proposals_created', 0)}"
                f" | cfo={flow.get('cfo_reason', '-')}"
            ),
        ]
        if blockers:
            lines.append(
                (
                    "Blockers"
                    f" | stage={blockers.get('primary_stage', '-')}"
                    f" | market={blockers.get('market_reason', '-')}"
                    f" | cfo={blockers.get('cfo_reason', '-')}"
                    f" | rejects={self._render_reason_counts(blockers.get('rejection_reason_counts'))}"
                    f" | exits={self._render_reason_counts(blockers.get('exit_skip_reason_counts'))}"
                )
            )

        raw_preview = [
            item
            for item in self._as_list(activity.get("raw_signal_preview"))
            if isinstance(item, dict)
        ]
        suppressed_preview = [
            item
            for item in self._as_list(activity.get("suppressed_signal_preview"))
            if isinstance(item, dict)
        ]
        surviving_preview = [
            item
            for item in self._as_list(activity.get("surviving_signal_preview"))
            if isinstance(item, dict)
        ]

        if raw_preview:
            lines.append("Raw signal preview:")
            for item in raw_preview[:5]:
                lines.append(f"  {self._render_signal_diagnostic(item)}")
        else:
            lines.append("Raw signal preview: none captured on this tick")

        if suppressed_preview:
            lines.append("Suppressed signal preview:")
            for item in suppressed_preview[:5]:
                lines.append(f"  {self._render_signal_diagnostic(item)}")
        elif int(flow.get("suppressed_signals", 0) or 0) > 0:
            lines.append("Suppressed signal preview: not captured on this older tick")
        else:
            lines.append("Suppressed signal preview: none")

        if surviving_preview:
            lines.append("Surviving signal preview:")
            for item in surviving_preview[:5]:
                lines.append(f"  {self._render_signal_diagnostic(item)}")
        else:
            lines.append("Surviving signal preview: none")

        return lines

    def _render_threshold_advice(self, advice: dict[str, Any]) -> list[str]:
        if not advice:
            return ["No threshold advice available yet."]
        status = str(advice.get("status", "unknown"))
        if status != "ok":
            return [
                (
                    f"status={status}"
                    f" | current={self._fmt_number(advice.get('current_threshold'), decimals=2)}"
                    f" | reason={advice.get('reason', '-')}"
                )
            ]

        gene = self._as_dict(advice.get("gene"))
        test = self._as_dict(advice.get("test"))
        all_result = self._as_dict(advice.get("all"))
        adaptive_state = self._as_dict(advice.get("adaptive_state"))
        return [
            (
                f"action={advice.get('action', '-')}"
                f" | current={self._fmt_number(advice.get('current_threshold'), decimals=2)}"
                f" | recommended={self._fmt_number(advice.get('recommended_threshold'), decimals=2)}"
                f" | confidence={advice.get('confidence', '-')}"
                f" | mode={advice.get('mode', '-')}"
            ),
            (
                "adaptive="
                f"{'on' if advice.get('adaptive_enabled') else 'off'}"
                f" | effective={self._fmt_number(adaptive_state.get('effective_threshold'), decimals=2)}"
                f" | crypto={self._fmt_number(adaptive_state.get('crypto_threshold'), decimals=2)}"
                f" | rails={self._fmt_number(adaptive_state.get('ceiling'), decimals=2)}"
                f"..{self._fmt_number(adaptive_state.get('floor'), decimals=2)}"
                f" | band=+/-{self._fmt_number(adaptive_state.get('band_width'), decimals=2)}"
                f" | cliff_gap={self._fmt_number(adaptive_state.get('cliff_safety_gap'), decimals=2)}"
                f" | updated={adaptive_state.get('updated_at') or '-'}"
            ),
            (
                f"evidence=ticks {advice.get('tick_count', 0)}"
                f" | train {advice.get('train_tick_count', 0)}"
                f" | test {advice.get('test_tick_count', 0)}"
                f" | test_score={self._fmt_number(test.get('score'), decimals=2)}"
            ),
            (
                f"policy=base {self._fmt_number(gene.get('base_threshold'), decimals=2)}"
                f" | target {gene.get('target_low', '-')}-{gene.get('target_high', '-')}/tick"
                f" | ending {self._fmt_number(all_result.get('ending_threshold'), decimals=2)}"
            ),
            (
                "trade-aware="
                f"avg_tradeable {self._fmt_number(all_result.get('avg_tradeable_survivors'), decimals=2)}/tick"
                f" | avg_tradeable_fit={self._fmt_number(all_result.get('avg_tradeable_fitness'), decimals=2)}"
                f" | non_tradeable_survivors={int(all_result.get('non_tradeable_survivors', 0) or 0)}"
            ),
            str(advice.get("reason", "-")),
            str(adaptive_state.get("reason", "")),
        ]

    def _render_holding_window_advice(self, advice: dict[str, Any]) -> list[str]:
        if not advice:
            return ["No holding-window advice available yet."]
        status = str(advice.get("status", "unknown"))
        if status != "ok":
            return [
                (
                    f"status={status}"
                    f" | strategy={advice.get('strategy_id', '-')}"
                    f" | reason={advice.get('reason', '-')}"
                )
            ]

        recommendation = self._as_dict(advice.get("recommendation"))
        sample_counts = self._as_dict(advice.get("sample_counts"))
        fixed_all = self._as_dict(advice.get("fixed_windows_all"))
        fixed_long_all = self._as_dict(advice.get("fixed_windows_long_all"))
        fixed_7d = self._as_dict(advice.get("fixed_windows_7d"))
        policy_all = self._as_dict(advice.get("policy_stats_all"))
        lines = [
            (
                f"strategy={advice.get('strategy_id', '-')}"
                f" | current={advice.get('current_window', '-')}"
                f" | action={recommendation.get('action', '-')}"
                f" | candidate={recommendation.get('candidate_policy', '-')}"
                f" | confidence={recommendation.get('confidence', '-')}"
            ),
            (
                "samples="
                f"all {sample_counts.get('complete_15m_1h_1d', 0)}"
                f" | 30d {sample_counts.get('complete_15m_1h_1d_30d', 0)}"
                f" | 1h/1d/7d {sample_counts.get('complete_1h_1d_7d', 0)}"
                f" | 7d {sample_counts.get('complete_15m_1h_7d', 0)}"
                f" | 1d {sample_counts.get('complete_15m_1h_1d_1d', 0)}"
            ),
            (
                "all-time fixed="
                f"15m {self._holding_metric_text(self._as_dict(fixed_all.get('15m')))}"
                f" | 1h {self._holding_metric_text(self._as_dict(fixed_all.get('1h')))}"
                f" | 1d {self._holding_metric_text(self._as_dict(fixed_all.get('1d')))}"
            ),
            (
                "recent 7d fixed="
                f"15m {self._holding_metric_text(self._as_dict(fixed_7d.get('15m')))}"
                f" | 1h {self._holding_metric_text(self._as_dict(fixed_7d.get('1h')))}"
            ),
        ]
        if int(sample_counts.get("complete_1h_1d_7d", 0) or 0) > 0:
            lines.append(
                "all-time long="
                f"1h {self._holding_metric_text(self._as_dict(fixed_long_all.get('1h')))}"
                f" | 1d {self._holding_metric_text(self._as_dict(fixed_long_all.get('1d')))}"
                f" | 7d {self._holding_metric_text(self._as_dict(fixed_long_all.get('7d')))}"
            )
        lines.extend(
            [
                (
                    "dynamic="
                    f"1h_profit_else_1d {self._holding_metric_text(self._as_dict(policy_all.get('take_1h_profit_else_1d')))}"
                ),
                str(recommendation.get("reason", "-")),
            ]
        )
        return lines

    def _holding_metric_text(self, metrics: dict[str, Any]) -> str:
        if not metrics or int(metrics.get("n", 0) or 0) <= 0:
            return "n=0"
        return (
            f"n={metrics.get('n', 0)}"
            f"/avg={self._fmt_number(metrics.get('avg_return_pct'), decimals=2)}%"
            f"/win={float(metrics.get('win_rate', 0) or 0) * 100:.1f}%"
            f"/score={self._fmt_number(metrics.get('score'), decimals=2)}"
        )

    def _render_reason_counts(self, counts: Any) -> str:
        if not isinstance(counts, dict) or not counts:
            return "-"
        parts = []
        for reason, count in sorted(
            counts.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        ):
            parts.append(f"{reason}:{int(count)}")
            if len(parts) >= 3:
                break
        return ", ".join(parts) or "-"

    def _render_signal_diagnostic(self, item: dict[str, Any]) -> str:
        strategy_id = str(item.get("strategy_id", "-") or "-")
        symbol = str(item.get("symbol", "-") or "-").upper()
        allocation_status = str(item.get("allocation_status", "-") or "-")
        note = str(item.get("allocation_note", "") or "")
        return (
            f"{strategy_id} -> {symbol}"
            f" | status={allocation_status}"
            f" | score={self._fmt_number(item.get('signal_score'), decimals=2)}"
            f" | fitness={self._fmt_number(item.get('fitness_composite_score'), decimals=2)}"
            f" | checkpoints={item.get('fitness_checkpoints_evaluated', 0)}"
            f" | target={self._fmt_number(item.get('target_return_pct'), decimals=2)}%"
            + (f" | {self._truncate(note, 120)}" if note else "")
        )

    def _build_cost_overview(self, *, checked_at: datetime) -> dict[str, Any]:
        usd_to_gbp = self._latest_usd_to_gbp_rate()
        today = checked_at.date()
        yesterday = today - timedelta(days=1)
        today_rows = self.usage_ledger.list_daily_usage(usage_date=today)
        yesterday_rows = self.usage_ledger.list_daily_usage(usage_date=yesterday)
        recent_daily_totals: list[dict[str, Any]] = []
        for offset in range(6, -1, -1):
            usage_date = today - timedelta(days=offset)
            rows = self.usage_ledger.list_daily_usage(usage_date=usage_date)
            recent_daily_totals.append(
                {
                    "usage_date": usage_date.isoformat(),
                    "label": usage_date.strftime("%d %b"),
                    "estimated_cost_usd": round(
                        self.usage_ledger.total_estimated_cost_usd(rows),
                        6,
                    ),
                    "estimated_cost_gbp": self._convert_cost_to_gbp(
                        self.usage_ledger.total_estimated_cost_usd(rows),
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "request_count": self.usage_ledger.total_requests(rows),
                }
            )

        pricing_configured = self._pricing_configured()
        gemini_pricing_configured = self._provider_pricing_configured("gemini_api")
        today_sources = self._build_source_cost_rows(today_rows, usd_to_gbp=usd_to_gbp)
        yesterday_sources = self._build_source_cost_rows(
            yesterday_rows,
            usd_to_gbp=usd_to_gbp,
        )

        notes: list[str] = []
        if not self.config.gemini_analysis_enabled:
            notes.append(
                "Gemini analysis is disabled, so new Gemini API cost should stay flat unless you re-enable it."
            )
        if not pricing_configured:
            notes.append(
                "Internal cost estimates are incomplete because provider pricing is still zero or unset."
            )
        if not gemini_pricing_configured:
            notes.append(
                "Gemini requests are being counted, but Gemini token pricing is not configured in .env."
            )
        if not notes:
            notes.append("Internal estimated cost is based on the configured provider pricing values.")

        return {
            "pricing_configured": pricing_configured,
            "gemini_pricing_configured": gemini_pricing_configured,
            "usd_to_gbp": usd_to_gbp,
            "warning_threshold_usd": self.config.api_daily_cost_warning_usd,
            "limit_threshold_usd": self.config.api_daily_cost_limit_usd,
            "today": self._build_cost_day_snapshot(
                usage_date=today,
                rows=today_rows,
                usd_to_gbp=usd_to_gbp,
            ),
            "yesterday": self._build_cost_day_snapshot(
                usage_date=yesterday,
                rows=yesterday_rows,
                usd_to_gbp=usd_to_gbp,
            ),
            "daily_totals": recent_daily_totals,
            "today_sources": today_sources,
            "yesterday_sources": yesterday_sources,
            "notes": notes,
        }

    def _build_open_positions(
        self,
        *,
        latest_tick: dict[str, Any] | None,
        recent_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if latest_tick is None:
            return []

        snapshot = self._as_dict(latest_tick.get("state_snapshot_json"))
        positions_state = self._as_dict(snapshot.get("alpaca_positions"))
        orders_state = self._as_dict(snapshot.get("alpaca_orders"))
        exit_state = self._as_dict(snapshot.get("paper_exit_management"))
        raw_positions = self._as_list(positions_state.get("raw"))
        raw_orders = self._as_list(orders_state.get("raw"))
        exit_orders = self._as_list(exit_state.get("orders"))
        skipped = self._as_list(exit_state.get("skipped"))

        open_exit_symbols = {
            str(order.get("symbol", "")).upper()
            for order in raw_orders
            if isinstance(order, dict)
            and str(order.get("side", "")).strip().lower() == "sell"
            and self._order_status_is_open(str(order.get("status", "")))
        }
        submitted_exit_symbols = {
            str(order.get("symbol", "")).upper()
            for order in exit_orders
            if isinstance(order, dict)
            and str(order.get("side", "")).strip().lower() == "sell"
        }
        skipped_by_symbol = {
            str(item.get("symbol", "")).upper(): str(item.get("reason", "")).strip()
            for item in skipped
            if isinstance(item, dict) and item.get("symbol")
        }

        rows: list[dict[str, Any]] = []
        for position in raw_positions:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get("symbol", "")).upper()
            if not symbol:
                continue
            entry_order = self._find_latest_entry_plan(symbol=symbol, orders=recent_orders)
            raw_entry = self._as_dict(entry_order.get("raw_json")) if entry_order else {}
            if symbol in submitted_exit_symbols:
                exit_state_label = "exit_submitted"
            elif symbol in open_exit_symbols:
                exit_state_label = "sell_order_open"
            elif entry_order is None:
                exit_state_label = "missing_entry_plan"
            else:
                exit_state_label = skipped_by_symbol.get(symbol, "monitoring")

            rows.append(
                {
                    "symbol": symbol,
                    "qty": self._to_float(position.get("qty")),
                    "market_value_usd": self._to_float(position.get("market_value")),
                    "avg_entry_price": self._to_float(position.get("avg_entry_price")),
                    "current_price": self._to_float(position.get("current_price")),
                    "unrealized_pl_usd": self._to_float(position.get("unrealized_pl")),
                    "unrealized_pl_pct": self._pct_from_ratio(position.get("unrealized_plpc")),
                    "strategy_id": str(entry_order.get("strategy_id", "-") if entry_order else "-"),
                    "stop_loss_price": self._to_float(
                        raw_entry.get("planned_stop_loss_price")
                        if raw_entry.get("planned_stop_loss_price") is not None
                        else (entry_order or {}).get("stop_loss_price")
                    ),
                    "target_price": self._to_float(
                        raw_entry.get("planned_take_profit_price")
                        if raw_entry.get("planned_take_profit_price") is not None
                        else (entry_order or {}).get("take_profit_price")
                    ),
                    "profit_capture_pct": self._to_float(
                        raw_entry.get("planned_profit_capture_pct")
                    ),
                    "holding_window_code": str(
                        raw_entry.get("planned_holding_window_code")
                        or (entry_order or {}).get("planned_holding_window_code")
                        or "-"
                    ),
                    "managed_exit_policy": str(
                        raw_entry.get("planned_managed_exit_policy")
                        or (
                            "profit_after_1h_else_1d"
                            if str(entry_order.get("strategy_id", "")).strip()
                            == "mean_reversion.snapback"
                            else "time_exit"
                        )
                    ),
                    "exit_state": exit_state_label,
                }
            )

        rows.sort(key=lambda item: str(item.get("symbol", "")))
        return rows

    def _build_account_overview(
        self,
        *,
        latest_tick: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if latest_tick is None:
            return {}

        snapshot = self._as_dict(latest_tick.get("state_snapshot_json"))
        account_state = self._as_dict(snapshot.get("alpaca_account"))
        positions_state = self._as_dict(snapshot.get("alpaca_positions"))
        orders_state = self._as_dict(snapshot.get("alpaca_orders"))
        summary = self._as_dict(account_state.get("summary"))
        raw_account = self._as_dict(account_state.get("raw"))
        raw_positions = self._as_list(positions_state.get("raw"))
        raw_orders = self._as_list(orders_state.get("raw"))

        equity = self._to_float(summary.get("equity"))
        cash = self._to_float(summary.get("cash"))
        buying_power = self._to_float(summary.get("buying_power"))
        portfolio_value = self._to_float(summary.get("portfolio_value"))
        last_equity = self._to_float(raw_account.get("last_equity"))
        long_market_value = self._to_float(raw_account.get("long_market_value"))
        if long_market_value is None:
            long_market_value = self._to_float(raw_account.get("position_market_value"))
        usd_to_gbp = self._latest_usd_to_gbp_rate()

        day_change_usd: float | None = None
        day_change_pct: float | None = None
        if equity is not None and last_equity not in (None, 0):
            day_change_usd = round(equity - float(last_equity), 6)
            day_change_pct = round((day_change_usd / float(last_equity)) * 100, 6)

        total_open_unrealized_pl_usd = round(
            sum(
                self._to_float(position.get("unrealized_pl")) or 0.0
                for position in raw_positions
                if isinstance(position, dict)
            ),
            6,
        )
        day_change_gbp = self._convert_cost_to_gbp(
            day_change_usd,
            usd_to_gbp=usd_to_gbp,
        )
        total_open_unrealized_pl_gbp = self._convert_cost_to_gbp(
            total_open_unrealized_pl_usd,
            usd_to_gbp=usd_to_gbp,
        )
        open_positions_count = sum(
            1
            for position in raw_positions
            if isinstance(position, dict) and (self._to_float(position.get("qty")) or 0.0) > 0
        )
        open_entry_orders = [
            order
            for order in raw_orders
            if isinstance(order, dict)
            and str(order.get("side", "")).strip().lower() == "buy"
            and self._order_status_is_open(str(order.get("status", "")))
        ]
        open_entry_order_notional_usd = round(
            sum(
                self._estimate_order_notional_usd(order)
                or float(self.config.paper_execution_default_notional_usd)
                for order in open_entry_orders
            ),
            6,
        )
        broker_id = str(account_state.get("broker_id") or "alpaca_paper").strip().lower()
        slot_policy = self._build_earned_slot_policy(
            broker_id=broker_id,
            account_state_key="alpaca_account",
            current_equity=equity,
            base_max_positions=int(self.config.paper_execution_max_open_positions),
            slot_size_usd=float(self.config.paper_execution_default_notional_usd),
        )
        effective_max_open_positions = int(slot_policy["effective_max_open_positions"])
        capital_envelope_max_usd = round(
            float(self.config.paper_execution_default_notional_usd)
            * float(effective_max_open_positions),
            6,
        )
        capital_committed_usd = round(
            (open_positions_count * float(self.config.paper_execution_default_notional_usd))
            + open_entry_order_notional_usd,
            6,
        )
        capital_free_usd = round(
            max(capital_envelope_max_usd - capital_committed_usd, 0.0),
            6,
        )
        capital_committed_pct = (
            round((capital_committed_usd / capital_envelope_max_usd) * 100.0, 6)
            if capital_envelope_max_usd > 0
            else None
        )
        return {
            "broker_id": broker_id,
            "status": str(summary.get("status", "unknown") or "unknown"),
            "currency": str(summary.get("currency", "USD") or "USD"),
            "equity": equity,
            "cash": cash,
            "buying_power": buying_power,
            "portfolio_value": portfolio_value,
            "last_equity": last_equity,
            "day_change_usd": day_change_usd,
            "day_change_gbp": day_change_gbp,
            "day_change_pct": day_change_pct,
            "position_market_value_usd": long_market_value,
            "open_position_unrealized_pl_usd": total_open_unrealized_pl_usd,
            "open_position_unrealized_pl_gbp": total_open_unrealized_pl_gbp,
            "usd_to_gbp": usd_to_gbp,
            "capital_envelope_max_usd": capital_envelope_max_usd,
            "capital_envelope_max_gbp": self._convert_cost_to_gbp(
                capital_envelope_max_usd,
                usd_to_gbp=usd_to_gbp,
            ),
            "capital_committed_usd": capital_committed_usd,
            "capital_committed_gbp": self._convert_cost_to_gbp(
                capital_committed_usd,
                usd_to_gbp=usd_to_gbp,
            ),
            "capital_free_usd": capital_free_usd,
            "capital_free_gbp": self._convert_cost_to_gbp(
                capital_free_usd,
                usd_to_gbp=usd_to_gbp,
            ),
            "capital_committed_pct": capital_committed_pct,
            "open_positions_count": open_positions_count,
            "open_entry_orders_count": len(open_entry_orders),
            "base_max_open_positions": int(self.config.paper_execution_max_open_positions),
            "earned_slots": int(slot_policy["earned_slots"]),
            "effective_max_open_positions": effective_max_open_positions,
            "earned_slot_pnl_usd": slot_policy["total_pnl_usd"],
            "earned_slot_baseline_equity": slot_policy["baseline_equity"],
        }

    def _build_earned_slot_policy(
        self,
        *,
        broker_id: str,
        account_state_key: str,
        current_equity: float | None,
        base_max_positions: int,
        slot_size_usd: float,
    ) -> dict[str, Any]:
        base_slots = max(0, int(base_max_positions))
        slot_size = max(0.0, float(slot_size_usd or 0.0))
        baseline_equity = None
        first_order = self.usage_ledger.get_first_paper_trade_order(broker_id=broker_id)
        if first_order is not None:
            tracking_started_at = first_order.get("submitted_at") or first_order.get("captured_at")
            if isinstance(tracking_started_at, datetime):
                baseline_tick = self.usage_ledger.get_latest_tick_run_before(
                    started_before=tracking_started_at
                )
                baseline_snapshot = self._as_dict((baseline_tick or {}).get("state_snapshot_json"))
                baseline_account_state = self._as_dict(baseline_snapshot.get(account_state_key))
                baseline_summary = self._as_dict(baseline_account_state.get("summary"))
                baseline_raw = self._as_dict(baseline_account_state.get("raw"))
                baseline_equity = self._to_float(baseline_summary.get("equity"))
                if baseline_equity is None:
                    baseline_equity = self._to_float(baseline_raw.get("last_equity"))
                if baseline_equity is None:
                    baseline_equity = self._to_float(baseline_raw.get("equity"))

        total_pnl_usd = 0.0
        if baseline_equity is not None and current_equity is not None:
            total_pnl_usd = round(current_equity - baseline_equity, 6)
        earned_slots = int(max(total_pnl_usd, 0.0) // slot_size) if slot_size > 0 else 0
        return {
            "base_max_open_positions": base_slots,
            "slot_size_usd": slot_size,
            "baseline_equity": baseline_equity,
            "current_equity": current_equity,
            "total_pnl_usd": total_pnl_usd,
            "earned_slots": earned_slots,
            "effective_max_open_positions": base_slots + earned_slots,
        }

    def _build_broker_accounts(
        self,
        *,
        broker_snapshot_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        latest_by_broker: dict[str, dict[str, Any]] = {}
        for row in broker_snapshot_rows:
            broker_id = str(row.get("broker_id", "")).strip().lower()
            if broker_id and broker_id not in latest_by_broker:
                latest_by_broker[broker_id] = row

        desired_brokers: list[str] = []
        for broker_id in (
            self.config.paper_execution_equity_broker_id,
            self.config.paper_execution_crypto_broker_id,
            self.config.live_execution_equity_broker_id,
            self.config.live_execution_crypto_broker_id,
            "ig_spreadbet",
        ):
            normalized = str(broker_id or "").strip().lower()
            if normalized and normalized not in desired_brokers:
                desired_brokers.append(normalized)
        for broker_id in latest_by_broker:
            if broker_id not in desired_brokers:
                desired_brokers.append(broker_id)

        usd_to_gbp = self._latest_usd_to_gbp_rate()
        accounts: list[dict[str, Any]] = []
        for broker_id in desired_brokers:
            row = latest_by_broker.get(broker_id)
            roles: list[str] = []
            if broker_id == self.config.paper_execution_equity_broker_id:
                roles.append("equity_exec")
            if broker_id == self.config.paper_execution_crypto_broker_id:
                roles.append("crypto_exec")
            if broker_id == self.config.live_execution_equity_broker_id:
                roles.append("live_equity_follower")
            if (
                not self.config.live_execution_equity_only
                and broker_id == self.config.live_execution_crypto_broker_id
            ):
                roles.append("live_crypto_follower")

            broker_label = self._broker_label(broker_id)
            if row is None:
                if broker_id == "ig_spreadbet":
                    note = "scaffold only; no live account snapshot yet"
                    status = "scaffold_only"
                elif broker_id == "alpaca_live":
                    note = "dormant live follower; no live account snapshot yet"
                    status = "dormant"
                else:
                    note = "no recent account snapshot"
                    status = "no_snapshot"
                accounts.append(
                    {
                        "broker_id": broker_id,
                        "broker_label": broker_label,
                        "roles": roles,
                        "has_snapshot": False,
                        "status": status,
                        "note": note,
                    }
                )
                continue

            currency = str(row.get("currency", "USD") or "USD").upper()
            accounts.append(
                {
                    "broker_id": broker_id,
                    "broker_label": broker_label,
                    "roles": roles,
                    "has_snapshot": True,
                    "status": str(row.get("account_status", "unknown") or "unknown"),
                    "captured_at": row.get("captured_at"),
                    "currency": currency,
                    "equity": self._to_float(row.get("equity")),
                    "cash": self._to_float(row.get("cash")),
                    "buying_power": self._to_float(row.get("buying_power")),
                    "portfolio_value": self._to_float(row.get("portfolio_value")),
                    "last_equity": self._to_float(row.get("last_equity")),
                    "position_market_value": self._to_float(row.get("position_market_value")),
                    "open_position_unrealized_pl": self._to_float(
                        row.get("open_position_unrealized_pl")
                    ),
                    "equity_gbp": self._native_value_to_gbp(
                        row.get("equity"),
                        currency=currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "cash_gbp": self._native_value_to_gbp(
                        row.get("cash"),
                        currency=currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "open_position_unrealized_pl_gbp": self._native_value_to_gbp(
                        row.get("open_position_unrealized_pl"),
                        currency=currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                }
            )
        return accounts

    def _build_live_execution_overview(self) -> dict[str, Any]:
        """Summarize live readiness without implying live-money approval."""
        slot_size = float(self.config.live_execution_default_notional_usd)
        max_slots = int(self.config.live_execution_max_open_positions)
        envelope_max_usd = round(slot_size * max_slots, 6)
        blockers: list[str] = []
        if not self.config.live_execution_enabled:
            blockers.append("live_execution_disabled")
        if self.config.live_execution_kill_switch:
            blockers.append("live_kill_switch_on")
        if not self.config.alpaca_live_api_configured:
            blockers.append("alpaca_live_credentials_missing")
        if self.config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
            blockers.append("activation_ack_missing")
        if not self.config.live_execution_allowed_strategies:
            blockers.append("no_live_strategies_allowed")

        status = "safe_off"
        if self.config.live_execution_enabled or not self.config.live_execution_kill_switch:
            status = "blocked"
        if not blockers:
            status = "armed"

        return {
            "status": status,
            "broker_id": "alpaca_live",
            "enabled": self.config.live_execution_enabled,
            "kill_switch_on": self.config.live_execution_kill_switch,
            "credentials_configured": self.config.alpaca_live_api_configured,
            "activation_ack_present": self.config.live_execution_activation_ack
            == "LIVE_TRADING_APPROVED",
            "slot_size_usd": slot_size,
            "max_open_positions": max_slots,
            "envelope_max_usd": envelope_max_usd,
            "max_orders_per_tick": int(self.config.live_execution_max_orders_per_tick),
            "max_daily_drawdown_usd": float(self.config.live_execution_max_daily_drawdown_usd),
            "require_market_open": self.config.live_execution_require_market_open,
            "equity_only": self.config.live_execution_equity_only,
            "min_projected_gain_pct": float(self.config.live_execution_min_projected_gain_pct),
            "crypto_min_projected_gain_pct": float(
                self.config.live_execution_crypto_min_projected_gain_pct
            ),
            "limit_buffer_bps": float(self.config.live_execution_limit_buffer_bps),
            "crypto_limit_buffer_bps": float(
                self.config.live_execution_crypto_limit_buffer_bps
            ),
            "equity_broker_id": self.config.live_execution_equity_broker_id,
            "crypto_broker_id": self.config.live_execution_crypto_broker_id,
            "allowed_strategies": list(self.config.live_execution_allowed_strategies),
            "blockers": blockers,
            "note": (
                "Prepared for side-by-side paper/live operation. Live entries require "
                "credentials, explicit enablement, kill switch off, activation ack, "
                "and a live strategy allowlist before they can follow submitted paper trades."
            ),
        }

    def _build_live_execution_intelligence(
        self,
        *,
        recent_orders: list[dict[str, Any]],
        live_execution_overview: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare future live follower entries with same-proposal paper entries.

        This is deliberately read-only: strategy scoring remains shared shadow
        fitness, while this surface watches for execution divergence such as
        fill drift, status mismatch, or unmatched live orders.
        """
        paper_brokers = {
            str(self.config.paper_execution_equity_broker_id or "alpaca_paper").strip().lower(),
            str(self.config.paper_execution_crypto_broker_id or "alpaca_paper").strip().lower(),
        }
        live_brokers = {
            str(self.config.live_execution_equity_broker_id or "alpaca_live").strip().lower(),
            str(self.config.live_execution_crypto_broker_id or "alpaca_live").strip().lower(),
        }
        paper_entries = [
            order
            for order in recent_orders
            if str(order.get("broker_id", "")).strip().lower() in paper_brokers
            and str(order.get("side", "")).strip().lower() == "buy"
        ]
        live_entries = [
            order
            for order in recent_orders
            if str(order.get("broker_id", "")).strip().lower() in live_brokers
            and str(order.get("side", "")).strip().lower() == "buy"
        ]
        paper_by_proposal = {
            str(order.get("proposal_id", "")).strip(): order
            for order in paper_entries
            if str(order.get("proposal_id", "")).strip()
        }
        matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        unmatched_live: list[dict[str, Any]] = []
        for live_order in live_entries:
            proposal_id = str(live_order.get("proposal_id", "")).strip()
            paper_order = paper_by_proposal.get(proposal_id)
            if paper_order is None:
                unmatched_live.append(live_order)
            else:
                matched_pairs.append((paper_order, live_order))

        fill_drifts: list[dict[str, Any]] = []
        status_mismatches = 0
        for paper_order, live_order in matched_pairs:
            paper_fill = self._to_float(paper_order.get("filled_avg_price"))
            live_fill = self._to_float(live_order.get("filled_avg_price"))
            paper_status = str(paper_order.get("status", "")).strip().lower()
            live_status = str(live_order.get("status", "")).strip().lower()
            if paper_status and live_status and paper_status != live_status:
                status_mismatches += 1
            drift_bps = None
            if paper_fill is not None and live_fill is not None and paper_fill > 0:
                drift_bps = round(((live_fill - paper_fill) / paper_fill) * 10000.0, 2)
            fill_drifts.append(
                {
                    "symbol": str(live_order.get("symbol") or paper_order.get("symbol") or "").upper(),
                    "proposal_id": str(live_order.get("proposal_id", "")),
                    "strategy_id": str(live_order.get("strategy_id") or paper_order.get("strategy_id") or ""),
                    "paper_status": paper_status,
                    "live_status": live_status,
                    "paper_fill": paper_fill,
                    "live_fill": live_fill,
                    "fill_drift_bps": drift_bps,
                }
            )

        usable_drifts = [
            float(item["fill_drift_bps"])
            for item in fill_drifts
            if item.get("fill_drift_bps") is not None
        ]
        average_abs_drift_bps = (
            round(sum(abs(value) for value in usable_drifts) / len(usable_drifts), 2)
            if usable_drifts
            else None
        )
        blockers = list(live_execution_overview.get("blockers", []) or [])
        return {
            "mode": "read_only_execution_monitor",
            "strategy_intelligence": "shared_shadow_fitness",
            "live_independent_strategy_fitness": False,
            "paper_entry_orders_sampled": len(paper_entries),
            "live_entry_orders_sampled": len(live_entries),
            "matched_live_followups": len(matched_pairs),
            "unmatched_live_entries": len(unmatched_live),
            "status_mismatches": status_mismatches,
            "average_abs_fill_drift_bps": average_abs_drift_bps,
            "latest_fill_drifts": fill_drifts[:5],
            "blockers": blockers,
            "note": (
                "Live uses the shared shadow-fitness strategy brain. This monitor "
                "checks future live execution quality against same-proposal paper "
                "orders and remains read-only."
            ),
        }

    def _build_alerts(
        self,
        *,
        now: datetime,
        recent_ticks: list[dict[str, Any]],
        recent_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for tick in recent_ticks:
            snapshot = self._as_dict(tick.get("state_snapshot_json"))
            execution = self._as_dict(snapshot.get("execution"))
            risk_cfo = self._as_dict(snapshot.get("risk_cfo"))
            started_at = tick.get("started_at")
            execution_status = str(execution.get("execution_status", "")).strip().lower()
            if execution_status == "error":
                errors = execution.get("errors", [])
                first_item = errors[0] if isinstance(errors, list) and errors else {}
                first_item = first_item if isinstance(first_item, dict) else {}
                symbol = (
                    str(first_item.get("symbol", "")).upper()
                    or self._first_list_item(risk_cfo.get("approved_symbols"))
                    or "unknown symbol"
                )
                detail = (
                    str(first_item.get("error", "")).strip()
                    or str(execution.get("first_error", "")).strip()
                    or str(tick.get("last_error", "")).strip()
                    or "Paper execution failed."
                )
                alerts.append(
                    {
                        "level": "error",
                        "kind": "paper_execution_failed",
                        "at": started_at,
                        "tick_id": tick.get("tick_id", ""),
                        "summary": f"Paper execution failed for {symbol}",
                        "detail": detail,
                        "age": self._age_text(now, started_at),
                    }
                )
                continue
            if int(execution.get("orders_submitted", 0) or 0) > 0:
                submitted_symbols = execution.get("submitted_symbols", [])
                if not isinstance(submitted_symbols, list):
                    submitted_symbols = []
                symbol_text = ", ".join(str(symbol).upper() for symbol in submitted_symbols[:3]) or "paper order"
                alerts.append(
                    {
                        "level": "info",
                        "kind": "paper_order_submitted",
                        "at": started_at,
                        "tick_id": tick.get("tick_id", ""),
                        "summary": f"Paper order submitted for {symbol_text}",
                        "detail": (
                            f"latest_status={execution.get('latest_status', '-')}"
                            f" | orders_saved={execution.get('orders_saved', 0)}"
                        ),
                        "age": self._age_text(now, started_at),
                    }
                )

        if alerts:
            return alerts[:5]

        if recent_orders:
            latest_order = recent_orders[0]
            submitted_at = latest_order.get("submitted_at") or latest_order.get("captured_at")
            return [
                {
                    "level": "info",
                    "kind": "latest_paper_order",
                    "at": submitted_at,
                    "tick_id": latest_order.get("tick_id", ""),
                    "summary": (
                        f"Latest paper order: {latest_order.get('symbol', '-')}"
                        f" {latest_order.get('status', '-')}"
                    ),
                    "detail": (
                        f"side={latest_order.get('side', '-')}"
                        f" | strategy={latest_order.get('strategy_id', '-')}"
                    ),
                    "age": self._age_text(now, submitted_at),
                }
            ]

        return [
            {
                "level": "ok",
                "kind": "clear",
                "at": None,
                "tick_id": "",
                "summary": "No recent paper execution alerts",
                "detail": "No recent submission failures or submitted orders were found.",
                "age": "-",
            }
        ]

    def _build_performance_comparison(
        self,
        *,
        checked_at: datetime,
        latest_tick: dict[str, Any] | None,
        first_tick: dict[str, Any] | None,
        first_order: dict[str, Any] | None,
        account_overview: dict[str, Any],
    ) -> dict[str, Any]:
        if latest_tick is None or not account_overview:
            return {}

        baseline_tick = None
        tracking_started_at = None
        tracking_source = "first_tick"
        if first_order is not None:
            tracking_started_at = first_order.get("submitted_at") or first_order.get("captured_at")
            if isinstance(tracking_started_at, datetime):
                baseline_tick = self.usage_ledger.get_latest_tick_run_before(
                    started_before=tracking_started_at
                )
                tracking_source = "pre_first_paper_order_tick"
        if baseline_tick is None:
            baseline_tick = first_tick or latest_tick
            if tracking_started_at is None and baseline_tick is not None:
                tracking_started_at = baseline_tick.get("started_at")
        baseline_snapshot = self._as_dict((baseline_tick or {}).get("state_snapshot_json"))
        baseline_account_state = self._as_dict(baseline_snapshot.get("alpaca_account"))
        baseline_summary = self._as_dict(baseline_account_state.get("summary"))
        baseline_raw = self._as_dict(baseline_account_state.get("raw"))
        baseline_equity = self._to_float(baseline_summary.get("equity"))
        if baseline_equity is None:
            baseline_equity = self._to_float(baseline_raw.get("last_equity"))
        current_equity = self._to_float(account_overview.get("equity"))
        envelope_max_usd = self._to_float(account_overview.get("capital_envelope_max_usd"))
        usd_to_gbp = self._to_float(account_overview.get("usd_to_gbp"))

        if baseline_equity is None or current_equity is None or envelope_max_usd in (None, 0):
            return {}

        if tracking_started_at is None:
            return {}

        tracked_seconds = max((checked_at - tracking_started_at).total_seconds(), 0.0)
        tracked_days = max(tracked_seconds / 86400.0, 0.0)
        total_pnl_usd = round(current_equity - baseline_equity, 6)
        total_pnl_gbp = self._convert_cost_to_gbp(total_pnl_usd, usd_to_gbp=usd_to_gbp)
        return_on_envelope_pct = round((total_pnl_usd / envelope_max_usd) * 100.0, 6)
        simple_annualized_pct = (
            round((return_on_envelope_pct / tracked_days) * 365.0, 6)
            if tracked_days > 0
            else None
        )
        benchmarks = []
        for annual_rate in (5.0, 10.0, 20.0):
            annual_profit_usd = round(envelope_max_usd * (annual_rate / 100.0), 6)
            benchmarks.append(
                {
                    "annual_rate_pct": annual_rate,
                    "annual_profit_usd": annual_profit_usd,
                    "annual_profit_gbp": self._convert_cost_to_gbp(
                        annual_profit_usd,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "daily_profit_usd": round(annual_profit_usd / 365.0, 6),
                    "daily_profit_gbp": self._convert_cost_to_gbp(
                        annual_profit_usd / 365.0,
                        usd_to_gbp=usd_to_gbp,
                    ),
                }
            )

        return {
            "tracking_started_at": tracking_started_at,
            "tracking_source": tracking_source,
            "tracked_days": tracked_days,
            "baseline_equity": baseline_equity,
            "current_equity": current_equity,
            "total_pnl_usd": total_pnl_usd,
            "total_pnl_gbp": total_pnl_gbp,
            "envelope_max_usd": envelope_max_usd,
            "envelope_max_gbp": self._convert_cost_to_gbp(
                envelope_max_usd,
                usd_to_gbp=usd_to_gbp,
            ),
            "return_on_envelope_pct": return_on_envelope_pct,
            "simple_annualized_pct": simple_annualized_pct,
            "benchmarks": benchmarks,
            "note": "Short paper-trading samples are not comparable to diversified long-term investing yet.",
        }

    def _render_alert_line(self, alert: dict[str, Any]) -> str:
        return (
            "- "
            f"{str(alert.get('level', 'info')).upper()} | "
            f"{self._fmt_dt(alert.get('at'))} | "
            f"{alert.get('summary', '-')}"
            f" | detail={self._truncate(str(alert.get('detail', '-') or '-'), 180)}"
        )

    def _render_order_line(self, order: dict[str, Any]) -> str:
        return (
            "- "
            f"{self._fmt_dt(order.get('submitted_at') or order.get('captured_at'))} | "
            f"{order.get('symbol', '')} | "
            f"{order.get('status', '') or '-'} | "
            f"side={order.get('side', '') or '-'} | "
            f"notional=${float(order.get('notional_usd') or 0):.2f} | "
            f"strategy={order.get('strategy_id', '') or '-'}"
        )

    def _render_proposal_line(self, proposal: dict[str, Any]) -> str:
        return (
            "- "
            f"{self._fmt_dt(proposal.get('proposed_at'))} | "
            f"{proposal.get('symbol', '')} | "
            f"status={proposal.get('status', '') or '-'} | "
            f"strategy={proposal.get('strategy_id', '') or '-'} | "
            f"score={float(proposal.get('signal_score') or proposal.get('opportunity_score') or 0):.3f}"
        )

    def _render_cost_overview(self, overview: dict[str, Any]) -> list[str]:
        today = self._as_dict(overview.get("today"))
        yesterday = self._as_dict(overview.get("yesterday"))
        usd_to_gbp = self._to_float(overview.get("usd_to_gbp"))
        fx_text = f"{usd_to_gbp:.4f}" if usd_to_gbp is not None else "-"
        lines = [
            (
                "Pricing"
                f" | configured={'yes' if overview.get('pricing_configured') else 'no'}"
                f" | gemini_pricing={'yes' if overview.get('gemini_pricing_configured') else 'no'}"
                f" | usd_to_gbp={fx_text}"
            ),
            (
                "Today"
                f" | est=${self._fmt_number(today.get('estimated_cost_usd'), decimals=4)}"
                f" | est_gbp={self._fmt_currency_prefix(today.get('estimated_cost_gbp'), '£', 4)}"
                f" | requests={int(today.get('request_count', 0) or 0)}"
            ),
            (
                "Yesterday"
                f" | est=${self._fmt_number(yesterday.get('estimated_cost_usd'), decimals=4)}"
                f" | est_gbp={self._fmt_currency_prefix(yesterday.get('estimated_cost_gbp'), '£', 4)}"
                f" | requests={int(yesterday.get('request_count', 0) or 0)}"
            ),
            (
                "Budget"
                f" | warning=${float(overview.get('warning_threshold_usd', 0) or 0):.2f}"
                f" | limit=${float(overview.get('limit_threshold_usd', 0) or 0):.2f}"
            ),
        ]
        for note in self._as_list(overview.get("notes"))[:3]:
            lines.append(str(note))
        return lines

    def _render_open_position_line(self, position: dict[str, Any]) -> str:
        unrealized_pl_usd = self._to_float(position.get("unrealized_pl_usd")) or 0.0
        unrealized_pl_pct = self._to_float(position.get("unrealized_pl_pct"))
        unrealized_pct_text = (
            f"{unrealized_pl_pct:+.2f}%"
            if unrealized_pl_pct is not None
            else "-"
        )
        return (
            "- "
            f"{position.get('symbol', '')} | "
            f"qty={self._fmt_number(position.get('qty'), decimals=4)} | "
            f"mv=${self._fmt_number(position.get('market_value_usd'), decimals=2)} | "
            f"entry=${self._fmt_number(position.get('avg_entry_price'), decimals=4)} | "
            f"current=${self._fmt_number(position.get('current_price'), decimals=4)} | "
            f"upl=${unrealized_pl_usd:+.2f} ({unrealized_pct_text}) | "
            f"stop=${self._fmt_number(position.get('stop_loss_price'), decimals=4)} | "
            f"target=${self._fmt_number(position.get('target_price'), decimals=4)} | "
            f"policy={position.get('managed_exit_policy', '-') or '-'} | "
            f"exit={position.get('exit_state', '-') or '-'} | "
            f"strategy={position.get('strategy_id', '-') or '-'}"
        )

    def _render_account_overview(self, overview: dict[str, Any]) -> list[str]:
        if not overview:
            return ["No account snapshot yet."]

        broker_id = str(overview.get("broker_id", "alpaca_paper") or "alpaca_paper").strip().lower()
        day_change_usd = self._to_float(overview.get("day_change_usd"))
        day_change_gbp = self._to_float(overview.get("day_change_gbp"))
        day_change_pct = self._to_float(overview.get("day_change_pct"))
        day_change_text = (
            f"${day_change_usd:+.2f}"
            if day_change_usd is not None
            else "-"
        )
        if day_change_gbp is not None:
            day_change_text = f"{day_change_text} (approx £{day_change_gbp:+.2f})"
        if day_change_pct is not None:
            day_change_text = f"{day_change_text} ({day_change_pct:+.2f}%)"

        open_pl_usd = self._to_float(overview.get("open_position_unrealized_pl_usd"))
        open_pl_gbp = self._to_float(overview.get("open_position_unrealized_pl_gbp"))
        open_pl_text = (
            f"${open_pl_usd:.2f}"
            if open_pl_usd is not None
            else "-"
        )
        if open_pl_gbp is not None:
            open_pl_text = f"{open_pl_text} (approx £{open_pl_gbp:.2f})"

        return [
            (
                f"Broker={self._broker_label(broker_id)} | "
                f"Status={overview.get('status', 'unknown')} | "
                f"Equity=${self._fmt_number(overview.get('equity'), decimals=2)} | "
                f"Last equity=${self._fmt_number(overview.get('last_equity'), decimals=2)} | "
                f"Day change={day_change_text}"
            ),
            (
                f"Cash=${self._fmt_number(overview.get('cash'), decimals=2)} | "
                f"Buying power=${self._fmt_number(overview.get('buying_power'), decimals=2)} | "
                f"Position value=${self._fmt_number(overview.get('position_market_value_usd'), decimals=2)} | "
                f"Open P/L={open_pl_text}"
            ),
            self._render_capital_envelope_line(overview),
        ]

    def _render_broker_accounts(
        self,
        *,
        now: datetime,
        broker_accounts: list[dict[str, Any]],
    ) -> list[str]:
        if not broker_accounts:
            return ["No broker account snapshots recorded yet."]

        lines: list[str] = []
        for account in broker_accounts:
            broker_id = str(account.get("broker_id", "")).strip().lower()
            broker_label = str(account.get("broker_label", broker_id) or broker_id)
            role_text = ", ".join(account.get("roles", []) or []) or "-"
            if not account.get("has_snapshot"):
                note = str(account.get("note", "")).strip()
                line = (
                    f"{broker_label} ({broker_id}) | roles={role_text} | "
                    f"status={account.get('status', 'unknown')}"
                )
                if note:
                    line = f"{line} | {note}"
                lines.append(line)
                continue

            currency = str(account.get("currency", "USD") or "USD").upper()
            prefix = "$" if currency == "USD" else "£" if currency == "GBP" else f"{currency} "
            equity_text = self._fmt_currency_prefix(account.get("equity"), prefix, 2)
            cash_text = self._fmt_currency_prefix(account.get("cash"), prefix, 2)
            open_pl_value = self._to_float(account.get("open_position_unrealized_pl"))
            open_pl_text = (
                f"{prefix}{open_pl_value:+.2f}"
                if open_pl_value is not None
                else "-"
            )

            equity_gbp = self._to_float(account.get("equity_gbp"))
            cash_gbp = self._to_float(account.get("cash_gbp"))
            open_pl_gbp = self._to_float(account.get("open_position_unrealized_pl_gbp"))
            if currency != "GBP" and equity_gbp is not None:
                equity_text = f"{equity_text} (approx £{equity_gbp:.2f})"
            if currency != "GBP" and cash_gbp is not None:
                cash_text = f"{cash_text} (approx £{cash_gbp:.2f})"
            if currency != "GBP" and open_pl_gbp is not None:
                open_pl_text = f"{open_pl_text} (approx £{open_pl_gbp:+.2f})"

            captured_at = account.get("captured_at")
            lines.append(
                (
                    f"{broker_label} ({broker_id}) | roles={role_text} | "
                    f"status={account.get('status', 'unknown')} | currency={currency} | "
                    f"equity={equity_text} | cash={cash_text} | "
                    f"open P/L={open_pl_text} | age={self._age_text(now, captured_at)}"
                )
            )
        return lines

    def _render_live_execution_overview(self, overview: dict[str, Any]) -> list[str]:
        if not overview:
            return ["No live-readiness state available."]

        status = str(overview.get("status", "unknown") or "unknown")
        enabled = "yes" if overview.get("enabled") else "no"
        kill_switch = "on" if overview.get("kill_switch_on") else "off"
        credentials = "yes" if overview.get("credentials_configured") else "no"
        activation_ack = "yes" if overview.get("activation_ack_present") else "no"
        asset_scope = "equities only" if overview.get("equity_only") else "equities + crypto"
        strategies = ", ".join(overview.get("allowed_strategies", []) or []) or "none"
        blockers = ", ".join(overview.get("blockers", []) or []) or "none"
        return [
            (
                f"Status={status} | broker={self._broker_label(str(overview.get('broker_id', 'alpaca_live')))} | "
                f"enabled={enabled} | kill_switch={kill_switch} | credentials={credentials} | "
                f"activation_ack={activation_ack}"
            ),
            (
                f"Envelope=${self._fmt_number(overview.get('envelope_max_usd'), decimals=2)} | "
                f"slot_size=${self._fmt_number(overview.get('slot_size_usd'), decimals=2)} | "
                f"slots={overview.get('max_open_positions', 0)} | "
                f"max_orders_per_tick={overview.get('max_orders_per_tick', 0)} | "
                f"daily_loss_limit=${self._fmt_number(overview.get('max_daily_drawdown_usd'), decimals=2)}"
            ),
            (
                f"Asset scope={asset_scope} | allowed_strategies={strategies} | "
                f"projected_gain=equity {float(overview.get('min_projected_gain_pct') or 0) * 100:.2f}%"
                f"/crypto {float(overview.get('crypto_min_projected_gain_pct') or 0) * 100:.2f}% | "
                f"limit_buffer=equity {self._fmt_number(overview.get('limit_buffer_bps'), decimals=1)}bps"
                f"/crypto {self._fmt_number(overview.get('crypto_limit_buffer_bps'), decimals=1)}bps"
            ),
            f"Blockers={blockers}",
            str(overview.get("note", "") or "").strip(),
        ]

    def _render_live_execution_intelligence(self, overview: dict[str, Any]) -> list[str]:
        if not overview:
            return ["No live execution intelligence available yet."]

        shared_brain = str(overview.get("strategy_intelligence", "unknown") or "unknown")
        independent = "yes" if overview.get("live_independent_strategy_fitness") else "no"
        blockers = ", ".join(overview.get("blockers", []) or []) or "none"
        lines = [
            (
                f"Mode={overview.get('mode', 'unknown')} | strategy_brain={shared_brain} | "
                f"independent_live_strategy_fitness={independent}"
            ),
            (
                f"Recent entry sample | paper={overview.get('paper_entry_orders_sampled', 0)} | "
                f"live={overview.get('live_entry_orders_sampled', 0)} | "
                f"matched_followups={overview.get('matched_live_followups', 0)} | "
                f"unmatched_live={overview.get('unmatched_live_entries', 0)}"
            ),
            (
                f"Execution drift | status_mismatches={overview.get('status_mismatches', 0)} | "
                f"avg_abs_fill_drift={self._fmt_number(overview.get('average_abs_fill_drift_bps'), decimals=2)}bps"
            ),
            f"Live blockers currently limiting comparison={blockers}",
        ]
        fill_drifts = overview.get("latest_fill_drifts", [])
        if isinstance(fill_drifts, list) and fill_drifts:
            for item in fill_drifts[:3]:
                item = item if isinstance(item, dict) else {}
                lines.append(
                    (
                        f"Pair {item.get('symbol', '-')}: paper={item.get('paper_status', '-')}"
                        f" @ {self._fmt_number(item.get('paper_fill'), decimals=4)} | "
                        f"live={item.get('live_status', '-')} @ "
                        f"{self._fmt_number(item.get('live_fill'), decimals=4)} | "
                        f"drift={self._fmt_number(item.get('fill_drift_bps'), decimals=2)}bps"
                    )
                )
        else:
            lines.append("No live/paper fill pairs yet; comparison becomes useful after live follower orders exist.")
        note = str(overview.get("note", "") or "").strip()
        if note:
            lines.append(note)
        return lines

    def _render_capital_envelope_line(self, overview: dict[str, Any]) -> str:
        max_usd = self._to_float(overview.get("capital_envelope_max_usd"))
        max_gbp = self._to_float(overview.get("capital_envelope_max_gbp"))
        committed_usd = self._to_float(overview.get("capital_committed_usd"))
        committed_gbp = self._to_float(overview.get("capital_committed_gbp"))
        free_usd = self._to_float(overview.get("capital_free_usd"))
        free_gbp = self._to_float(overview.get("capital_free_gbp"))
        committed_pct = self._to_float(overview.get("capital_committed_pct"))
        open_positions_count = int(overview.get("open_positions_count", 0) or 0)
        open_entry_orders_count = int(overview.get("open_entry_orders_count", 0) or 0)
        base_slots = int(overview.get("base_max_open_positions", 0) or 0)
        earned_slots = int(overview.get("earned_slots", 0) or 0)
        effective_slots = int(overview.get("effective_max_open_positions", base_slots) or base_slots)

        max_text = self._fmt_currency_prefix(max_usd, "$", 2)
        if max_gbp is not None:
            max_text = f"{max_text} (approx £{max_gbp:.2f})"

        committed_text = self._fmt_currency_prefix(committed_usd, "$", 2)
        if committed_gbp is not None:
            committed_text = f"{committed_text} (approx £{committed_gbp:.2f})"

        free_text = self._fmt_currency_prefix(free_usd, "$", 2)
        if free_gbp is not None:
            free_text = f"{free_text} (approx £{free_gbp:.2f})"

        committed_pct_text = (
            f"{committed_pct:.1f}%"
            if committed_pct is not None
            else "-"
        )
        earned_text = (
            f" | earned_slots=+{earned_slots}"
            if earned_slots > 0
            else ""
        )
        return (
            "Capital envelope="
            f"{max_text} | "
            f"committed={committed_text} | "
            f"free={free_text} | "
            f"used={committed_pct_text} | "
            f"slots={open_positions_count}/{effective_slots}"
            f"{earned_text} | "
            f"open_entry_orders={open_entry_orders_count}"
        )

    def _render_performance_comparison(self, comparison: dict[str, Any]) -> list[str]:
        if not comparison:
            return ["No paper-performance comparison available yet."]

        tracked_days = self._to_float(comparison.get("tracked_days"))
        tracked_text = f"{tracked_days:.1f}d" if tracked_days is not None else "-"
        tracking_started_at = comparison.get("tracking_started_at")
        tracking_source = str(comparison.get("tracking_source", "-") or "-")
        tracking_source_label = {
            "pre_first_paper_order_tick": "tick before first paper order",
            "first_tick": "first persisted tick",
        }.get(tracking_source, tracking_source)
        total_pnl_usd = self._to_float(comparison.get("total_pnl_usd"))
        total_pnl_gbp = self._to_float(comparison.get("total_pnl_gbp"))
        envelope_max_usd = self._to_float(comparison.get("envelope_max_usd"))
        envelope_max_gbp = self._to_float(comparison.get("envelope_max_gbp"))
        return_on_envelope_pct = self._to_float(comparison.get("return_on_envelope_pct"))
        simple_annualized_pct = self._to_float(comparison.get("simple_annualized_pct"))

        pnl_text = (
            f"${total_pnl_usd:+.2f}"
            if total_pnl_usd is not None
            else "-"
        )
        if total_pnl_gbp is not None:
            pnl_text = f"{pnl_text} (approx £{total_pnl_gbp:+.2f})"

        envelope_text = self._fmt_currency_prefix(envelope_max_usd, "$", 2)
        if envelope_max_gbp is not None:
            envelope_text = f"{envelope_text} (approx £{envelope_max_gbp:.2f})"

        lines = [
            (
                f"Tracking window={tracked_text} | "
                f"since={self._fmt_dt(tracking_started_at)} | "
                f"source={tracking_source_label}"
            ),
            (
                f"Paper P/L vs configured bankroll cap={pnl_text} | "
                f"bankroll_cap={envelope_text} | "
                f"return_on_cap={return_on_envelope_pct:+.2f}%"
                if return_on_envelope_pct is not None
                else f"Paper P/L vs configured bankroll cap={pnl_text} | bankroll_cap={envelope_text}"
            ),
        ]
        if simple_annualized_pct is not None:
            lines.append(
                f"Simple annualized pace (not a forecast)={simple_annualized_pct:+.2f}%/yr"
            )

        benchmark_parts: list[str] = []
        for benchmark in self._as_list(comparison.get("benchmarks")):
            if not isinstance(benchmark, dict):
                continue
            annual_rate_pct = self._to_float(benchmark.get("annual_rate_pct"))
            annual_profit_usd = self._to_float(benchmark.get("annual_profit_usd"))
            daily_profit_usd = self._to_float(benchmark.get("daily_profit_usd"))
            if annual_rate_pct is None or annual_profit_usd is None or daily_profit_usd is None:
                continue
            benchmark_parts.append(
                f"{annual_rate_pct:.0f}%/yr => ${annual_profit_usd:.2f}/yr (~${daily_profit_usd:.2f}/day)"
            )
        if benchmark_parts:
            lines.append("Monzo-style yardsticks on the same bankroll: " + " | ".join(benchmark_parts))

        note = str(comparison.get("note", "")).strip()
        if note:
            lines.append(note)
        return lines

    def _build_strategy_coverage(
        self,
        *,
        latest_fitness_rows: list[dict[str, Any]],
        proposal_events: list[dict[str, Any]],
        training_volume_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        strategy_ids: list[str] = []
        seen: set[str] = set()
        for definition in build_strategy_registry():
            for profile in definition.build_profiles(self.config):
                strategy_id = str(profile.strategy_id)
                if strategy_id in seen:
                    continue
                strategy_ids.append(strategy_id)
                seen.add(strategy_id)

        fitness_by_strategy: dict[str, dict[str, Any]] = {}
        for row in latest_fitness_rows:
            strategy_id = str(row.get("strategy_id", "")).strip()
            if not strategy_id:
                continue
            existing = fitness_by_strategy.get(strategy_id)
            current_score = float(row.get("composite_fitness_score") or 0)
            if existing is None or current_score > float(
                existing.get("composite_fitness_score") or 0
            ):
                fitness_by_strategy[strategy_id] = row

        proposal_counts: dict[str, int] = {}
        last_proposed_at: dict[str, datetime] = {}
        for event in proposal_events:
            strategy_id = str(event.get("strategy_id", "")).strip()
            if not strategy_id:
                continue
            proposal_counts[strategy_id] = proposal_counts.get(strategy_id, 0) + 1
            proposed_at = event.get("proposed_at")
            if isinstance(proposed_at, datetime):
                previous = last_proposed_at.get(strategy_id)
                if previous is None or proposed_at > previous:
                    last_proposed_at[strategy_id] = proposed_at

        training_by_strategy: dict[str, dict[str, Any]] = {}
        for row in training_volume_rows:
            strategy_id = str(row.get("strategy_id", "")).strip()
            if strategy_id:
                training_by_strategy[strategy_id] = row

        rows: list[dict[str, Any]] = []
        for strategy_id in strategy_ids:
            fitness_row = fitness_by_strategy.get(strategy_id, {})
            training_row = training_by_strategy.get(strategy_id, {})
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "composite_fitness_score": float(
                        fitness_row.get("composite_fitness_score") or 0
                    ),
                    "fitness_rank": int(fitness_row.get("fitness_rank", 0) or 0),
                    "proposal_count_7d": int(proposal_counts.get(strategy_id, 0)),
                    "has_fitness_data": strategy_id in fitness_by_strategy,
                    "latest_checkpoint_code": str(
                        fitness_row.get("checkpoint_code", "")
                    ).strip(),
                    "win_rate": float(fitness_row.get("win_rate", 0) or 0),
                    "loss_rate": float(fitness_row.get("loss_rate", 0) or 0),
                    "sample_weight": float(fitness_row.get("sample_weight", 0) or 0),
                    "evaluated_proposals": int(
                        fitness_row.get("evaluated_proposals", 0) or 0
                    ),
                    "checkpoints_evaluated": int(
                        fitness_row.get("checkpoints_evaluated", 0) or 0
                    ),
                    "last_proposed_at": last_proposed_at.get(strategy_id),
                    "total_proposals_all": int(training_row.get("total_proposals", 0) or 0),
                    "evaluated_outcomes_all": int(
                        training_row.get("evaluated_outcomes", 0) or 0
                    ),
                    "first_proposed_at": training_row.get("first_proposed_at"),
                    "last_proposed_at_all": training_row.get("last_proposed_at"),
                }
            )
        rows.sort(
            key=lambda row: (
                1 if row.get("has_fitness_data") else 0,
                float(row.get("composite_fitness_score") or 0),
                int(row.get("evaluated_outcomes_all") or 0),
                int(row.get("total_proposals_all") or 0),
            ),
            reverse=True,
        )
        for index, row in enumerate(rows, start=1):
            row["rank_position"] = index
            row["sample_label"] = self._strategy_sample_label(row)
            row["ranking_reason"] = self._strategy_ranking_reason(row)
        return rows

    def _build_strategy_leaderboard_notes(
        self,
        *,
        strategy_rows: list[dict[str, Any]],
    ) -> list[str]:
        if not strategy_rows:
            return ["No strategy ranking data yet."]

        top_row = strategy_rows[0]
        lines = [
            (
                f"Top now: {top_row.get('strategy_id', '-')}"
                f" | fit={float(top_row.get('composite_fitness_score') or 0):.2f}"
                f" | checkpoint={top_row.get('latest_checkpoint_code') or '-'}"
            ),
            self._strategy_ranking_reason(top_row),
            (
                "Ranking order is based on each strategy's best current composite fitness row."
                " Strategies with no fitness data are shown last."
            ),
            "",
        ]

        for row in strategy_rows:
            fit_text = f"{float(row.get('composite_fitness_score') or 0):.2f}"
            checkpoint = str(row.get("latest_checkpoint_code", "") or "-")
            lines.append(
                (
                    f"{int(row.get('rank_position', 0) or 0)}. {row.get('strategy_id', '-')}"
                    f" | fit={fit_text}"
                    f" | checkpoint={checkpoint}"
                    f" | sample={row.get('sample_label', 'none')}"
                    f" | proposals={int(row.get('total_proposals_all', 0) or 0)}"
                    f" | outcomes={int(row.get('evaluated_outcomes_all', 0) or 0)}"
                )
            )
        return lines

    def _strategy_sample_label(self, row: dict[str, Any]) -> str:
        total_proposals = int(row.get("total_proposals_all", 0) or 0)
        evaluated = int(row.get("checkpoints_evaluated", 0) or 0)
        strongest_count = max(total_proposals, evaluated)
        if strongest_count >= 500:
            return "broad"
        if strongest_count >= 100:
            return "moderate"
        if strongest_count >= 20:
            return "early"
        if strongest_count > 0:
            return "small"
        return "none"

    def _strategy_ranking_reason(self, row: dict[str, Any]) -> str:
        strategy_id = str(row.get("strategy_id", "") or "-")
        if not row.get("has_fitness_data"):
            return f"{strategy_id} has no fitness data yet, so it is ranked below trained strategies."

        checkpoint = str(row.get("latest_checkpoint_code", "") or "-")
        fitness_score = float(row.get("composite_fitness_score") or 0)
        win_rate = float(row.get("win_rate", 0) or 0) * 100
        evaluated = int(row.get("checkpoints_evaluated", 0) or 0)
        total_proposals = int(row.get("total_proposals_all", 0) or 0)
        sample_label = str(row.get("sample_label", "none") or "none")
        return (
            f"{strategy_id} is ranked here because its best checkpoint is {checkpoint}"
            f" with composite fitness {fitness_score:.2f}, win rate {win_rate:.1f}%,"
            f" and {evaluated} evaluated checkpoints."
            f" Evidence level is {sample_label} with {total_proposals} all-time proposals."
        )

    def _build_strategy_hourly_activity(
        self,
        *,
        proposal_events: list[dict[str, Any]],
        strategy_id: str,
        now: datetime,
        hours: int,
    ) -> list[dict[str, Any]]:
        horizon = max(1, hours)
        start = now.astimezone().replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=horizon - 1
        )
        buckets: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for offset in range(horizon):
            bucket = start + timedelta(hours=offset)
            key = bucket.isoformat()
            counts[key] = 0
            buckets.append(
                {
                    "bucket": bucket,
                    "label": bucket.strftime("%H:%M"),
                    "count": 0,
                }
            )

        for event in proposal_events:
            if str(event.get("strategy_id", "")).strip() != strategy_id:
                continue
            proposed_at = event.get("proposed_at")
            if not isinstance(proposed_at, datetime):
                continue
            bucket = proposed_at.astimezone().replace(minute=0, second=0, microsecond=0)
            key = bucket.isoformat()
            if key in counts:
                counts[key] += 1

        for item in buckets:
            item["count"] = counts[item["bucket"].isoformat()]
        return buckets

    def _get_log_status(self, path: Path) -> LogFileStatus:
        if not path.exists():
            return LogFileStatus(
                path=path,
                exists=False,
                updated_at=None,
                last_line="",
            )

        updated_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        last_line = ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if stripped:
                        last_line = stripped
        except OSError:
            last_line = "<unreadable>"
        return LogFileStatus(
            path=path,
            exists=True,
            updated_at=updated_at,
            last_line=last_line,
        )

    def _render_log_line(self, label: str, status: LogFileStatus) -> str:
        if not status.exists:
            return f"- {label}: missing | path={status.path}"
        age_text = self._age_text(datetime.now().astimezone(), status.updated_at)
        snippet = status.last_line[:140] if status.last_line else "-"
        return (
            f"- {label}: updated={self._fmt_dt(status.updated_at)} | age={age_text} | "
            f"path={status.path} | last_line={snippet}"
        )

    def _heartbeat_status(self, *, now: datetime, started_at: datetime | None) -> str:
        if started_at is None:
            return "unknown"
        age = now - started_at
        expected = max(60, self.config.control_tick_interval_seconds)
        if age <= timedelta(seconds=expected * 3):
            return "healthy"
        if age <= timedelta(minutes=15):
            return "late"
        return "stale"

    def _age_text(self, now: datetime, value: datetime | None) -> str:
        if value is None:
            return "-"
        delta = now - value
        total_seconds = max(0, int(delta.total_seconds()))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _fmt_dt(self, value: datetime | None) -> str:
        if value is None:
            return "-"
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _fmt_seconds(self, value: Any) -> str:
        try:
            return f"{float(value):.3f}s"
        except (TypeError, ValueError):
            return "-"

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _first_list_item(self, value: Any) -> str:
        if not isinstance(value, list) or not value:
            return ""
        first = value[0]
        return str(first).upper() if first else ""

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    def _build_source_cost_rows(
        self,
        rows: list[Any],
        *,
        usd_to_gbp: float | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "source": row.source,
                "request_count": row.request_count,
                "success_count": row.success_count,
                "error_count": row.error_count,
                "estimated_cost_usd": round(float(row.estimated_cost_usd), 6),
                "estimated_cost_gbp": self._convert_cost_to_gbp(
                    row.estimated_cost_usd,
                    usd_to_gbp=usd_to_gbp,
                ),
            }
            items.append(item)
        items.sort(
            key=lambda item: (
                float(item.get("estimated_cost_usd", 0) or 0),
                int(item.get("request_count", 0) or 0),
                str(item.get("source", "")),
            ),
            reverse=True,
        )
        return items

    def _build_cost_day_snapshot(
        self,
        *,
        usage_date: Any,
        rows: list[Any],
        usd_to_gbp: float | None,
    ) -> dict[str, Any]:
        total_cost_usd = round(self.usage_ledger.total_estimated_cost_usd(rows), 6)
        return {
            "usage_date": usage_date.isoformat() if hasattr(usage_date, "isoformat") else str(usage_date),
            "estimated_cost_usd": total_cost_usd,
            "estimated_cost_gbp": self._convert_cost_to_gbp(
                total_cost_usd,
                usd_to_gbp=usd_to_gbp,
            ),
            "request_count": self.usage_ledger.total_requests(rows),
            "source_count": len(rows),
        }

    def _latest_usd_to_gbp_rate(self) -> float | None:
        latest_fx = self.usage_ledger.get_latest_fx_reference(source="ecb_fx")
        if latest_fx is None:
            return None
        return self._to_float(latest_fx.get("usd_to_gbp"))

    def _convert_cost_to_gbp(
        self,
        value_usd: Any,
        *,
        usd_to_gbp: float | None,
    ) -> float | None:
        numeric = self._to_float(value_usd)
        if numeric is None or usd_to_gbp is None:
            return None
        return round(numeric * usd_to_gbp, 6)

    def _native_value_to_gbp(
        self,
        value: Any,
        *,
        currency: str,
        usd_to_gbp: float | None,
    ) -> float | None:
        numeric = self._to_float(value)
        if numeric is None:
            return None
        if currency.upper() == "GBP":
            return round(numeric, 6)
        if currency.upper() == "USD":
            return self._convert_cost_to_gbp(numeric, usd_to_gbp=usd_to_gbp)
        return None

    def _estimate_order_notional_usd(self, order: dict[str, Any]) -> float | None:
        notional = self._to_float(order.get("notional"))
        if notional is not None and notional > 0:
            return notional

        qty = self._to_float(order.get("qty"))
        if qty is None or qty <= 0:
            return None

        for key in ("limit_price", "filled_avg_price", "stop_price"):
            price = self._to_float(order.get(key))
            if price is not None and price > 0:
                return round(qty * price, 6)
        return None

    def _pricing_configured(self) -> bool:
        return any(
            self._provider_pricing_configured(source)
            for source in self.config.provider_pricing
        )

    def _provider_pricing_configured(self, source: str) -> bool:
        pricing = self.config.provider_pricing.get(source)
        if pricing is None:
            return False
        return any(
            float(value or 0) > 0
            for value in (
                pricing.cost_per_request_usd,
                pricing.input_cost_per_million_units_usd,
                pricing.output_cost_per_million_units_usd,
            )
        )

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _pct_from_ratio(self, value: Any) -> float | None:
        numeric = self._to_float(value)
        if numeric is None:
            return None
        return round(numeric * 100.0, 4)

    def _fmt_number(self, value: Any, *, decimals: int) -> str:
        numeric = self._to_float(value)
        if numeric is None:
            return "-"
        return f"{numeric:.{decimals}f}"

    def _fmt_currency_prefix(self, value: Any, prefix: str, decimals: int) -> str:
        numeric = self._to_float(value)
        if numeric is None:
            return "-"
        return f"{prefix}{numeric:.{decimals}f}"

    def _broker_label(self, broker_id: str) -> str:
        normalized = str(broker_id or "").strip().lower()
        return {
            "alpaca_paper": "Alpaca Paper",
            "alpaca_live": "Alpaca Live",
            "ig_spreadbet": "IG Spread Betting",
        }.get(normalized, normalized or "unknown broker")

    def _order_status_is_open(self, value: str) -> bool:
        return value.strip().lower() in {
            "new",
            "accepted",
            "pending_new",
            "accepted_for_bidding",
            "partially_filled",
            "held",
            "pending_replace",
            "pending_cancel",
        }

    def _find_latest_entry_plan(
        self,
        *,
        symbol: str,
        orders: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        symbol_upper = symbol.upper()
        for order in orders:
            if not isinstance(order, dict):
                continue
            if str(order.get("symbol", "")).upper() != symbol_upper:
                continue
            if str(order.get("side", "")).lower() != "buy":
                continue
            raw = self._as_dict(order.get("raw_json"))
            if not any(
                value not in (None, "", 0, 0.0)
                for value in (
                    raw.get("planned_stop_loss_price"),
                    raw.get("planned_take_profit_price"),
                    raw.get("planned_holding_window_minutes"),
                    order.get("stop_loss_price"),
                    order.get("take_profit_price"),
                )
            ):
                continue
            return order
        return None
