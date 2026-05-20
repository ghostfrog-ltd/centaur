from __future__ import annotations

from typing import Any

from ..config import RuntimeConfig
from ..models import TickContext
from .base import BrokerAdapter, BrokerAdapterError

_DEFAULT_EPICS = {
    "AAPL": "ED.D.AAPL.CASH.IP",
    "TSLA": "ED.D.TSLA.CASH.IP",
    "NVDA": "ED.D.NVDA.CASH.IP",
    "AMD": "ED.D.AMD.CASH.IP",
    "MSFT": "ED.D.MSFT.CASH.IP",
    "GOOGL": "ED.D.GOOGL.CASH.IP",
}


class IgBrokerAdapter(BrokerAdapter):
    broker_id = "ig_spreadbet"
    label = "IG Spread Betting"
    native_currency = "GBP"
    state_prefix = "ig"
    supported_asset_classes = ("equity",)

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        api_key: str,
        account_type: str,
        account_number: str,
        timeout_seconds: int,
        min_bet_per_point_gbp: float,
        epic_overrides: dict[str, str],
        api_configured: bool,
    ) -> None:
        self.base_url = str(base_url).strip()
        self.username = str(username).strip()
        self.password = str(password).strip()
        self.api_key = str(api_key).strip()
        self.account_type = str(account_type).strip().upper()
        self.account_number = str(account_number).strip()
        self.timeout_seconds = int(timeout_seconds)
        self.min_bet_per_point_gbp = float(min_bet_per_point_gbp)
        self.epic_overrides = {
            str(symbol).strip().upper(): str(epic).strip()
            for symbol, epic in epic_overrides.items()
            if str(symbol).strip() and str(epic).strip()
        }
        self.api_configured = bool(api_configured)

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "IgBrokerAdapter":
        return cls(
            base_url=config.ig_base_url,
            username=config.ig_username,
            password=config.ig_password,
            api_key=config.ig_api_key,
            account_type=config.ig_account_type,
            account_number=config.ig_account_number,
            timeout_seconds=config.ig_request_timeout_seconds,
            min_bet_per_point_gbp=config.ig_min_bet_per_point_gbp,
            epic_overrides=config.ig_epic_overrides,
            api_configured=config.ig_api_configured,
        )

    def resolve_epic(self, symbol: str) -> str | None:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        return self.epic_overrides.get(normalized) or _DEFAULT_EPICS.get(normalized)

    def estimate_bet_per_point_gbp(
        self,
        *,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None,
    ) -> float | None:
        entry_price_gbp = _to_float(proposal.get("entry_price_gbp"))
        if entry_price_gbp is None:
            entry_price_usd = _to_float(proposal.get("entry_price"))
            if entry_price_usd is not None and usd_to_gbp not in (None, 0):
                entry_price_gbp = entry_price_usd * float(usd_to_gbp)
        notional_gbp = float(notional_usd) * float(usd_to_gbp or 0.0)
        if entry_price_gbp in (None, 0) or notional_gbp <= 0:
            return None
        return round(notional_gbp / float(entry_price_gbp), 6)

    def validate_entry_constraints(
        self,
        *,
        context: TickContext,
        proposal: dict[str, Any],
        notional_usd: float,
        usd_to_gbp: float | None = None,
    ) -> str | None:
        base_reason = super().validate_entry_constraints(
            context=context,
            proposal=proposal,
            notional_usd=notional_usd,
            usd_to_gbp=usd_to_gbp,
        )
        if base_reason is not None:
            return base_reason
        if not self.api_configured:
            return "ig_not_configured"
        if float(usd_to_gbp or 0.0) <= 0:
            return "fx_reference_unavailable"
        if self.resolve_epic(str(proposal.get("symbol", ""))) is None:
            return "ig_epic_unmapped"

        bet_per_point = self.estimate_bet_per_point_gbp(
            proposal=proposal,
            notional_usd=notional_usd,
            usd_to_gbp=usd_to_gbp,
        )
        if bet_per_point is None or bet_per_point <= 0:
            return "ig_invalid_bet_size"
        if bet_per_point < self.min_bet_per_point_gbp:
            return "ig_min_bet_exceeds_notional_limit"

        entry_price_gbp = _to_float(proposal.get("entry_price_gbp"))
        if entry_price_gbp is None:
            entry_price_usd = _to_float(proposal.get("entry_price"))
            if entry_price_usd is not None:
                entry_price_gbp = entry_price_usd * float(usd_to_gbp or 0.0)
        notional_gbp = float(notional_usd) * float(usd_to_gbp or 0.0)
        if entry_price_gbp is None or entry_price_gbp <= 0 or notional_gbp <= 0:
            return "ig_invalid_bet_size"

        min_bet_implied_exposure = float(self.min_bet_per_point_gbp) * float(entry_price_gbp)
        effective_leverage = min_bet_implied_exposure / notional_gbp
        if effective_leverage > 1.0 + 1e-9:
            return "ig_leverage_above_1x"
        return None

    def get_account(self, context: TickContext) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and not active for live account sync yet.")

    def summarize_account(self, raw_account: dict[str, Any]) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and cannot summarize accounts yet.")

    def get_clock(self, context: TickContext) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and does not provide market clock yet.")

    def summarize_clock(self, raw_clock: dict[str, Any]) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and cannot summarize clock data yet.")

    def get_positions(self, context: TickContext) -> list[dict[str, Any]]:
        raise BrokerAdapterError("IG adapter is scaffold-only and not active for position sync yet.")

    def summarize_positions(self, raw_positions: list[dict[str, Any]]) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and cannot summarize positions yet.")

    def get_orders(
        self,
        context: TickContext,
        *,
        after,
        limit: int,
        status: str = "all",
        nested: bool = True,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        raise BrokerAdapterError("IG adapter is scaffold-only and not active for working-order sync yet.")

    def summarize_orders(self, raw_orders: list[dict[str, Any]]) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and cannot summarize orders yet.")

    def submit_order(
        self,
        context: TickContext,
        *,
        order_request: dict[str, Any],
    ) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter is scaffold-only and paper execution is not enabled.")

    def cancel_order(
        self,
        context: TickContext,
        *,
        order_id: str,
    ) -> None:
        raise BrokerAdapterError("IG adapter is scaffold-only and cannot cancel orders yet.")

    def build_entry_order_request(
        self,
        *,
        proposal: dict[str, Any],
        client_order_id: str,
        notional_usd: float,
        limit_buffer_bps: float,
        usd_to_gbp: float | None = None,
    ) -> dict[str, Any]:
        raise BrokerAdapterError("IG adapter order construction is not enabled until the adapter leaves shadow mode.")

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
        raise BrokerAdapterError("IG adapter exit construction is not enabled until the adapter leaves shadow mode.")


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
