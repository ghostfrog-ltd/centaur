from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.framework.reporting.self_improvement_status import SelfImprovementStatusReport
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class OperatorSummaryReport:
    """Compact operator-facing health summary for CLI, Slack, and email.

    This is read-only. It reuses persisted self-improvement diagnostics so the
    operator sees one consistent explanation of system health, freshness,
    promotion distance, and why no trades are happening.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        try:
            report = SelfImprovementStatusReport(
                config=self.config,
                usage_ledger=self.usage_ledger,
            ).build_report()
        except AttributeError as exc:
            if not self._is_missing_ledger_method_error(exc):
                raise
            return self._fallback_report_for_lightweight_ledger(exc)
        learning = dict(report.get("learning", {}) or {})
        quality = dict(report.get("evidence_quality", {}) or {})
        freshness = dict(report.get("freshness_diagnostics", {}) or {})
        stuck = dict(report.get("stuck_analysis", {}) or {})
        closest = list(report.get("closest_to_promotion", []) or [])
        closest_item = closest[0] if closest else {}
        now = datetime.now().astimezone()
        latest_cycle_dt = self._parse_dt(report.get("learning", {}).get("latest_persisted_cycle_time"))
        latest_tick = self._latest_tick_run()
        latest_tick_dt = self._parse_dt((latest_tick or {}).get("started_at"))
        latest_tick_age = self._format_timedelta(now - latest_tick_dt) if latest_tick_dt else "unknown"
        heartbeat_running = self._heartbeat_running(now=now, latest_tick_dt=latest_tick_dt)
        next_expected_cycle_dt = (
            latest_cycle_dt
            + timedelta(minutes=int(getattr(self.config, "research_cycle_min_interval_minutes", 60) or 60))
            if latest_cycle_dt
            else None
        )
        research_cycle_overdue = bool(next_expected_cycle_dt and now > next_expected_cycle_dt)
        latest_cycle_age = self._format_timedelta(now - latest_cycle_dt) if latest_cycle_dt else "unknown"
        latest_cycle_fresh = (
            "yes"
            if latest_cycle_dt and next_expected_cycle_dt and now <= next_expected_cycle_dt
            else ("no" if latest_cycle_dt else "unknown")
        )
        fresh_data = str(freshness.get("fresh_historical_bars_detected", "unknown"))
        provider_error_count = int(freshness.get("provider_error_count", 0) or 0)
        latest_cycle_data_fresh_when_run = (
            "yes"
            if str(freshness.get("pre_replay_refresh_ran", "no")) == "yes"
            and provider_error_count == 0
            else ("no" if provider_error_count > 0 else "unknown")
        )
        data_freshness_status = self._data_freshness_status(
            fresh_data=fresh_data,
            latest_cycle_fresh=latest_cycle_fresh,
            research_cycle_overdue=research_cycle_overdue,
            provider_error_count=provider_error_count,
        )
        health_failure_reasons = self._health_failure_reasons(
            heartbeat_running=heartbeat_running,
            data_freshness_status=data_freshness_status,
            research_cycle_overdue=research_cycle_overdue,
            provider_error_count=provider_error_count,
        )

        system_healthy = (
            str(report.get("status", "error")) == "ok"
            and provider_error_count == 0
            and heartbeat_running == "yes"
            and not research_cycle_overdue
            and data_freshness_status not in {"stale_overdue", "provider_error"}
        )
        strategy_evidence_stuck = "yes" if bool(stuck.get("strategy_evidence_stuck")) else "no"
        replay_windows_advancing = str(stuck.get("replay_window_advancing", "unknown"))
        strategy_evidence_improving = (
            str(quality.get("evidence_quality_status", "flat")) == "improving"
        )
        why_no_trades = self._build_explanation(
            report=report,
            system_healthy=system_healthy,
            data_freshness_status=data_freshness_status,
            heartbeat_running=heartbeat_running,
            research_cycle_overdue=research_cycle_overdue,
            latest_cycle_fresh=latest_cycle_fresh,
            next_expected_cycle_dt=next_expected_cycle_dt,
            strategy_evidence_stuck=strategy_evidence_stuck,
        )

        return {
            "status": "ok",
            "system_healthy": "yes" if system_healthy else "no",
            "system_health_reason": (
                "healthy" if system_healthy else ",".join(health_failure_reasons) or "unhealthy"
            ),
            "fresh_data": fresh_data,
            "data_freshness_status": data_freshness_status,
            "current_report_time": now.isoformat(),
            "latest_cycle_age": latest_cycle_age,
            "latest_cycle_data_fresh_when_run": latest_cycle_data_fresh_when_run,
            "latest_cycle_fresh_at_report_time": latest_cycle_fresh,
            "next_expected_research_cycle_time": (
                next_expected_cycle_dt.isoformat() if next_expected_cycle_dt else "-"
            ),
            "research_cycle_overdue": "yes" if research_cycle_overdue else "no",
            "heartbeat_running": heartbeat_running,
            "last_heartbeat_tick_time": (latest_tick_dt.isoformat() if latest_tick_dt else "-"),
            "last_heartbeat_tick_age": latest_tick_age,
            "health_failure_reasons": ",".join(health_failure_reasons) if health_failure_reasons else "-",
            "real_scheduled_cycles_in_lookback": int(
                learning.get("real_research_cycles_in_lookback", 0) or 0
            ),
            "replay_windows_advancing": replay_windows_advancing,
            "strategy_evidence_improving": "yes" if strategy_evidence_improving else "no",
            "strategy_evidence_stuck": strategy_evidence_stuck,
            "closest_to_promotion": {
                "strategy_id": closest_item.get("strategy_id", "-"),
                "profile_id": closest_item.get("profile_id", "-"),
                "checkpoint": closest_item.get("best_checkpoint", "-"),
                "distance_to_paper_candidate": closest_item.get(
                    "distance_to_paper_candidate", "-"
                ),
            },
            "why_no_trades_happening": why_no_trades,
            "broker_orders_created": int(learning.get("broker_orders_created", 0) or 0),
            "live_orders_created": int(learning.get("live_orders_created", 0) or 0),
            "auto_paper_approved": int(learning.get("auto_paper_approved", 0) or 0),
            "auto_live_approved": int(learning.get("auto_live_approved", 0) or 0),
            "self_improvement_status": str(report.get("self_improvement_status", "-") or "-"),
            "dominant_blocker": str(stuck.get("dominant_blocker", "-") or "-"),
            "latest_cycle_origin": str(learning.get("latest_persisted_cycle_origin", "-") or "-"),
            "latest_cycle_time": str(learning.get("latest_persisted_cycle_time", "-") or "-"),
            "replay_selection_mode": str(freshness.get("replay_selection_mode", "-") or "-"),
            "rolling_replay_cursor_enabled": str(
                freshness.get("rolling_replay_cursor_enabled", "-") or "-"
            ),
            "learning_progress_this_cycle": str(
                freshness.get("learning_progress_this_cycle", "-") or "-"
            ),
            "reason_no_learning_progress": str(
                freshness.get("reason_no_learning_progress", "-") or "-"
            ),
            "selected_anchor_time_by_bucket": str(
                freshness.get("selected_anchor_time_by_bucket", "-") or "-"
            ),
            "freshness_gain_vs_global_by_bucket": str(
                freshness.get("freshness_gain_vs_global_by_bucket", "-") or "-"
            ),
        }

    def _latest_tick_run(self) -> dict[str, Any] | None:
        getter = getattr(self.usage_ledger, "get_latest_tick_run", None)
        if not callable(getter):
            return None
        try:
            row = getter()
        except Exception:
            return None
        return row if isinstance(row, dict) else None

    def _parse_dt(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text or text == "-":
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _format_timedelta(self, value: timedelta) -> str:
        seconds = max(0, int(value.total_seconds()))
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        if days:
            return f"{days}d{hours}h{minutes}m{secs}s"
        if hours:
            return f"{hours}h{minutes}m{secs}s"
        if minutes:
            return f"{minutes}m{secs}s"
        return f"{secs}s"

    def _heartbeat_running(self, *, now: datetime, latest_tick_dt: datetime | None) -> str:
        if latest_tick_dt is None:
            return "unknown"
        interval = max(60, int(getattr(self.config, "control_tick_interval_seconds", 60) or 60))
        allowed_age = max(300, interval * 3)
        return "yes" if (now - latest_tick_dt).total_seconds() <= allowed_age else "no"

    def _health_failure_reasons(
        self,
        *,
        heartbeat_running: str,
        data_freshness_status: str,
        research_cycle_overdue: bool,
        provider_error_count: int,
    ) -> list[str]:
        reasons: list[str] = []
        if heartbeat_running == "no":
            reasons.append("heartbeat_not_running")
        if research_cycle_overdue:
            reasons.append("research_cycle_overdue")
        if provider_error_count > 0:
            reasons.append("provider_errors_present")
        if data_freshness_status == "stale_overdue":
            reasons.append("data_stale_overdue")
        if data_freshness_status == "provider_error":
            reasons.append("provider_error")
        return reasons

    def _data_freshness_status(
        self,
        *,
        fresh_data: str,
        latest_cycle_fresh: str,
        research_cycle_overdue: bool,
        provider_error_count: int,
    ) -> str:
        if provider_error_count > 0:
            return "provider_error"
        if fresh_data == "yes":
            return "fresh_now"
        if fresh_data == "no" and research_cycle_overdue:
            return "stale_overdue"
        if fresh_data == "no" and latest_cycle_fresh == "yes":
            return "stale_between_cycles"
        if fresh_data == "no":
            return "stale_overdue"
        return "unknown"

    def _build_explanation(
        self,
        *,
        report: dict[str, Any],
        system_healthy: bool,
        data_freshness_status: str,
        heartbeat_running: str,
        research_cycle_overdue: bool,
        latest_cycle_fresh: str,
        next_expected_cycle_dt: datetime | None,
        strategy_evidence_stuck: str,
    ) -> str:
        stuck = dict(report.get("stuck_analysis", {}) or {})
        dominant_blocker = str(stuck.get("dominant_blocker", "-") or "-")
        if data_freshness_status == "provider_error":
            return (
                "Centaur is not currently collecting fresh replay evidence because provider errors blocked refresh. "
                "Investigate the provider failure before judging strategy improvement."
            )
        if data_freshness_status == "stale_overdue" or research_cycle_overdue:
            return (
                "Centaur's latest scheduled research cycle is stale or overdue. "
                "Investigate launchd/heartbeat/research interval before judging strategy improvement."
            )
        if data_freshness_status == "stale_between_cycles" and heartbeat_running == "yes":
            return (
                "Centaur is running normally and the next research cycle is not overdue. "
                "Current data is stale between scheduled research cycles, and strategy evidence remains stuck because no profile is promotion eligible."
            )
        if heartbeat_running == "yes" and latest_cycle_fresh == "yes" and strategy_evidence_stuck == "yes":
            return (
                "Centaur's heartbeat is running, but no newer research cycle is due yet. "
                "Strategy evidence remains stuck because no profile is promotion eligible."
            )
        if system_healthy:
            return (
                "Centaur is operating correctly and collecting fresh replay evidence, "
                "but strategy evidence is not improving."
            )
        if next_expected_cycle_dt is not None:
            return (
                "Centaur's latest persisted cycle was healthy when recorded, but current report-time "
                "health is degraded or stale. "
                f"Next expected research cycle is {next_expected_cycle_dt.isoformat()}."
            )
        return (
            "Centaur's current report-time health is unclear. "
            f"The dominant blocker is {dominant_blocker}."
        )

    def _is_missing_ledger_method_error(self, exc: AttributeError) -> bool:
        text = str(exc)
        return "object has no attribute" in text and "list_" in text

    def _fallback_report_for_lightweight_ledger(
        self,
        exc: AttributeError,
    ) -> dict[str, Any]:
        reason = f"operator_summary_degraded_missing_usage_ledger_method:{exc}"
        return {
            "status": "degraded",
            "system_healthy": "unknown",
            "system_health_reason": "unknown",
            "fresh_data": "unknown",
            "data_freshness_status": "unknown",
            "current_report_time": "-",
            "latest_cycle_age": "unknown",
            "latest_cycle_data_fresh_when_run": "unknown",
            "latest_cycle_fresh_at_report_time": "unknown",
            "next_expected_research_cycle_time": "-",
            "research_cycle_overdue": "unknown",
            "heartbeat_running": "unknown",
            "last_heartbeat_tick_time": "-",
            "last_heartbeat_tick_age": "unknown",
            "health_failure_reasons": reason,
            "real_scheduled_cycles_in_lookback": 0,
            "replay_windows_advancing": "unknown",
            "strategy_evidence_improving": "unknown",
            "strategy_evidence_stuck": "unknown",
            "closest_to_promotion": {
                "strategy_id": "-",
                "profile_id": "-",
                "checkpoint": "-",
                "distance_to_paper_candidate": "-",
            },
            "why_no_trades_happening": (
                "Operator summary is running in a lightweight test/runtime context "
                "without full persisted self-improvement query support."
            ),
            "broker_orders_created": int(
                getattr(self.usage_ledger, "paper_trade_orders_recorded", 0) or 0
            ),
            "live_orders_created": int(
                getattr(self.usage_ledger, "live_trade_orders_recorded", 0) or 0
            ),
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            "self_improvement_status": "unknown",
            "dominant_blocker": "-",
            "latest_cycle_origin": "-",
            "latest_cycle_time": "-",
            "replay_selection_mode": "-",
            "selected_anchor_time_by_bucket": "-",
            "freshness_gain_vs_global_by_bucket": "-",
            "degraded_reason": reason,
        }

    def render(self) -> str:
        report = self.build_report()
        closest = dict(report.get("closest_to_promotion", {}) or {})
        lines = [
            "Operator Summary",
            f"system_healthy={report.get('system_healthy', '-')}",
            f"system_health_reason={report.get('system_health_reason', '-')}",
            f"fresh_data={report.get('fresh_data', '-')}",
            f"data_freshness_status={report.get('data_freshness_status', '-')}",
            f"current_report_time={report.get('current_report_time', '-')}",
            f"latest_cycle_age={report.get('latest_cycle_age', '-')}",
            "latest_cycle_data_fresh_when_run="
            f"{report.get('latest_cycle_data_fresh_when_run', '-')}",
            "latest_cycle_fresh_at_report_time="
            f"{report.get('latest_cycle_fresh_at_report_time', '-')}",
            "next_expected_research_cycle_time="
            f"{report.get('next_expected_research_cycle_time', '-')}",
            f"research_cycle_overdue={report.get('research_cycle_overdue', '-')}",
            f"heartbeat_running={report.get('heartbeat_running', '-')}",
            f"last_heartbeat_tick_time={report.get('last_heartbeat_tick_time', '-')}",
            f"last_heartbeat_tick_age={report.get('last_heartbeat_tick_age', '-')}",
            f"health_failure_reasons={report.get('health_failure_reasons', '-')}",
            "real_scheduled_cycles_in_lookback="
            f"{report.get('real_scheduled_cycles_in_lookback', '-')}",
            f"replay_windows_advancing={report.get('replay_windows_advancing', '-')}",
            "strategy_evidence_improving="
            f"{report.get('strategy_evidence_improving', '-')}",
            "strategy_evidence_stuck="
            f"{report.get('strategy_evidence_stuck', '-')}",
            f"self_improvement_status={report.get('self_improvement_status', '-')}",
            f"dominant_blocker={report.get('dominant_blocker', '-')}",
            f"closest_strategy_id={closest.get('strategy_id', '-')}",
            f"closest_profile_id={closest.get('profile_id', '-')}",
            f"closest_checkpoint={closest.get('checkpoint', '-')}",
            "closest_distance_to_paper_candidate="
            f"{closest.get('distance_to_paper_candidate', '-')}",
            "why_no_trades_happening="
            f"{report.get('why_no_trades_happening', '-')}",
            f"broker_orders_created={report.get('broker_orders_created', 0)}",
            f"live_orders_created={report.get('live_orders_created', 0)}",
            f"auto_paper_approved={report.get('auto_paper_approved', 0)}",
            f"auto_live_approved={report.get('auto_live_approved', 0)}",
            f"latest_cycle_origin={report.get('latest_cycle_origin', '-')}",
            f"latest_cycle_time={report.get('latest_cycle_time', '-')}",
            f"replay_selection_mode={report.get('replay_selection_mode', '-')}",
            "rolling_replay_cursor_enabled="
            f"{report.get('rolling_replay_cursor_enabled', '-')}",
            "learning_progress_this_cycle="
            f"{report.get('learning_progress_this_cycle', '-')}",
            "reason_no_learning_progress="
            f"{report.get('reason_no_learning_progress', '-')}",
            "selected_anchor_time_by_bucket="
            f"{report.get('selected_anchor_time_by_bucket', '-')}",
            "freshness_gain_vs_global_by_bucket="
            f"{report.get('freshness_gain_vs_global_by_bucket', '-')}",
        ]
        return "\n".join(lines)

    def render_slack(self) -> str:
        report = self.build_report()
        closest = dict(report.get("closest_to_promotion", {}) or {})
        lines = [
            "*PROJECT CENTAUR OPERATOR SUMMARY*",
            f"*System healthy:* {report.get('system_healthy', '-')}",
            f"*System health reason:* {report.get('system_health_reason', '-')}",
            f"*Fresh data:* {report.get('fresh_data', '-')}",
            f"*Data freshness:* {report.get('data_freshness_status', '-')}",
            f"*Current report time:* {report.get('current_report_time', '-')}",
            f"*Latest cycle age:* {report.get('latest_cycle_age', '-')}",
            "*Latest cycle data fresh when run:* "
            f"{report.get('latest_cycle_data_fresh_when_run', '-')}",
            "*Latest cycle fresh at report time:* "
            f"{report.get('latest_cycle_fresh_at_report_time', '-')}",
            "*Next expected research cycle:* "
            f"{report.get('next_expected_research_cycle_time', '-')}",
            f"*Research cycle overdue:* {report.get('research_cycle_overdue', '-')}",
            f"*Heartbeat running:* {report.get('heartbeat_running', '-')}",
            f"*Last heartbeat tick:* {report.get('last_heartbeat_tick_time', '-')}",
            f"*Last heartbeat tick age:* {report.get('last_heartbeat_tick_age', '-')}",
            f"*Health failure reasons:* {report.get('health_failure_reasons', '-')}",
            "*Real scheduled cycles in lookback:* "
            f"{report.get('real_scheduled_cycles_in_lookback', '-')}",
            f"*Replay windows advancing:* {report.get('replay_windows_advancing', '-')}",
            "*Strategy evidence improving:* "
            f"{report.get('strategy_evidence_improving', '-')}",
            "*Strategy evidence stuck:* "
            f"{report.get('strategy_evidence_stuck', '-')}",
            f"*Closest to promotion:* {closest.get('strategy_id', '-')}/{closest.get('profile_id', '-')}"
            f" @ {closest.get('checkpoint', '-')}"
            f" distance={closest.get('distance_to_paper_candidate', '-')}",
            f"*Why no trades:* {report.get('why_no_trades_happening', '-')}",
            "*Approvals/orders:* "
            f"broker_orders_created={report.get('broker_orders_created', 0)}, "
            f"live_orders_created={report.get('live_orders_created', 0)}, "
            f"auto_paper_approved={report.get('auto_paper_approved', 0)}, "
            f"auto_live_approved={report.get('auto_live_approved', 0)}",
        ]
        return "\n".join(lines)

    def render_email(self) -> str:
        report = self.build_report()
        closest = dict(report.get("closest_to_promotion", {}) or {})
        header = [
            "============================================================",
            "||            PROJECT CENTAUR OPERATOR SUMMARY            ||",
            "============================================================",
        ]
        body = [
            f"System healthy: {report.get('system_healthy', '-')}",
            f"System health reason: {report.get('system_health_reason', '-')}",
            f"Collecting fresh data: {report.get('fresh_data', '-')}",
            f"Data freshness: {report.get('data_freshness_status', '-')}",
            f"Current report time: {report.get('current_report_time', '-')}",
            f"Latest cycle age: {report.get('latest_cycle_age', '-')}",
            "Latest cycle data fresh when run: "
            f"{report.get('latest_cycle_data_fresh_when_run', '-')}",
            "Latest cycle fresh at report time: "
            f"{report.get('latest_cycle_fresh_at_report_time', '-')}",
            "Next expected research cycle time: "
            f"{report.get('next_expected_research_cycle_time', '-')}",
            f"Research cycle overdue: {report.get('research_cycle_overdue', '-')}",
            f"Heartbeat running: {report.get('heartbeat_running', '-')}",
            f"Last heartbeat tick time: {report.get('last_heartbeat_tick_time', '-')}",
            f"Last heartbeat tick age: {report.get('last_heartbeat_tick_age', '-')}",
            f"Health failure reasons: {report.get('health_failure_reasons', '-')}",
            "Real scheduled cycles in lookback: "
            f"{report.get('real_scheduled_cycles_in_lookback', '-')}",
            f"Replay windows advancing: {report.get('replay_windows_advancing', '-')}",
            "Strategy evidence improving: "
            f"{report.get('strategy_evidence_improving', '-')}",
            f"Strategy evidence stuck: {report.get('strategy_evidence_stuck', '-')}",
            f"Self improvement status: {report.get('self_improvement_status', '-')}",
            f"Dominant blocker: {report.get('dominant_blocker', '-')}",
            "Closest to promotion: "
            f"{closest.get('strategy_id', '-')}/{closest.get('profile_id', '-')}"
            f" @ {closest.get('checkpoint', '-')}"
            f" (distance {closest.get('distance_to_paper_candidate', '-')})",
            "",
            "Why no trades are happening:",
            f"{report.get('why_no_trades_happening', '-')}",
            "",
            "Safety state:",
            f"- broker_orders_created={report.get('broker_orders_created', 0)}",
            f"- live_orders_created={report.get('live_orders_created', 0)}",
            f"- auto_paper_approved={report.get('auto_paper_approved', 0)}",
            f"- auto_live_approved={report.get('auto_live_approved', 0)}",
            "",
            f"Latest cycle origin: {report.get('latest_cycle_origin', '-')}",
            f"Latest cycle time: {report.get('latest_cycle_time', '-')}",
            f"Replay selection mode: {report.get('replay_selection_mode', '-')}",
            "Selected anchor time by bucket: "
            f"{report.get('selected_anchor_time_by_bucket', '-')}",
            "Freshness gain vs global by bucket: "
            f"{report.get('freshness_gain_vs_global_by_bucket', '-')}",
        ]
        footer = [
            "============================================================",
            "||  This message is informational and does not change     ||",
            "||  thresholds, approvals, broker routing, or execution. ||",
            "============================================================",
        ]
        return "\n".join([*header, *body, *footer])

    def email_subject(self) -> str:
        report = self.build_report()
        status = str(report.get("self_improvement_status", "-") or "-")
        cycle_time = str(report.get("latest_cycle_time", "-") or "-")
        return f"Project Centaur operator summary [{status}] {cycle_time}"
