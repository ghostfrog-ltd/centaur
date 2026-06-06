"""Heartbeat step implementation owned by `27_analysis_gemini`."""

from __future__ import annotations

from app.heartbeat.support import (
    GeminiApiError,
    PipelineResult,
    TickContext,
    _build_fallback_analyses,
    _normalize_gemini_analyses,
    get_gemini_client,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `analysis.gemini` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    enrichment = context.state["context_enrichment"]
    selected_candidates = enrichment.get("selected_candidates", [])
    candidates_enriched = enrichment["candidates_enriched"]
    if candidates_enriched == 0:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "skipped",
        }
        context.state["gemini_analysis"] = result
        return result

    if not context.config.gemini_analysis_enabled:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "disabled",
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": [],
        }
        return result

    if not context.config.gemini_api_configured:
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": 0,
            "analysis_mode": "not_configured",
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": [],
        }
        return result

    candidates_for_llm = selected_candidates[
        : context.config.gemini_analysis_candidate_limit
    ]
    fx_reference = context.state["fx_gbp_reference"]
    market_context = {
        "market_gate": context.state["market_gate"],
        "fx_gbp_reference": {
            "source": fx_reference["source"],
            "provider_date": fx_reference["provider_date"],
            "usd_to_gbp": fx_reference["usd_to_gbp"],
            "gbp_to_usd": fx_reference["gbp_to_usd"],
            "mode": fx_reference["mode"],
        },
        "account_equity": context.state["alpaca_account"]["summary"]["equity"],
    }

    try:
        gemini_response = get_gemini_client(context).analyze_candidates(
            context=context,
            candidates=candidates_for_llm,
            market_context=market_context,
        )
        normalized_analyses = _normalize_gemini_analyses(
            requested_candidates=candidates_for_llm,
            analysis_payload=gemini_response["analysis"],
        )
        context.usage_ledger.record_gemini_analyses(
            tick_id=context.tick_id,
            analyses=normalized_analyses,
        )
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": len(normalized_analyses),
            "analysis_mode": "live",
            "top_symbol": normalized_analyses[0]["symbol"]
            if normalized_analyses
            else "",
            "top_score": normalized_analyses[0]["opportunity_score"]
            if normalized_analyses
            else 0,
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": normalized_analyses,
            "usage_metadata": gemini_response["usage_metadata"],
            "raw_response": gemini_response["raw_response"],
        }
        return result
    except GeminiApiError as exc:
        fallback_analyses = _build_fallback_analyses(
            requested_candidates=candidates_for_llm,
            error=str(exc),
        )
        context.usage_ledger.record_gemini_analyses(
            tick_id=context.tick_id,
            analyses=fallback_analyses,
        )
        result = {
            "provider": "gemini_api",
            "candidates_analyzed": len(fallback_analyses),
            "analysis_mode": "fallback",
            "error": str(exc),
            "top_symbol": fallback_analyses[0]["symbol"] if fallback_analyses else "",
            "top_score": fallback_analyses[0]["opportunity_score"] if fallback_analyses else 0,
        }
        context.state["gemini_analysis"] = {
            **result,
            "analyses": fallback_analyses,
        }
        return result

    result = {
        "provider": "gemini_api",
        "candidates_analyzed": candidates_enriched,
        "analysis_mode": "adapter_pending",
    }
    context.state["gemini_analysis"] = result
    return result
