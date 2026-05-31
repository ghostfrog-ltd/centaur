from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ExecutionAdapter, ExecutionAdapterError

if TYPE_CHECKING:
    from app.runtime.models import TickContext


def get_broker_adapter(context: "TickContext", broker_id: str):
    from app.adapters.brokers import get_broker_adapter as _get_broker_adapter

    return _get_broker_adapter(context, broker_id)


class BrokerExecutionAdapter(ExecutionAdapter):
    """Execution adapter backed by the existing broker adapter layer."""

    def __init__(self, *, broker_id: str) -> None:
        normalized = str(broker_id or "").strip().lower()
        if not normalized:
            raise ExecutionAdapterError("missing_broker_id")
        self.broker_id = normalized
        self.adapter_id = f"{normalized}_execution"

    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        from app.adapters.brokers import BrokerAdapterError

        try:
            return get_broker_adapter(context, self.broker_id).validate_entry_constraints(
                context=context,
                proposal=proposal,
                notional_usd=notional_usd,
                usd_to_gbp=usd_to_gbp,
            )
        except BrokerAdapterError as exc:
            raise ExecutionAdapterError(str(exc)) from exc

    def build_entry_order_request(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        client_order_id: str,
        notional_usd: float,
        limit_buffer_bps: float,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        from app.adapters.brokers import BrokerAdapterError

        try:
            return get_broker_adapter(context, self.broker_id).build_entry_order_request(
                proposal=proposal,
                client_order_id=client_order_id,
                notional_usd=notional_usd,
                limit_buffer_bps=limit_buffer_bps,
                usd_to_gbp=usd_to_gbp,
            )
        except BrokerAdapterError as exc:
            raise ExecutionAdapterError(str(exc)) from exc

    def build_exit_order_request(
        self,
        *,
        context: TickContext,
        symbol: str,
        asset_class: str,
        qty: float | str,
        reference_price: float,
        client_order_id: str,
        limit_buffer_bps: float,
        entry_order: dict[str, Any] | None = None,
        latest_bar: dict[str, Any] | None = None,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        from app.adapters.brokers import BrokerAdapterError

        try:
            return get_broker_adapter(context, self.broker_id).build_exit_order_request(
                symbol=symbol,
                asset_class=asset_class,
                qty=qty,
                reference_price=reference_price,
                client_order_id=client_order_id,
                limit_buffer_bps=limit_buffer_bps,
                entry_order=entry_order,
                latest_bar=latest_bar,
                usd_to_gbp=usd_to_gbp,
            )
        except BrokerAdapterError as exc:
            raise ExecutionAdapterError(str(exc)) from exc

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        from app.adapters.brokers import BrokerAdapterError

        try:
            return get_broker_adapter(context, self.broker_id).submit_order(
                context,
                order_request=order_request,
            )
        except BrokerAdapterError as exc:
            raise ExecutionAdapterError(str(exc)) from exc

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        from app.adapters.brokers import BrokerAdapterError

        try:
            get_broker_adapter(context, self.broker_id).cancel_order(
                context,
                order_id=order_id,
            )
        except BrokerAdapterError as exc:
            raise ExecutionAdapterError(str(exc)) from exc
