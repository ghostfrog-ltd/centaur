from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.runtime.models import TickContext


class BrokerAdapterError(RuntimeError):
    """Raised when a broker adapter cannot complete a requested action."""


class UnsupportedBrokerError(BrokerAdapterError):
    """Raised when Centaur is asked to use an unknown broker id."""


class BrokerAdapter(ABC):
    """Broker boundary for execution, validation, and audit normalization.

    Pipeline risk gates call adapters only after strategy and account checks have
    passed, and adapters may still veto a request when the broker cannot honor
    Centaur's notional, asset-class, leverage, or activation constraints.
    """

    broker_id = "unknown"
    label = "Unknown broker"
    native_currency = "USD"
    state_prefix = "broker"
    supported_asset_classes: tuple[str, ...] = tuple()

    def supports_asset_class(self, asset_class: str) -> bool:
        return str(asset_class or "").strip().lower() in self.supported_asset_classes

    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        """Return a broker-specific veto reason before an entry order is built."""
        asset_class = str(proposal.get("asset_class", "")).strip().lower()
        if asset_class and not self.supports_asset_class(asset_class):
            return "unsupported_asset_class"
        return None

    @abstractmethod
    def get_account(self, context: TickContext) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def summarize_account(self, raw_account: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_clock(self, context: TickContext) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def summarize_clock(self, raw_clock: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def summarize_positions(self, raw_positions: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_orders(
        self,
        context: TickContext,
        *,
        after: datetime | None,
        limit: int,
        status: str = "all",
        nested: bool = True,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def summarize_orders(self, raw_orders: list[dict[str, Any]]) -> dict[str, Any]:
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

    @abstractmethod
    def build_entry_order_request(
        self,
        *,
        proposal: dict[str, Any],
        client_order_id: str,
        notional_usd: float,
        limit_buffer_bps: float,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        """Build an entry request only after risk gates and adapter vetoes pass."""
        raise NotImplementedError

    @abstractmethod
    def build_exit_order_request(
        self,
        *,
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
        """Build a protective/managed exit request without widening quantity."""
        raise NotImplementedError
