from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from centaur.models import TickContext


class ExecutionAdapterError(RuntimeError):
    """Raised when an execution adapter cannot submit or cancel an order."""


class UnsupportedExecutionAdapterError(ExecutionAdapterError):
    """Raised when an execution provider is not implemented or not approved."""


class ExecutionAdapter(ABC):
    """Execution-only adapter boundary for order planning and mutation.

    Broker adapters may still own account, position, and order snapshot reads.
    This interface is intentionally narrower: it is the order-planning and
    mutation surface used after strategy, risk, and runtime guards have passed.
    """

    adapter_id = "unknown"
    broker_id = "unknown"

    @abstractmethod
    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        """Return a broker/execution-provider veto before an entry is built."""
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        raise NotImplementedError
