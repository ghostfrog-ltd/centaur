from __future__ import annotations

from datetime import datetime
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class AttentionStatusReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def render(self) -> str:
        alerts = self.usage_ledger.list_open_attention_alerts(limit=200)
        lines = ["Attention Status"]
        if not alerts:
            lines.append("open_alerts=0")
            return "\n".join(lines)
        lines.append(f"open_alerts={len(alerts)}")
        for alert in alerts:
            evidence = dict(alert.get("evidence_summary_json", {}) or {})
            source = str(evidence.get("source", "") or "")
            if not source and str(alert.get("event_type", "")) == "research_cycle_failure":
                source = "real_heartbeat"
            why = str(evidence.get("open_reason", "") or "")
            if not why and str(alert.get("event_type", "")) == "research_cycle_failure":
                why = "Waiting for a later real heartbeat research cycle to produce usable decisions."
            lines.append(
                f"event_id={alert.get('event_id', '-')}"
                f" | event_type={alert.get('event_type', '-')}"
                f" | source={source or '-'}"
                f" | tick_id={evidence.get('tick_id', '-')}"
                f" | cycle_id={evidence.get('cycle_id', '-')}"
            )
            lines.append(
                f"- age={self._age(alert.get('created_at'))}"
                f" | reminder_count={int(alert.get('slack_send_count', 0) or 0)}"
                f" | why_still_open={why or '-'}"
            )
            lines.append(
                f"- acknowledge=python main.py --alert-ack --event-id {alert.get('event_id', '-')}"
            )
            lines.append(
                f"- resolve=python main.py --alert-resolve --event-id {alert.get('event_id', '-')}"
                ' --reason "manual resolution"'
            )
        return "\n".join(lines)

    def _age(self, value: Any) -> str:
        if not isinstance(value, datetime):
            return "-"
        seconds = max(0, int((datetime.now().astimezone() - value).total_seconds()))
        hours, rem = divmod(seconds, 3600)
        minutes, _ = divmod(rem, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
