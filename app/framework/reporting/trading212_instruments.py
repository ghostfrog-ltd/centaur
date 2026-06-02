from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.framework.adapters.trading212 import Trading212ApiError, Trading212PaperClient
from app.framework.runtime.models import TickContext
from app.framework.runtime.settings import PROJECT_ROOT, RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

INSTRUMENT_CACHE_PATH = PROJECT_ROOT / ".runtime" / "trading212_instruments_cache.json"
IMPLEMENTED_TRADING212_PRICE_PROVIDERS = frozenset(
    {"positions_api", "trading212_positions"}
)


class Trading212InstrumentReport:
    """Inspect Trading 212 metadata before enabling a UK proposal lane.

    This report is deliberately read-only. Trading 212's public API exposes
    instrument metadata, accounts, positions, orders, and history, but not the
    same latest-bar surface Centaur uses for Alpaca. The report therefore maps
    real venue tickers and keeps the execution blocker visible until a trusted
    Trading 212-compatible price/proposal source exists.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        client_factory: Callable[[RuntimeConfig], Trading212PaperClient] | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.client_factory = client_factory or Trading212PaperClient.from_config

    def build_report(self, *, sample_limit: int = 25) -> dict[str, Any]:
        configured_symbols = [
            str(symbol).strip().upper()
            for symbol in getattr(self.config, "trading212_paper_equity_symbols", tuple())
            if str(symbol).strip()
        ]
        overrides = dict(getattr(self.config, "trading212_paper_ticker_overrides", {}) or {})
        price_source = _price_source_readiness(self.config)
        if not getattr(self.config, "trading212_paper_api_configured", False):
            return {
                "status": "not_configured",
                "configured_symbols": configured_symbols,
                "mapped_symbols": [],
                "unmapped_symbols": configured_symbols,
                "sample_instruments": [],
                "price_source": price_source,
                "blockers": ["trading212_paper_credentials_missing", *price_source["blockers"]],
            }

        started_at = datetime.now().astimezone()
        ledger = UsageLedger(config=self.config)
        context = TickContext(
            tick_id=f"trading212-instruments-{started_at:%Y%m%d%H%M%S}",
            started_at=started_at,
            config=self.config,
            usage_ledger=ledger,
        )
        try:
            instruments = self.client_factory(self.config).get_instruments(context)
        except Trading212ApiError as exc:
            cached = _load_instrument_cache()
            if cached:
                return self._build_from_instruments(
                    instruments=cached,
                    configured_symbols=configured_symbols,
                    overrides=overrides,
                    checked_at=started_at,
                    status="cache_after_api_error",
                    extra_blockers=[str(exc)],
                    price_source=price_source,
                    sample_limit=sample_limit,
                )
            return {
                "status": "api_error",
                "configured_symbols": configured_symbols,
                "mapped_symbols": [],
                "unmapped_symbols": configured_symbols,
                "sample_instruments": [],
                "price_source": price_source,
                "blockers": [str(exc), *price_source["blockers"]],
            }
        _save_instrument_cache(instruments)

        return self._build_from_instruments(
            instruments=instruments,
            configured_symbols=configured_symbols,
            overrides=overrides,
            checked_at=started_at,
            status="ok",
            extra_blockers=[],
            price_source=price_source,
            sample_limit=sample_limit,
        )

    def _build_from_instruments(
        self,
        *,
        instruments: list[dict[str, Any]],
        configured_symbols: list[str],
        overrides: dict[str, str],
        checked_at: datetime,
        status: str,
        extra_blockers: list[str],
        price_source: dict[str, Any],
        sample_limit: int,
    ) -> dict[str, Any]:

        matches = _match_configured_symbols(
            configured_symbols=configured_symbols,
            overrides=overrides,
            instruments=instruments,
        )
        mapped_symbols = [item for item in matches if item.get("status") == "mapped"]
        unmapped_symbols = [
            item["symbol"] for item in matches if item.get("status") != "mapped"
        ]
        blockers = []
        if unmapped_symbols:
            blockers.append("unmapped_configured_symbols")
        blockers.extend(price_source["blockers"])
        if not price_source["ready"]:
            blockers.append("trading212_proposal_lane_missing")
        blockers.extend(extra_blockers)
        return {
            "status": status,
            "checked_at": checked_at.isoformat(),
            "instrument_count": len(instruments),
            "configured_symbols": configured_symbols,
            "mapped_symbols": mapped_symbols,
            "unmapped_symbols": unmapped_symbols,
            "sample_instruments": _sample_uk_like_instruments(
                instruments=instruments,
                limit=max(1, int(sample_limit)),
            ),
            "price_source": price_source,
            "blockers": blockers,
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        lines = ["Trading 212 Instrument Report"]
        lines.append(f"status={report.get('status', 'unknown')}")
        if report.get("checked_at"):
            lines.append(f"checked_at={report.get('checked_at')}")
        if "instrument_count" in report:
            lines.append(f"instruments_seen={int(report.get('instrument_count', 0) or 0)}")
        configured = report.get("configured_symbols", [])
        lines.append("Configured UK symbols: " + (", ".join(configured) if configured else "-"))
        price_source = report.get("price_source", {})
        lines.append(
            (
                "Trading 212 price source: "
                f"provider={price_source.get('provider', '-')} | "
                f"status={price_source.get('status', '-')}"
            )
        )

        lines.append("Mapped configured symbols:")
        mapped = report.get("mapped_symbols", [])
        if mapped:
            for item in mapped:
                lines.append(
                    (
                        f"- {item.get('symbol', '-')}"
                        f" -> {item.get('ticker', '-')}"
                        f" | name={item.get('name', '-')}"
                        f" | currency={item.get('currency', '-')}"
                        f" | exchange={item.get('exchange', '-')}"
                    )
                )
        else:
            lines.append("- none")

        unmapped = report.get("unmapped_symbols", [])
        lines.append("Unmapped configured symbols: " + (", ".join(unmapped) if unmapped else "-"))
        sample = report.get("sample_instruments", [])
        lines.append("Sample Trading 212 instruments:")
        if sample:
            for item in sample:
                lines.append(
                    (
                        f"- {item.get('ticker', '-')}"
                        f" | symbol={item.get('symbol', '-')}"
                        f" | name={item.get('name', '-')}"
                        f" | currency={item.get('currency', '-')}"
                        f" | exchange={item.get('exchange', '-')}"
                    )
                )
        else:
            lines.append("- none")
        blockers = report.get("blockers", [])
        lines.append("Trading blockers: " + (", ".join(blockers) if blockers else "-"))
        lines.append(
            "Decision rule: do not submit Trading 212 entries until configured symbols map to real Trading 212 tickers and a Trading 212-compatible latest-price/proposal lane exists."
        )
        return "\n".join(lines)


def _price_source_readiness(config: RuntimeConfig) -> dict[str, Any]:
    provider = (
        str(getattr(config, "trading212_paper_market_data_provider", "disabled") or "disabled")
        .strip()
        .lower()
        or "disabled"
    )
    if provider in {"disabled", "none", "off"}:
        return {
            "provider": provider,
            "status": "disabled",
            "ready": False,
            "blockers": [
                "trading212_market_data_provider_disabled",
                "trading212_latest_bars_source_missing",
            ],
        }
    if provider not in IMPLEMENTED_TRADING212_PRICE_PROVIDERS:
        return {
            "provider": provider,
            "status": "not_implemented",
            "ready": False,
            "blockers": [
                f"trading212_market_data_provider_not_implemented:{provider}",
                "trading212_latest_bars_source_missing",
            ],
        }
    if provider in {"positions_api", "trading212_positions"}:
        return {
            "provider": provider,
            "status": "held_positions_only",
            "ready": True,
            "blockers": [],
            "warning": "requires_seed_positions_for_each_symbol",
        }
    return {
        "provider": provider,
        "status": "ready",
        "ready": True,
        "blockers": [],
    }


def _match_configured_symbols(
    *,
    configured_symbols: list[str],
    overrides: dict[str, str],
    instruments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches = []
    for symbol in configured_symbols:
        override = str(overrides.get(symbol, "")).strip()
        instrument = _find_instrument(symbol=symbol, ticker=override, instruments=instruments)
        if instrument is None:
            matches.append({"symbol": symbol, "status": "unmapped"})
            continue
        matches.append(
            {
                "symbol": symbol,
                "status": "mapped",
                "ticker": _field(instrument, "ticker"),
                "name": _instrument_name(instrument),
                "currency": _instrument_currency(instrument),
                "exchange": _instrument_exchange(instrument),
            }
        )
    return matches


def _find_instrument(
    *,
    symbol: str,
    ticker: str,
    instruments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_symbol = symbol.upper()
    normalized_ticker = ticker.upper()
    matches: list[tuple[int, dict[str, Any]]] = []
    for instrument in instruments:
        instrument_ticker = _field(instrument, "ticker").upper()
        if normalized_ticker and instrument_ticker == normalized_ticker:
            return instrument
        candidates = {
            _field(instrument, "symbol").upper(),
            _field(instrument, "shortName").upper(),
            _field(instrument, "name").upper(),
            instrument_ticker.split("_", 1)[0].upper(),
            instrument_ticker.replace("L_EQ", "").replace("L", "").upper(),
        }
        if normalized_symbol in candidates or instrument_ticker == f"{normalized_symbol}L_EQ":
            matches.append(
                (
                    _instrument_match_score(
                        symbol=normalized_symbol,
                        instrument=instrument,
                    ),
                    instrument,
                )
            )
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _instrument_match_score(*, symbol: str, instrument: dict[str, Any]) -> int:
    ticker = _field(instrument, "ticker").upper()
    currency = _instrument_currency(instrument).upper()
    score = 0
    if ticker == f"{symbol}L_EQ":
        score += 100
    if currency in {"GBP", "GBX"}:
        score += 50
    if ticker.endswith("L_EQ"):
        score += 25
    if ticker.endswith("_US_EQ"):
        score -= 100
    return score


def _sample_uk_like_instruments(
    *,
    instruments: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, str]]:
    sampled = []
    for instrument in instruments:
        currency = _instrument_currency(instrument).upper()
        exchange = _instrument_exchange(instrument).upper()
        ticker = _field(instrument, "ticker")
        if currency not in {"GBP", "GBX"} and not any(
            marker in exchange for marker in ("LSE", "LONDON", "XLON", "AIM")
        ):
            continue
        sampled.append(
            {
                "ticker": ticker,
                "symbol": _field(instrument, "symbol") or ticker.split("_", 1)[0],
                "name": _instrument_name(instrument),
                "currency": _instrument_currency(instrument),
                "exchange": _instrument_exchange(instrument),
            }
        )
        if len(sampled) >= limit:
            break
    return sampled


def _field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value or "").strip()


def _instrument_name(payload: dict[str, Any]) -> str:
    return (
        _field(payload, "name")
        or _field(payload, "shortName")
        or _field(payload, "fullName")
        or "-"
    )


def _instrument_currency(payload: dict[str, Any]) -> str:
    return (
        _field(payload, "currencyCode")
        or _field(payload, "currency")
        or _field(payload, "workingCurrency")
        or "-"
    )


def _instrument_exchange(payload: dict[str, Any]) -> str:
    exchange = payload.get("exchange")
    if isinstance(exchange, dict):
        return (
            _field(exchange, "name")
            or _field(exchange, "code")
            or _field(exchange, "id")
            or "-"
        )
    return _field(payload, "exchange") or _field(payload, "exchangeName") or "-"


def _load_instrument_cache(path: Path = INSTRUMENT_CACHE_PATH) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    instruments = payload.get("instruments") if isinstance(payload, dict) else None
    if not isinstance(instruments, list):
        return []
    return [item for item in instruments if isinstance(item, dict)]


def _save_instrument_cache(
    instruments: list[dict[str, Any]],
    path: Path = INSTRUMENT_CACHE_PATH,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "cached_at": datetime.now().astimezone().isoformat(),
                    "instrument_count": len(instruments),
                    "instruments": instruments,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except OSError:
        return
