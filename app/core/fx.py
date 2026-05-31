from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib import error, request

from app.runtime.models import TickContext
from app.runtime.settings import RuntimeConfig

ECB_NAMESPACE = {"gesmes": "http://www.gesmes.org/xml/2002-08-01", "def": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


class FxRateError(RuntimeError):
    """Raised when the FX reference-rate provider cannot be queried or parsed."""


@dataclass(frozen=True, slots=True)
class GbpReferenceRate:
    source: str
    provider_date: str
    fetched_at: datetime
    base_currency: str
    usd_per_eur: float
    gbp_per_eur: float
    usd_to_gbp: float
    gbp_to_usd: float
    mode: str
    raw_payload: str


class EcbReferenceRateClient:
    def __init__(self, *, url: str, timeout_seconds: int) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "EcbReferenceRateClient":
        return cls(
            url=config.ecb_reference_rates_url,
            timeout_seconds=config.ecb_request_timeout_seconds,
        )

    def get_gbp_reference_rate(self, context: TickContext) -> GbpReferenceRate:
        requested_at = datetime.now().astimezone()
        http_request = request.Request(
            url=self.url,
            headers={
                "Accept": "application/xml,text/xml",
                "User-Agent": "ghostfrog-centaur/0.1",
            },
            method="GET",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                status_code = getattr(response, "status", 200)

            parsed = parse_ecb_reference_rates(payload)
            context.record_api_usage(
                source="ecb_fx",
                endpoint="/stats/eurofxref/eurofxref-daily.xml",
                success=True,
                metadata={
                    "method": "GET",
                    "status_code": status_code,
                    "requested_at": requested_at.isoformat(),
                    "provider_date": parsed.provider_date,
                },
            )
            return GbpReferenceRate(
                source="ecb_fx",
                provider_date=parsed.provider_date,
                fetched_at=requested_at,
                base_currency="EUR",
                usd_per_eur=parsed.usd_per_eur,
                gbp_per_eur=parsed.gbp_per_eur,
                usd_to_gbp=parsed.usd_to_gbp,
                gbp_to_usd=parsed.gbp_to_usd,
                mode="fetched",
                raw_payload=payload,
            )
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            context.record_api_usage(
                source="ecb_fx",
                endpoint="/stats/eurofxref/eurofxref-daily.xml",
                success=False,
                metadata={
                    "method": "GET",
                    "status_code": exc.code,
                    "requested_at": requested_at.isoformat(),
                    "error": body[:240],
                },
            )
            raise FxRateError(
                f"ECB FX request failed with status {exc.code}: {body[:240]}"
            ) from exc
        except error.URLError as exc:
            context.record_api_usage(
                source="ecb_fx",
                endpoint="/stats/eurofxref/eurofxref-daily.xml",
                success=False,
                metadata={
                    "method": "GET",
                    "requested_at": requested_at.isoformat(),
                    "error": str(exc.reason),
                },
            )
            raise FxRateError(f"ECB FX request failed: {exc.reason}") from exc


@dataclass(frozen=True, slots=True)
class ParsedEcbRates:
    provider_date: str
    usd_per_eur: float
    gbp_per_eur: float
    usd_to_gbp: float
    gbp_to_usd: float


def parse_ecb_reference_rates(payload: str) -> ParsedEcbRates:
    root = ET.fromstring(payload)
    cube_with_date = root.find(".//def:Cube[@time]", ECB_NAMESPACE)
    if cube_with_date is None:
        raise FxRateError("ECB FX payload did not include a dated rate cube.")

    provider_date = cube_with_date.attrib["time"]
    rates: dict[str, float] = {}
    for cube in cube_with_date.findall("def:Cube", ECB_NAMESPACE):
        currency = cube.attrib.get("currency")
        rate = cube.attrib.get("rate")
        if currency and rate:
            rates[currency] = float(rate)

    if "USD" not in rates or "GBP" not in rates:
        raise FxRateError("ECB FX payload did not include both USD and GBP reference rates.")

    usd_per_eur = rates["USD"]
    gbp_per_eur = rates["GBP"]
    usd_to_gbp = gbp_per_eur / usd_per_eur
    gbp_to_usd = usd_per_eur / gbp_per_eur
    return ParsedEcbRates(
        provider_date=provider_date,
        usd_per_eur=usd_per_eur,
        gbp_per_eur=gbp_per_eur,
        usd_to_gbp=usd_to_gbp,
        gbp_to_usd=gbp_to_usd,
    )


def rate_is_stale(*, fetched_at: datetime, cache_minutes: int) -> bool:
    return datetime.now().astimezone() - fetched_at >= timedelta(minutes=cache_minutes)
