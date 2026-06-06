from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config


@dataclass(frozen=True, slots=True)
class AdapterRecord:
    adapter_type: str
    provider_id: str
    status: str
    implementation: str
    behavior: str
    activation_rule: str

    def as_dict(self) -> dict[str, str]:
        return {
            "adapter_type": self.adapter_type,
            "provider_id": self.provider_id,
            "status": self.status,
            "implementation": self.implementation,
            "behavior": self.behavior,
            "activation_rule": self.activation_rule,
        }


class AdapterInventoryReport:
    """Read-only inventory of adapter boundaries and vendor activation status."""

    def __init__(self, *, config: RuntimeConfig | None = None) -> None:
        self.config = config or load_runtime_config()

    def build_report(self) -> dict[str, Any]:
        records = [item.as_dict() for item in _adapter_records(config=self.config)]
        return {
            "status": "ok",
            "mode": getattr(self.config, "centaur_mode", ""),
            "environment": getattr(self.config, "centaur_environment", ""),
            "records": records,
            "active_market_data_provider": "alpaca",
            "active_execution_bridge": "broker_bridge",
            "non_alpaca_active": any(
                item["status"] == "active" and item["provider_id"] != "alpaca"
                for item in records
            ),
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Centaur Adapter Inventory\n"
                f"Status: {report.get('status', 'unknown')}"
            )
        lines = [
            "Centaur Adapter Inventory",
            (
                f"mode={report.get('mode', '-')}"
                f" | environment={report.get('environment', '-')}"
                f" | active_market_data={report.get('active_market_data_provider', '-')}"
                f" | execution_bridge={report.get('active_execution_bridge', '-')}"
            ),
        ]
        for item in report.get("records", []):
            record = item if isinstance(item, dict) else {}
            lines.append(
                (
                    f"- {record.get('adapter_type', '-')}/{record.get('provider_id', '-')}"
                    f" | status={record.get('status', '-')}"
                    f" | implementation={record.get('implementation', '-')}"
                    f" | behavior={record.get('behavior', '-')}"
                    f" | activation_rule={record.get('activation_rule', '-')}"
                )
            )
        lines.append(
            "Decision rule: unsupported and scaffold-only adapters must not be used for trading without concrete implementation, tests, evidence surfaces, and explicit approval."
        )
        return "\n".join(lines)


def _adapter_records(*, config: RuntimeConfig | None = None) -> list[AdapterRecord]:
    trading212_price_provider = (
        str(getattr(config, "trading212_paper_market_data_provider", "disabled") or "disabled")
        .strip()
        .lower()
        or "disabled"
    )
    trading212_live_price_provider = (
        str(getattr(config, "trading212_live_market_data_provider", "disabled") or "disabled")
        .strip()
        .lower()
        or "disabled"
    )
    return [
        AdapterRecord(
            adapter_type="market_data",
            provider_id="alpaca",
            status="active",
            implementation="AlpacaMarketDataAdapter",
            behavior="latest equity/crypto bars and historical equity/crypto backfill",
            activation_rule="current approved provider",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="alpaca_paper",
            status="active_bridge",
            implementation="BrokerExecutionAdapter -> AlpacaBrokerAdapter",
            behavior="paper order planning, submit, cancel",
            activation_rule="paper risk gates plus execution router",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="alpaca_live",
            status="active_bridge",
            implementation="BrokerExecutionAdapter -> AlpacaLiveBrokerAdapter",
            behavior="independent LIVE_* lane order planning, submit, cancel",
            activation_rule="live proposal/risk gates plus LiveRiskGuard",
        ),
        AdapterRecord(
            adapter_type="broker_account",
            provider_id="alpaca",
            status="active",
            implementation="AlpacaBrokerAdapter / AlpacaLiveBrokerAdapter",
            behavior="account, clock, positions, order snapshots",
            activation_rule="paper/live mode boundaries",
        ),
        AdapterRecord(
            adapter_type="broker_account",
            provider_id="ig_spreadbet",
            status="scaffold_only",
            implementation="IgBrokerAdapter",
            behavior="account scaffold; no live trading lane",
            activation_rule="not approved for execution",
        ),
        AdapterRecord(
            adapter_type="broker_account",
            provider_id="trading212_paper",
            status="active_paper",
            implementation="Trading212PaperBrokerAdapter",
            behavior="demo account, positions, orders, and paper equity order mutation",
            activation_rule="paper master gates plus broker-specific 10-slot lane",
        ),
        AdapterRecord(
            adapter_type="broker_account",
            provider_id="trading212_live",
            status="disabled_live",
            implementation="Trading212LiveBrokerAdapter",
            behavior="live account identity and API wiring; order mutation hard-disabled",
            activation_rule="requires explicit Trading 212 live approval plus implemented price/proposal lane",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="ig_spreadbet",
            status="not_implemented",
            implementation="-",
            behavior="not available through execution adapter registry",
            activation_rule="requires concrete adapter, evidence surfaces, tests, and approval",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="trading212_paper",
            status="active_bridge",
            implementation="BrokerExecutionAdapter -> Trading212PaperBrokerAdapter",
            behavior="paper equity limit order planning, submit, cancel",
            activation_rule="paper risk gates plus duplicate client-order-id guard",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="trading212_live",
            status="disabled_live",
            implementation="BrokerExecutionAdapter -> Trading212LiveBrokerAdapter",
            behavior="live equity order planning interface exists; validate/submit/cancel fail closed",
            activation_rule="TRADING212_LIVE_EXECUTION_ENABLED must stay false until separately approved",
        ),
        AdapterRecord(
            adapter_type="market_data",
            provider_id="trading212_paper",
            status="metadata_only",
            implementation="Trading212PaperClient.get_instruments",
            behavior=(
                "read-only instrument metadata for UK symbol/ticker readiness; "
                f"configured_price_provider={trading212_price_provider}; positions_api can price only held symbols"
            ),
            activation_rule="Trading 212 entries require mapped Trading 212 tickers and an implemented trusted price/proposal lane",
        ),
        AdapterRecord(
            adapter_type="market_data",
            provider_id="trading212_live",
            status="disabled_live",
            implementation="Trading212PaperClient.get_instruments via live credentials when approved",
            behavior=(
                "live instrument metadata wiring mirrors paper; "
                f"configured_price_provider={trading212_live_price_provider}; no latest-bar source yet"
            ),
            activation_rule="read-only/live mutation requires explicit approval and implemented provider",
        ),
        AdapterRecord(
            adapter_type="market_data",
            provider_id="binance",
            status="not_implemented",
            implementation="-",
            behavior="future venue-symbol mapping only",
            activation_rule="requires adapter, tests, persistence provenance, and approval",
        ),
        AdapterRecord(
            adapter_type="execution",
            provider_id="binance",
            status="not_implemented",
            implementation="-",
            behavior="not available",
            activation_rule="requires adapter, LiveRiskGuard venue checks, tests, and approval",
        ),
        AdapterRecord(
            adapter_type="market_data",
            provider_id="coinbase",
            status="not_implemented",
            implementation="-",
            behavior="future venue-symbol mapping only",
            activation_rule="requires adapter, tests, persistence provenance, and approval",
        ),
        AdapterRecord(
            adapter_type="market_data",
            provider_id="polygon",
            status="not_implemented",
            implementation="-",
            behavior="not available",
            activation_rule="requires adapter, cost controls, tests, and approval",
        ),
    ]
