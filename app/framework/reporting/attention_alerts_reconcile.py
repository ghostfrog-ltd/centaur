from __future__ import annotations

from datetime import datetime
from typing import Any

from app.framework.runtime.attention_alerts import (
    approval_request_id,
    build_event_id,
    create_attention_alert,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

APPROVAL_RELATED_EVENT_TYPES = {
    "paper_approval_missing",
    "paper_candidate",
    "live_execution_requested_while_disabled",
}
PAPER_APPROVAL_EVENT_TYPES = {"paper_approval_missing", "paper_candidate"}


class AttentionAlertsReconcileReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def reconcile(self) -> dict[str, Any]:
        alerts = list(self.usage_ledger.list_open_attention_alerts(limit=200) or [])
        promotions = list(getattr(self.usage_ledger, "list_strategy_promotions", lambda: [])() or [])
        promotions_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        promotions_by_strategy: dict[str, list[dict[str, Any]]] = {}
        for promotion in promotions:
            if not isinstance(promotion, dict):
                continue
            strategy_id = str(promotion.get("strategy_id", "") or "").strip()
            profile_id = str(promotion.get("profile_id", "") or "").strip()
            if not strategy_id or not profile_id:
                continue
            promotions_by_pair[(strategy_id, profile_id)] = promotion
            promotions_by_strategy.setdefault(strategy_id, []).append(promotion)

        before_blank = self._count_blank_profile_open_alerts(alerts)
        resolved = 0
        converted = 0
        remapped = 0
        inspected = 0

        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            event_type = str(alert.get("event_type", "") or "").strip()
            if event_type not in APPROVAL_RELATED_EVENT_TYPES:
                continue
            inspected += 1
            strategy_id = str(alert.get("strategy_id", "") or "").strip()
            profile_id = str(alert.get("profile_id", "") or "").strip()
            event_id = str(alert.get("event_id", "") or "").strip()
            if not event_id:
                continue

            if not profile_id:
                mapped = self._safe_map_profile(
                    strategy_id=strategy_id,
                    promotions_by_strategy=promotions_by_strategy,
                )
                self.usage_ledger.resolve_attention_alert(
                    event_id=event_id,
                    status="resolved",
                    reason=f"reconciled_blank_profile_{event_type}",
                )
                resolved += 1
                if mapped is not None:
                    mapped_strategy_id, mapped_profile_id = mapped
                    promotion = promotions_by_pair.get((mapped_strategy_id, mapped_profile_id), {})
                    if event_type in PAPER_APPROVAL_EVENT_TYPES and self._promotion_supports_paper_alert(promotion):
                        self._create_paper_alert(
                            strategy_id=mapped_strategy_id,
                            profile_id=mapped_profile_id,
                            source_alert=alert,
                        )
                        remapped += 1
                        continue
                    if event_type == "live_execution_requested_while_disabled":
                        self._create_live_alert(
                            strategy_id=mapped_strategy_id,
                            profile_id=mapped_profile_id,
                            source_alert=alert,
                        )
                        remapped += 1
                        continue
                    self._create_diagnostic_alert(
                        diagnostic_type=f"{event_type}_stale",
                        strategy_id=mapped_strategy_id,
                        profile_id=mapped_profile_id,
                        title=f"{event_type} alert no longer actionable",
                        message=(
                            f"The original {event_type} alert was blank-profile and mapped to "
                            f"{mapped_strategy_id}/{mapped_profile_id}, but the current promotion "
                            "stage does not support a normal actionable approval alert."
                        ),
                        source_alert=alert,
                    )
                    converted += 1
                    continue
                self._create_diagnostic_alert(
                    diagnostic_type=f"{event_type}_invalid",
                    strategy_id=strategy_id,
                    profile_id="",
                    title=f"{event_type} alert missing profile identity",
                    message=(
                        f"The original {event_type} alert remained blank-profile and could not be "
                        "mapped safely to a current strategy/profile promotion row."
                    ),
                    source_alert=alert,
                )
                converted += 1
                continue

            if event_type in PAPER_APPROVAL_EVENT_TYPES:
                promotion = promotions_by_pair.get((strategy_id, profile_id))
                current_stage = str((promotion or {}).get("stage", "") or "missing_promotion")
                if not self._promotion_supports_paper_alert(promotion):
                    self.usage_ledger.resolve_attention_alert(
                        event_id=event_id,
                        status="resolved",
                        reason=f"reconciled_non_actionable_stage_{current_stage}",
                    )
                    resolved += 1
                    continue

        after_alerts = list(self.usage_ledger.list_open_attention_alerts(limit=200) or [])
        return {
            "status": "ok",
            "inspected_open_approval_related_alerts": inspected,
            "open_blank_profile_approval_related_alerts_before": before_blank,
            "open_blank_profile_approval_related_alerts_after": self._count_blank_profile_open_alerts(
                after_alerts
            ),
            "resolved_alerts": resolved,
            "converted_to_diagnostic_alerts": converted,
            "remapped_alerts": remapped,
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.reconcile()
        return "\n".join(
            [
                "Attention Alerts Reconcile",
                f"status={report.get('status', '-')}",
                "inspected_open_approval_related_alerts="
                f"{int(report.get('inspected_open_approval_related_alerts', 0) or 0)}",
                "open_blank_profile_approval_related_alerts_before="
                f"{int(report.get('open_blank_profile_approval_related_alerts_before', 0) or 0)}",
                "open_blank_profile_approval_related_alerts_after="
                f"{int(report.get('open_blank_profile_approval_related_alerts_after', 0) or 0)}",
                f"resolved_alerts={int(report.get('resolved_alerts', 0) or 0)}",
                "converted_to_diagnostic_alerts="
                f"{int(report.get('converted_to_diagnostic_alerts', 0) or 0)}",
                f"remapped_alerts={int(report.get('remapped_alerts', 0) or 0)}",
            ]
        )

    def _count_blank_profile_open_alerts(self, alerts: list[dict[str, Any]]) -> int:
        return sum(
            1
            for alert in alerts
            if str(alert.get("event_type", "") or "").strip() in APPROVAL_RELATED_EVENT_TYPES
            and not str(alert.get("profile_id", "") or "").strip()
            and str(alert.get("attention_status", "") or "open").strip() == "open"
        )

    def _safe_map_profile(
        self,
        *,
        strategy_id: str,
        promotions_by_strategy: dict[str, list[dict[str, Any]]],
    ) -> tuple[str, str] | None:
        normalized_strategy_id = str(strategy_id or "").strip()
        if not normalized_strategy_id:
            return None
        matches = [
            item
            for item in promotions_by_strategy.get(normalized_strategy_id, [])
            if str(item.get("profile_id", "") or "").strip()
        ]
        if len(matches) != 1:
            return None
        return normalized_strategy_id, str(matches[0].get("profile_id", "") or "").strip()

    def _promotion_supports_paper_alert(self, promotion: dict[str, Any] | None) -> bool:
        return isinstance(promotion, dict) and str(promotion.get("stage", "") or "").strip() == "paper_candidate"

    def _create_paper_alert(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        source_alert: dict[str, Any],
    ) -> None:
        approval_id = approval_request_id(strategy_id=strategy_id, profile_id=profile_id)
        evidence = dict(source_alert.get("evidence_summary_json", {}) or {})
        create_attention_alert(
            usage_ledger=self.usage_ledger,
            now=datetime.now().astimezone(),
            event_id=build_event_id(
                event_type="paper_approval_missing",
                strategy_id=strategy_id,
                profile_id=profile_id,
                approval_id=approval_id,
            ),
            severity="warning",
            event_type="paper_approval_missing",
            title="Broker paper blocked by missing manual approval",
            message=(
                f"{strategy_id}/{profile_id} is blocked from broker paper execution until "
                "manual approval exists."
            ),
            evidence_summary={
                **evidence,
                "stage": "paper_candidate",
                "open_reason": "Reconciled from a blank-profile approval alert onto the current paper-candidate promotion row.",
                "approval_command": (
                    "python main.py --promotion-approve-paper "
                    f"--strategy-id {strategy_id} --profile-id {profile_id} "
                    "--max-paper-notional 10 --max-open-trades 1 "
                    "--cooldown-minutes 60 --confirm-promotion-approval"
                ),
                "reject_command": (
                    "python main.py --promotion-reject "
                    f"--strategy-id {strategy_id} --profile-id {profile_id} "
                    '--reason "manual review rejected"'
                ),
            },
            recommended_action="Approve or reject this request.",
            requires_attention=True,
            strategy_id=strategy_id,
            profile_id=profile_id,
            approval_request_id_value=approval_id,
            source=str(evidence.get("source", "") or "reconcile"),
        )

    def _create_live_alert(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        source_alert: dict[str, Any],
    ) -> None:
        evidence = dict(source_alert.get("evidence_summary_json", {}) or {})
        create_attention_alert(
            usage_ledger=self.usage_ledger,
            now=datetime.now().astimezone(),
            event_id=build_event_id(
                event_type="live_execution_requested_while_disabled",
                strategy_id=strategy_id,
                profile_id=profile_id,
            ),
            severity="critical",
            event_type="live_execution_requested_while_disabled",
            title="Live execution requested while disabled",
            message=(
                "Live proposals were present, but live execution remains disabled. "
                "No live trading was enabled."
            ),
            evidence_summary={
                **evidence,
                "open_reason": "Reconciled from a blank-profile disabled-live alert onto a valid strategy/profile identity.",
            },
            recommended_action="Review live request source; keep live disabled unless explicitly approved.",
            requires_attention=True,
            strategy_id=strategy_id,
            profile_id=profile_id,
            source=str(evidence.get("source", "") or "reconcile"),
        )

    def _create_diagnostic_alert(
        self,
        *,
        diagnostic_type: str,
        strategy_id: str,
        profile_id: str,
        title: str,
        message: str,
        source_alert: dict[str, Any],
    ) -> None:
        evidence = dict(source_alert.get("evidence_summary_json", {}) or {})
        create_attention_alert(
            usage_ledger=self.usage_ledger,
            now=datetime.now().astimezone(),
            event_id=build_event_id(
                event_type=diagnostic_type,
                strategy_id=strategy_id,
                profile_id=profile_id,
            ),
            severity="info",
            event_type=diagnostic_type,
            title=title,
            message=message,
            evidence_summary={
                **evidence,
                "stage": "diagnostic_invalid_or_stale_alert",
                "open_reason": message,
            },
            recommended_action="Inspect the source event payload and current promotion state.",
            requires_attention=False,
            strategy_id=strategy_id,
            profile_id=profile_id,
            source=str(evidence.get("source", "") or "reconcile"),
        )
