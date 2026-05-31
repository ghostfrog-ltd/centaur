from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from app.adapters.execution import ExecutionAdapterError, get_execution_adapter

from .live_guard import LiveRiskGuard, LiveRiskGuardError
from .mode_context import mode_context_from_config

if TYPE_CHECKING:
    from app.runtime.models import TickContext

ExecutionAdapterFactory = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class RoutedOrder:
    status: str
    broker_id: str
    order: dict[str, Any] | None = None
    error: str | None = None
    intended_order: dict[str, Any] | None = None

    @property
    def submitted(self) -> bool:
        return self.status == "submitted" and self.order is not None

    @property
    def canceled(self) -> bool:
        return self.status == "canceled"


class ExecutionRouter:
    """Single choke point for broker entry-order submission.

    Risk gates still decide whether an order is eligible. The router only
    enforces runtime lane boundaries, calls the selected broker adapter, and
    returns a structured result so execution steps can persist the audit trail.
    """

    def __init__(
        self,
        *,
        adapter_factory: ExecutionAdapterFactory = get_execution_adapter,
        live_guard: LiveRiskGuard | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._live_guard = live_guard or LiveRiskGuard()

    def route_entry_approval(
        self,
        *,
        context: TickContext,
        approval: dict[str, Any],
        lane: str,
    ) -> RoutedOrder:
        broker_id = str(approval.get("broker_id", "")).strip().lower()
        order_request = approval.get("order_request")
        return self.route_order_request(
            context=context,
            broker_id=broker_id,
            order_request=order_request,
            lane=lane,
            action="entry",
            strategy_id=str(approval.get("strategy_id", "")),
            notional_usd=approval.get("notional_usd"),
        )

    def route_order_request(
        self,
        *,
        context: TickContext,
        broker_id: str,
        order_request: Any,
        lane: str,
        action: str,
        strategy_id: str | None = None,
        notional_usd: Any = None,
    ) -> RoutedOrder:
        broker_id = str(broker_id).strip().lower()
        if not broker_id:
            return RoutedOrder(status="rejected", broker_id="", error="missing_broker_id")
        if not isinstance(order_request, dict):
            return RoutedOrder(
                status="rejected",
                broker_id=broker_id,
                error="missing_order_request",
            )

        normalized_lane = str(lane or "").strip().lower()
        mode_context = mode_context_from_config(context.config)
        if normalized_lane == "shadow":
            routed = RoutedOrder(
                status="recorded_shadow_intent",
                broker_id=broker_id,
                intended_order=order_request,
            )
            self._record_intent(
                context=context,
                lane=normalized_lane,
                action=action,
                broker_id=broker_id,
                intended_order=order_request,
                status=routed.status,
                strategy_id=strategy_id,
            )
            return routed
        if normalized_lane == "live" and not mode_context.can_mutate_live_broker:
            routed = RoutedOrder(
                status="live_dry_intent",
                broker_id=broker_id,
                intended_order=order_request,
            )
            self._record_intent(
                context=context,
                lane=normalized_lane,
                action=action,
                broker_id=broker_id,
                intended_order=order_request,
                status=routed.status,
                strategy_id=strategy_id,
            )
            return routed
        if normalized_lane not in {"paper", "live"}:
            return RoutedOrder(
                status="rejected",
                broker_id=broker_id,
                error=f"unsupported_execution_lane:{normalized_lane or 'unknown'}",
            )

        try:
            if normalized_lane == "live":
                self._live_guard.assert_order_action_allowed(
                    context=context,
                    broker_id=broker_id,
                    action=action,
                    strategy_id=strategy_id,
                    notional_usd=notional_usd,
                    order_request=order_request,
                )
            adapter = self._adapter_factory(context, broker_id)
            order = adapter.submit_order(context, order_request=order_request)
        except LiveRiskGuardError as exc:
            return RoutedOrder(status="error", broker_id=broker_id, error=str(exc))
        except ExecutionAdapterError as exc:
            return RoutedOrder(status="error", broker_id=broker_id, error=str(exc))

        return RoutedOrder(status="submitted", broker_id=broker_id, order=order)

    def route_cancel_order(
        self,
        *,
        context: TickContext,
        broker_id: str,
        order_id: str,
        lane: str,
    ) -> RoutedOrder:
        broker_id = str(broker_id).strip().lower()
        normalized_order_id = str(order_id or "").strip()
        if not broker_id:
            return RoutedOrder(status="rejected", broker_id="", error="missing_broker_id")
        if not normalized_order_id:
            return RoutedOrder(
                status="rejected",
                broker_id=broker_id,
                error="missing_order_id",
            )

        normalized_lane = str(lane or "").strip().lower()
        mode_context = mode_context_from_config(context.config)
        intended_order = {"order_id": normalized_order_id, "action": "cancel"}
        if normalized_lane == "live" and not mode_context.can_mutate_live_broker:
            routed = RoutedOrder(
                status="live_dry_intent",
                broker_id=broker_id,
                intended_order=intended_order,
            )
            self._record_intent(
                context=context,
                lane=normalized_lane,
                action="cancel",
                broker_id=broker_id,
                intended_order=intended_order,
                status=routed.status,
            )
            return routed
        if normalized_lane not in {"paper", "live"}:
            return RoutedOrder(
                status="rejected",
                broker_id=broker_id,
                error=f"unsupported_execution_lane:{normalized_lane or 'unknown'}",
            )

        try:
            if normalized_lane == "live":
                self._live_guard.assert_order_action_allowed(
                    context=context,
                    broker_id=broker_id,
                    action="cancel",
                )
            adapter = self._adapter_factory(context, broker_id)
            adapter.cancel_order(context, order_id=normalized_order_id)
        except LiveRiskGuardError as exc:
            return RoutedOrder(status="error", broker_id=broker_id, error=str(exc))
        except ExecutionAdapterError as exc:
            return RoutedOrder(status="error", broker_id=broker_id, error=str(exc))

        return RoutedOrder(status="canceled", broker_id=broker_id)

    def _record_intent(
        self,
        *,
        context: TickContext,
        lane: str,
        action: str,
        broker_id: str,
        intended_order: dict[str, Any],
        status: str,
        strategy_id: str | None = None,
    ) -> None:
        context.state.setdefault("execution_router_intents", []).append(
            {
                "lane": lane,
                "action": action,
                "broker_id": broker_id,
                "status": status,
                "strategy_id": strategy_id or "",
                "intended_order": intended_order,
            }
        )
        recorder = getattr(context.usage_ledger, "record_execution_router_intent", None)
        if callable(recorder):
            recorder(
                tick_id=context.tick_id,
                recorded_at=datetime.now().astimezone(),
                environment=str(getattr(context.config, "centaur_environment", "") or ""),
                mode=str(getattr(context.config, "centaur_mode", "") or ""),
                lane=lane,
                action=action,
                broker_id=broker_id,
                status=status,
                strategy_id=strategy_id or "",
                intended_order=intended_order,
            )
