"""Heartbeat step implementation owned by `23_market_scan`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    _coerce_datetime,
    rank_candidates,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `market.scan` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    gate = context.state["market_gate"]
    equity_universe = list(context.config.discovery_equity_symbols)
    crypto_universe = list(context.config.discovery_crypto_symbols)
    current_rows = context.usage_ledger.get_latest_bars_for_tick(
        tick_id=context.tick_id,
        sources=[
            "alpaca_market_data",
            "alpaca_crypto_data",
            "trading212_market_data",
        ],
    )

    result = {
        "equity_universe": len(equity_universe),
        "crypto_universe": len(crypto_universe),
        "bars_available": len(current_rows),
        "discovered_candidates": len(current_rows),
        "candidates_found": 0,
        "selected_candidates": 0,
        "mode": "pending",
        "scan_ready": gate["can_scan"],
    }
    if not current_rows:
        result["mode"] = "skipped"
        result["scan_ready"] = False
        result["skip_reason"] = gate["reason"] if gate["can_scan"] else gate["reason"]
        context.state["market_scan"] = {
            "result": result,
            "discovered_candidates": [],
            "ranked_candidates": [],
            "selected_candidates": [],
            "excluded_candidates": [],
        }
        return result

    freshness = _build_source_freshness(context=context, current_rows=current_rows)
    discovered_candidates = list(freshness["discovered_candidates"])
    eligible_rows = list(freshness["eligible_rows"])
    excluded_candidates = list(freshness["excluded_candidates"])

    if not eligible_rows:
        result.update(
            {
                "mode": "skipped",
                "skip_reason": "no_fresh_market_data",
                "source_freshness_status": freshness["source_freshness_status"],
                "stale_sources_excluded": freshness["stale_sources_excluded"],
                "candidates_excluded_due_to_stale_source": freshness[
                    "candidates_excluded_due_to_stale_source"
                ],
                "candidates_excluded_due_to_account_only_source": freshness[
                    "candidates_excluded_due_to_account_only_source"
                ],
                "market_data_source_used_for_strategy": freshness[
                    "market_data_source_used_for_strategy"
                ],
                "account_data_source_used_for_positions": freshness[
                    "account_data_source_used_for_positions"
                ],
                "eligible_for_strategy_evaluation": 0,
            }
        )
        context.state["market_scan"] = {
            "result": result,
            "discovered_candidates": discovered_candidates,
            "ranked_candidates": [],
            "selected_candidates": [],
            "excluded_candidates": excluded_candidates,
        }
        return result

    previous_rows = context.usage_ledger.get_previous_bars(
        tick_id=context.tick_id,
        symbol_keys=[(row["source"], row["symbol"]) for row in eligible_rows],
        current_rows=eligible_rows,
    )
    ranked_candidates = rank_candidates(
        current_rows=eligible_rows,
        previous_by_symbol=previous_rows,
        target_count=context.config.discovery_target_count,
    )
    ranked_candidate_dicts = [item.as_dict() for item in ranked_candidates]
    for item in ranked_candidate_dicts:
        item["market_data_source_used_for_strategy"] = freshness[
            "market_data_source_used_for_strategy"
        ].get(item["asset_class"], item["source"])
    selected_candidates = [item for item in ranked_candidate_dicts if item["selected"]]
    context.usage_ledger.record_discovery_candidates(
        tick_id=context.tick_id,
        candidates=ranked_candidate_dicts,
    )

    result["candidates_found"] = len(ranked_candidate_dicts)
    result["selected_candidates"] = len(selected_candidates)
    result["eligible_for_strategy_evaluation"] = len(ranked_candidate_dicts)
    result["mode"] = "dynamic_discovery"
    result["source_freshness_status"] = freshness["source_freshness_status"]
    result["stale_sources_excluded"] = freshness["stale_sources_excluded"]
    result["candidates_excluded_due_to_stale_source"] = freshness[
        "candidates_excluded_due_to_stale_source"
    ]
    result["candidates_excluded_due_to_account_only_source"] = freshness[
        "candidates_excluded_due_to_account_only_source"
    ]
    result["market_data_source_used_for_strategy"] = freshness[
        "market_data_source_used_for_strategy"
    ]
    result["account_data_source_used_for_positions"] = freshness[
        "account_data_source_used_for_positions"
    ]
    if selected_candidates:
        result["top_symbol"] = selected_candidates[0]["symbol"]
        result["top_score"] = selected_candidates[0]["discovery_score"]

    context.state["market_scan"] = {
        "result": result,
        "discovered_candidates": discovered_candidates,
        "ranked_candidates": ranked_candidate_dicts,
        "selected_candidates": selected_candidates,
        "excluded_candidates": excluded_candidates,
    }
    return result


def _build_source_freshness(
    *,
    context: TickContext,
    current_rows: list[dict[str, object]],
) -> dict[str, object]:
    now = context.started_at
    trading212_provider = str(
        context.state.get("trading212_data_latest_bars", {}).get("provider", "disabled") or "disabled"
    ).strip().lower()
    allow_stale = bool(getattr(context.config, "allow_stale_market_data_for_research", False))
    source_freshness_status: dict[str, dict[str, object]] = {}
    market_data_source_used_for_strategy: dict[str, str] = {}
    account_data_source_used_for_positions = {
        "alpaca": "alpaca_account_positions_api",
        "trading212_paper": (
            "trading212_positions_api" if trading212_provider in {"positions_api", "trading212_positions"} else trading212_provider
        ),
    }
    eligible_rows: list[dict[str, object]] = []
    discovered_candidates: list[dict[str, object]] = []
    excluded_candidates: list[dict[str, object]] = []
    stale_excluded_count = 0
    account_only_excluded_count = 0

    for row in current_rows:
        source = str(row.get("source", "")).strip()
        asset_class = str(row.get("asset_class", "") or _asset_class_for_source(source)).strip().lower()
        bar_timestamp = _coerce_datetime(row.get("bar_timestamp"))
        threshold_seconds = _threshold_seconds(context=context, asset_class=asset_class)
        newest_bar_age_seconds = (
            max(0.0, (now - bar_timestamp).total_seconds()) if bar_timestamp is not None else None
        )
        provider_kind = "market_data"
        eligible = True
        status = "fresh"
        rejection_reason = ""
        if source == "trading212_market_data" and trading212_provider in {"positions_api", "trading212_positions"}:
            provider_kind = "account_positions"
            eligible = False
            status = "account_only"
            rejection_reason = "market_data_source_account_only_positions_api"
        elif newest_bar_age_seconds is None:
            eligible = False
            status = "missing_bar_timestamp"
            rejection_reason = "market_data_source_missing_bar_timestamp"
        elif newest_bar_age_seconds > threshold_seconds:
            status = "stale"
            rejection_reason = "market_data_source_stale"
            eligible = allow_stale

        candidate = dict(row)
        candidate["asset_class"] = asset_class
        candidate["market_data_fresh"] = status == "fresh"
        candidate["market_data_eligible"] = eligible
        candidate["market_data_rejection_reason"] = rejection_reason
        candidate["market_data_status"] = status
        discovered_candidates.append(candidate)
        if eligible:
            eligible_rows.append(candidate)
            market_data_source_used_for_strategy.setdefault(asset_class, source)
        else:
            candidate["movement_pct"] = None
            excluded_candidates.append(candidate)
            if status == "account_only":
                account_only_excluded_count += 1
            else:
                stale_excluded_count += 1

        status_entry = source_freshness_status.setdefault(
            source,
            {
                "status": status,
                "eligible_for_strategy": eligible,
                "provider_kind": provider_kind,
                "asset_class": asset_class,
                "newest_bar_age_seconds": newest_bar_age_seconds,
                "threshold_seconds": threshold_seconds,
                "rejection_reason": rejection_reason,
            },
        )
        existing_age = status_entry.get("newest_bar_age_seconds")
        if isinstance(newest_bar_age_seconds, float) and (
            not isinstance(existing_age, float) or newest_bar_age_seconds < existing_age
        ):
            status_entry["newest_bar_age_seconds"] = newest_bar_age_seconds
            status_entry["status"] = status
            status_entry["eligible_for_strategy"] = eligible
            status_entry["provider_kind"] = provider_kind
            status_entry["asset_class"] = asset_class
            status_entry["rejection_reason"] = rejection_reason

    stale_sources_excluded = sorted(
        source
        for source, item in source_freshness_status.items()
        if not bool(item.get("eligible_for_strategy"))
    )
    return {
        "discovered_candidates": discovered_candidates,
        "eligible_rows": eligible_rows,
        "excluded_candidates": excluded_candidates,
        "source_freshness_status": source_freshness_status,
        "stale_sources_excluded": stale_sources_excluded,
        "candidates_excluded_due_to_stale_source": stale_excluded_count + account_only_excluded_count,
        "candidates_excluded_due_to_account_only_source": account_only_excluded_count,
        "market_data_source_used_for_strategy": market_data_source_used_for_strategy,
        "account_data_source_used_for_positions": account_data_source_used_for_positions,
    }


def _threshold_seconds(*, context: TickContext, asset_class: str) -> int:
    if asset_class == "crypto":
        return int(getattr(context.config, "max_bar_age_crypto_seconds", 600))
    return int(getattr(context.config, "max_bar_age_equity_seconds", 1800))


def _asset_class_for_source(source: str) -> str:
    if source == "alpaca_crypto_data":
        return "crypto"
    return "equity"
