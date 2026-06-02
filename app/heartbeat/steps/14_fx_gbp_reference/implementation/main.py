"""Heartbeat step implementation owned by `14_fx_gbp_reference`."""

from __future__ import annotations

from app.heartbeat.support import (
    EcbReferenceRateClient,
    PipelineResult,
    TickContext,
    rate_is_stale,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `fx.gbp_reference` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    cached = context.usage_ledger.get_latest_fx_reference(source="ecb_fx")
    if cached is not None and not rate_is_stale(
        fetched_at=cached["fetched_at"],
        cache_minutes=context.config.ecb_reference_cache_minutes,
    ):
        result = {
            "source": cached["source"],
            "provider_date": cached["provider_date"],
            "usd_to_gbp": round(float(cached["usd_to_gbp"]), 6),
            "gbp_to_usd": round(float(cached["gbp_to_usd"]), 6),
            "mode": "cache",
        }
        context.state["fx_gbp_reference"] = {**result, "raw": cached}
        return result

    if cached is not None:
        try:
            fetched = EcbReferenceRateClient.from_config(context.config).get_gbp_reference_rate(context)
        except Exception:
            result = {
                "source": cached["source"],
                "provider_date": cached["provider_date"],
                "usd_to_gbp": round(float(cached["usd_to_gbp"]), 6),
                "gbp_to_usd": round(float(cached["gbp_to_usd"]), 6),
                "mode": "stale_cache",
            }
            context.state["fx_gbp_reference"] = {**result, "raw": cached}
            return result
    else:
        fetched = EcbReferenceRateClient.from_config(context.config).get_gbp_reference_rate(
            context
        )

    rate_payload = {
        "source": fetched.source,
        "provider_date": fetched.provider_date,
        "fetched_at": fetched.fetched_at.isoformat(),
        "base_currency": fetched.base_currency,
        "usd_per_eur": fetched.usd_per_eur,
        "gbp_per_eur": fetched.gbp_per_eur,
        "usd_to_gbp": fetched.usd_to_gbp,
        "gbp_to_usd": fetched.gbp_to_usd,
        "mode": fetched.mode,
        "raw_payload": fetched.raw_payload,
    }
    context.usage_ledger.record_fx_reference_rate(rate=rate_payload)
    result = {
        "source": fetched.source,
        "provider_date": fetched.provider_date,
        "usd_to_gbp": round(fetched.usd_to_gbp, 6),
        "gbp_to_usd": round(fetched.gbp_to_usd, 6),
        "mode": fetched.mode,
    }
    context.state["fx_gbp_reference"] = {**result, "raw": rate_payload}
    return result
