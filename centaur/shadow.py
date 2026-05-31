from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class CheckpointWindow:
    code: str
    minutes: int

    @property
    def label(self) -> str:
        return self.code


def parse_checkpoint_windows(window_codes: tuple[str, ...]) -> list[CheckpointWindow]:
    parsed: list[CheckpointWindow] = []
    seen_codes: set[str] = set()

    for raw_code in window_codes:
        code = raw_code.strip().lower()
        if not code or code in seen_codes:
            continue
        minutes = _window_code_to_minutes(code)
        parsed.append(CheckpointWindow(code=code, minutes=minutes))
        seen_codes.add(code)

    parsed.sort(key=lambda item: item.minutes)
    return parsed


def build_shadow_proposals(
    *,
    tick_id: str,
    proposed_at: datetime,
    strategy_signals: list[dict[str, Any]],
    recent_strategy_keys: set[tuple[str, str, str]],
    proposal_limit: int,
    min_signal_score: float,
    checkpoint_windows: tuple[str, ...],
) -> list[dict[str, Any]]:
    windows = parse_checkpoint_windows(checkpoint_windows)
    if not windows or not strategy_signals:
        return []

    proposals: list[dict[str, Any]] = []
    ranked_signals = sorted(
        strategy_signals,
        key=lambda item: (
            float(item.get("signal_score", 0) or 0),
            float(item.get("confidence", 0) or 0),
            str(item.get("strategy_id", "")),
            str(item.get("symbol", "")),
        ),
        reverse=True,
    )

    for signal in ranked_signals:
        symbol = str(signal.get("symbol", "")).upper()
        if not symbol:
            continue

        source = str(signal.get("source", ""))
        strategy_id = str(signal.get("strategy_id", ""))
        if (strategy_id, source, symbol) in recent_strategy_keys:
            continue

        signal_score = float(signal.get("signal_score", 0) or 0)
        if signal_score < min_signal_score:
            continue

        entry_price = _to_float(signal.get("entry_price"))
        if entry_price is None or entry_price <= 0:
            continue

        entry_price_gbp = _to_float(signal.get("entry_price_gbp"))
        holding_window_code = str(signal.get("holding_window_code", "")).lower()
        holding_window_minutes = int(signal.get("holding_window_minutes", 0) or 0)
        proposal_windows = _merge_checkpoint_windows(
            base_windows=windows,
            holding_window_code=holding_window_code,
            holding_window_minutes=holding_window_minutes,
        )
        proposal_id = _build_proposal_id(
            tick_id=tick_id,
            strategy_id=strategy_id,
            source=source,
            symbol=symbol,
        )

        checkpoints = [
            {
                "checkpoint_code": window.code,
                "checkpoint_minutes": window.minutes,
                "due_at": (proposed_at + timedelta(minutes=window.minutes)).isoformat(),
            }
            for window in proposal_windows
        ]

        proposal = {
            "proposal_id": proposal_id,
            "tick_id": tick_id,
            "proposed_at": proposed_at.isoformat(),
            "strategy_id": strategy_id,
            "strategy_family": str(signal.get("strategy_family", "")),
            "profile_id": str(signal.get("profile_id", "")),
            "source": source,
            "symbol": symbol,
            "asset_class": str(signal.get("asset_class", "equity")),
            "direction": str(signal.get("direction", "long")),
            "status": "active",
            "action_bias": "watch",
            "opportunity_score": signal_score,
            "signal_score": signal_score,
            "signal_confidence": round(float(signal.get("confidence", 0) or 0), 6),
            "confidence": round(float(signal.get("confidence", 0) or 0), 6),
            "discovery_score": round(float(signal.get("discovery_score", 0) or 0), 6),
            "entry_price": round(entry_price, 8),
            "entry_price_gbp": round(entry_price_gbp, 8) if entry_price_gbp is not None else None,
            "stop_loss_price": _to_float(signal.get("stop_loss_price")),
            "stop_loss_price_gbp": _to_float(signal.get("stop_loss_price_gbp")),
            "target_price": _to_float(signal.get("target_price")),
            "target_price_gbp": _to_float(signal.get("target_price_gbp")),
            "atr_value": _to_float(signal.get("atr_value")),
            "atr_pct": _to_float(signal.get("atr_pct")),
            "breakout_high_price": _to_float(signal.get("breakout_high_price")),
            "avg_volume_lookback": _to_float(signal.get("avg_volume_lookback")),
            "volume_ratio": _to_float(signal.get("volume_ratio")),
            "break_even_trigger_price": _to_float(signal.get("break_even_trigger_price")),
            "break_even_trigger_price_gbp": _to_float(
                signal.get("break_even_trigger_price_gbp")
            ),
            "trailing_stop_mode": str(signal.get("trailing_stop_mode", "")).strip(),
            "risk_pct": round(float(signal.get("risk_pct", 0) or 0), 6),
            "target_return_pct": round(float(signal.get("target_return_pct", 0) or 0), 6),
            "holding_window_code": holding_window_code,
            "holding_window_minutes": holding_window_minutes,
            "thesis": str(signal.get("rationale", "")).strip(),
            "rationale": str(signal.get("rationale", "")).strip(),
            "risks": [],
            "note": str(signal.get("note", "shadow_trade_watch_candidate")),
            "checkpoint_windows": checkpoints,
        }
        proposals.append(proposal)
        if len(proposals) >= max(1, proposal_limit):
            break

    return proposals


def evaluate_shadow_checkpoint(
    *,
    checkpoint: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of: datetime,
    execution_spread_bps: float = 0.0,
    entry_slippage_bps: float = 0.0,
    exit_slippage_bps: float = 0.0,
    fixed_round_trip_cost_usd: float = 0.0,
    reference_notional_usd: float = 0.0,
    profit_target_ladder_pct: tuple[float, ...] = (),
) -> dict[str, Any] | None:
    raw_checkpoint = checkpoint.get("raw_json", {})
    if not isinstance(raw_checkpoint, dict):
        raw_checkpoint = {}
    proposed_at = _to_datetime(checkpoint.get("proposed_at"))
    due_at = _to_datetime(checkpoint.get("due_at"))
    entry_price = _to_float(checkpoint.get("entry_price"))
    entry_price_gbp = _to_float(checkpoint.get("entry_price_gbp"))
    stop_loss_price = _to_float(checkpoint.get("stop_loss_price"))
    target_price = _to_float(checkpoint.get("target_price"))
    break_even_trigger_price = _to_float(
        checkpoint.get("break_even_trigger_price", raw_checkpoint.get("break_even_trigger_price"))
    )
    trailing_stop_mode = str(
        checkpoint.get("trailing_stop_mode", raw_checkpoint.get("trailing_stop_mode", ""))
    ).strip()
    risk_pct = _to_float(checkpoint.get("risk_pct")) or 0.0
    trade_notional_usd = (
        _to_float(checkpoint.get("notional_usd"))
        or _to_float(raw_checkpoint.get("notional_usd"))
        or _to_float(reference_notional_usd)
        or 0.0
    )
    if proposed_at is None or due_at is None or entry_price is None:
        return None

    normalized_bars = []
    for item in bars:
        captured_at = _to_datetime(item.get("captured_at"))
        if captured_at is None or captured_at < proposed_at or captured_at > as_of:
            continue
        normalized_bars.append(
            {
                "captured_at": captured_at,
                "high_price": _to_float(item.get("high_price")),
                "low_price": _to_float(item.get("low_price")),
                "close_price": _to_float(item.get("close_price")),
                "high_price_gbp": _to_float(item.get("high_price_gbp")),
                "low_price_gbp": _to_float(item.get("low_price_gbp")),
                "close_price_gbp": _to_float(item.get("close_price_gbp")),
            }
        )

    if not normalized_bars:
        return None

    normalized_bars.sort(key=lambda item: item["captured_at"])
    observed_bars: list[dict[str, Any]] = []
    exit_at: datetime | None = None
    exit_price: float | None = None
    exit_price_gbp: float | None = None
    outcome_status = "pending"
    notes = ""
    break_even_active = False
    break_even_pending = False

    for bar in normalized_bars:
        if bar["captured_at"] >= due_at:
            break

        observed_bars.append(bar)
        if break_even_pending:
            break_even_active = True
            break_even_pending = False

        effective_stop_loss = stop_loss_price
        if trailing_stop_mode == "break_even_next_bar" and break_even_active:
            effective_stop_loss = entry_price
        stop_hit = (
            effective_stop_loss is not None
            and bar["low_price"] is not None
            and bar["low_price"] <= effective_stop_loss
        )
        target_hit = (
            target_price is not None
            and bar["high_price"] is not None
            and bar["high_price"] >= target_price
        )
        if stop_hit and target_hit:
            outcome_status = "ambiguous_range"
            exit_at = bar["captured_at"]
            exit_price = bar["close_price"] or entry_price
            exit_price_gbp = bar["close_price_gbp"] or entry_price_gbp
            notes = "stop_and_target_touched_same_bar"
            break
        if stop_hit:
            outcome_status = (
                "break_even_stop"
                if trailing_stop_mode == "break_even_next_bar"
                and break_even_active
                and effective_stop_loss == entry_price
                else "stop_hit"
            )
            exit_at = bar["captured_at"]
            exit_price = effective_stop_loss
            exit_price_gbp = _convert_like_for_gbp(
                entry_price=entry_price,
                target_price=effective_stop_loss,
                entry_price_gbp=entry_price_gbp,
            )
            break
        if target_hit:
            outcome_status = "target_hit"
            exit_at = bar["captured_at"]
            exit_price = target_price
            exit_price_gbp = _convert_like_for_gbp(
                entry_price=entry_price,
                target_price=target_price,
                entry_price_gbp=entry_price_gbp,
            )
            break
        break_even_trigger_hit = (
            trailing_stop_mode == "break_even_next_bar"
            and not break_even_active
            and break_even_trigger_price is not None
            and bar["high_price"] is not None
            and bar["high_price"] >= break_even_trigger_price
        )
        if break_even_trigger_hit:
            break_even_pending = True
            notes = "break_even_armed_next_bar"

    if outcome_status == "pending":
        exit_bar = next(
            (bar for bar in normalized_bars if bar["captured_at"] >= due_at),
            None,
        )
        if exit_bar is None:
            return None
        observed_bars.append(exit_bar)
        exit_at = exit_bar["captured_at"]
        exit_price = exit_bar["close_price"] or entry_price
        exit_price_gbp = exit_bar["close_price_gbp"] or entry_price_gbp
        outcome_status = "time_exit"
        if not notes:
            notes = "window_elapsed"

    if exit_at is None or exit_price is None:
        return None

    max_high = _max_value(observed_bars, "high_price")
    min_low = _min_value(observed_bars, "low_price")
    effective_entry_price = _apply_long_entry_friction(
        price=entry_price,
        spread_bps=execution_spread_bps,
        slippage_bps=entry_slippage_bps,
    )
    effective_exit_price = _apply_long_exit_friction(
        price=exit_price,
        spread_bps=execution_spread_bps,
        slippage_bps=exit_slippage_bps,
    )
    effective_entry_price_gbp = _scale_like_price(
        base_price=entry_price,
        adjusted_price=effective_entry_price,
        base_like=entry_price_gbp,
    )
    effective_exit_price_gbp = _scale_like_price(
        base_price=exit_price,
        adjusted_price=effective_exit_price,
        base_like=exit_price_gbp,
    )
    gross_realized_return_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 6)
    realized_return_pct_before_fixed_cost = round(
        ((effective_exit_price - effective_entry_price) / effective_entry_price) * 100.0,
        6,
    )
    fixed_round_trip_cost_usd = max(0.0, float(fixed_round_trip_cost_usd or 0.0))
    fixed_friction_return_pct = (
        round((fixed_round_trip_cost_usd / trade_notional_usd) * 100.0, 6)
        if trade_notional_usd > 0
        else 0.0
    )
    realized_return_pct = round(
        realized_return_pct_before_fixed_cost - fixed_friction_return_pct,
        6,
    )
    effective_risk_pct = _effective_risk_pct(
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        fallback_risk_pct=risk_pct,
        execution_spread_bps=execution_spread_bps,
        entry_slippage_bps=entry_slippage_bps,
        exit_slippage_bps=exit_slippage_bps,
    )
    max_favorable_excursion_pct = (
        round(
            (
                (
                    _apply_long_exit_friction(
                        price=max_high,
                        spread_bps=execution_spread_bps,
                        slippage_bps=exit_slippage_bps,
                    )
                    - effective_entry_price
                )
                / effective_entry_price
            )
            * 100.0,
            6,
        )
        if max_high is not None
        else None
    )
    max_adverse_excursion_pct = (
        round(
            (
                (
                    _apply_long_exit_friction(
                        price=min_low,
                        spread_bps=execution_spread_bps,
                        slippage_bps=exit_slippage_bps,
                    )
                    - effective_entry_price
                )
                / effective_entry_price
            )
            * 100.0,
            6,
        )
        if min_low is not None
        else None
    )
    profit_target_ladder = _profit_target_ladder_outcomes(
        entry_price=entry_price,
        entry_price_gbp=entry_price_gbp,
        stop_loss_price=stop_loss_price,
        bars=normalized_bars,
        due_at=due_at,
        target_pcts=profit_target_ladder_pct,
        execution_spread_bps=execution_spread_bps,
        entry_slippage_bps=entry_slippage_bps,
        exit_slippage_bps=exit_slippage_bps,
        fixed_round_trip_cost_usd=fixed_round_trip_cost_usd,
        trade_notional_usd=trade_notional_usd,
    )

    return {
        "proposal_id": checkpoint["proposal_id"],
        "checkpoint_code": str(checkpoint["checkpoint_code"]).lower(),
        "checkpoint_minutes": int(checkpoint.get("checkpoint_minutes", 0) or 0),
        "due_at": due_at.isoformat(),
        "evaluated_at": exit_at.isoformat(),
        "environment": str(checkpoint.get("environment", "paper") or "paper"),
        "mode": str(checkpoint.get("mode", "paper") or "paper"),
        "source_environment": str(
            checkpoint.get("source_environment", "shadow") or "shadow"
        ),
        "data_provider": str(checkpoint.get("data_provider", "alpaca") or "alpaca"),
        "execution_provider": str(
            checkpoint.get("execution_provider", "shadow") or "shadow"
        ),
        "outcome_status": outcome_status,
        "exit_price": round(exit_price, 8),
        "exit_price_gbp": round(exit_price_gbp, 8) if exit_price_gbp is not None else None,
        "effective_entry_price": round(effective_entry_price, 8),
        "effective_entry_price_gbp": (
            round(effective_entry_price_gbp, 8)
            if effective_entry_price_gbp is not None
            else None
        ),
        "effective_exit_price": round(effective_exit_price, 8),
        "effective_exit_price_gbp": (
            round(effective_exit_price_gbp, 8)
            if effective_exit_price_gbp is not None
            else None
        ),
        "gross_realized_return_pct": gross_realized_return_pct,
        "realized_return_pct_before_fixed_cost": realized_return_pct_before_fixed_cost,
        "realized_return_pct": realized_return_pct,
        "max_favorable_excursion_pct": max_favorable_excursion_pct,
        "max_adverse_excursion_pct": max_adverse_excursion_pct,
        "profit_target_ladder": profit_target_ladder,
        "effective_risk_pct": effective_risk_pct,
        "execution_spread_bps": round(float(execution_spread_bps), 6),
        "entry_slippage_bps": round(float(entry_slippage_bps), 6),
        "exit_slippage_bps": round(float(exit_slippage_bps), 6),
        "fixed_round_trip_cost_usd": round(fixed_round_trip_cost_usd, 6),
        "reference_notional_usd": round(float(trade_notional_usd), 6)
        if trade_notional_usd > 0
        else 0.0,
        "fixed_friction_return_pct": fixed_friction_return_pct,
        "net_profit_usd_on_reference_notional": (
            round((trade_notional_usd * realized_return_pct / 100.0), 6)
            if trade_notional_usd > 0
            else None
        ),
        "estimated_round_trip_friction_bps": round(
            max(0.0, execution_spread_bps)
            + max(0.0, entry_slippage_bps)
            + max(0.0, exit_slippage_bps),
            6,
        ),
        "fitness_score": _compute_fitness_score(
            outcome_status=outcome_status,
            realized_return_pct=realized_return_pct,
            risk_pct=effective_risk_pct,
        ),
        "bars_observed": len(observed_bars),
        "notes": notes,
    }


def _window_code_to_minutes(code: str) -> int:
    suffix = code[-1]
    raw_value = code[:-1]
    value = int(raw_value)
    if value <= 0:
        raise ValueError(f"Shadow checkpoint window must be positive: {code}")
    if suffix == "m":
        return value
    if suffix == "h":
        return value * 60
    if suffix == "d":
        return value * 60 * 24
    if suffix == "w":
        return value * 60 * 24 * 7
    raise ValueError(f"Unsupported shadow checkpoint window: {code}")


def _merge_checkpoint_windows(
    *,
    base_windows: list[CheckpointWindow],
    holding_window_code: str,
    holding_window_minutes: int,
) -> list[CheckpointWindow]:
    merged = {item.code: item for item in base_windows}
    if holding_window_code and holding_window_minutes > 0:
        merged[holding_window_code] = CheckpointWindow(
            code=holding_window_code,
            minutes=holding_window_minutes,
        )
    return sorted(merged.values(), key=lambda item: item.minutes)


def _profit_target_ladder_outcomes(
    *,
    entry_price: float,
    entry_price_gbp: float | None,
    stop_loss_price: float | None,
    bars: list[dict[str, Any]],
    due_at: datetime,
    target_pcts: tuple[float, ...],
    execution_spread_bps: float,
    entry_slippage_bps: float,
    exit_slippage_bps: float,
    fixed_round_trip_cost_usd: float,
    trade_notional_usd: float,
) -> list[dict[str, Any]]:
    if entry_price <= 0:
        return []

    effective_entry_price = _apply_long_entry_friction(
        price=entry_price,
        spread_bps=execution_spread_bps,
        slippage_bps=entry_slippage_bps,
    )
    if effective_entry_price <= 0:
        return []

    clean_targets = sorted({round(float(value), 6) for value in target_pcts if float(value) > 0})
    outcomes: list[dict[str, Any]] = []
    for target_pct in clean_targets:
        target_price = entry_price * (1.0 + (target_pct / 100.0))
        exit_at: datetime | None = None
        exit_price: float | None = None
        exit_price_gbp: float | None = None
        status = "not_hit_by_checkpoint"

        for bar in bars:
            captured_at = bar.get("captured_at")
            if not isinstance(captured_at, datetime) or captured_at >= due_at:
                break

            stop_hit = (
                stop_loss_price is not None
                and bar.get("low_price") is not None
                and float(bar["low_price"]) <= stop_loss_price
            )
            target_hit = (
                bar.get("high_price") is not None
                and float(bar["high_price"]) >= target_price
            )
            if stop_hit and target_hit:
                status = "ambiguous_stop_and_target"
                exit_at = captured_at
                exit_price = _to_float(bar.get("close_price")) or entry_price
                exit_price_gbp = _to_float(bar.get("close_price_gbp")) or entry_price_gbp
                break
            if stop_hit:
                status = "stop_hit_before_target"
                exit_at = captured_at
                exit_price = stop_loss_price
                exit_price_gbp = _convert_like_for_gbp(
                    entry_price=entry_price,
                    target_price=stop_loss_price,
                    entry_price_gbp=entry_price_gbp,
                )
                break
            if target_hit:
                status = "target_hit"
                exit_at = captured_at
                exit_price = target_price
                exit_price_gbp = _convert_like_for_gbp(
                    entry_price=entry_price,
                    target_price=target_price,
                    entry_price_gbp=entry_price_gbp,
                )
                break

        if exit_price is None:
            exit_bar = next(
                (
                    bar
                    for bar in bars
                    if isinstance(bar.get("captured_at"), datetime)
                    and bar["captured_at"] >= due_at
                ),
                None,
            )
            if exit_bar is not None:
                exit_at = exit_bar["captured_at"]
                exit_price = _to_float(exit_bar.get("close_price")) or entry_price
                exit_price_gbp = _to_float(exit_bar.get("close_price_gbp")) or entry_price_gbp

        effective_exit_price = (
            _apply_long_exit_friction(
                price=exit_price,
                spread_bps=execution_spread_bps,
                slippage_bps=exit_slippage_bps,
            )
            if exit_price is not None
            else None
        )
        realized_return_pct = None
        net_profit_usd = None
        if effective_exit_price is not None:
            before_fixed_cost = (
                (effective_exit_price - effective_entry_price) / effective_entry_price
            ) * 100.0
            fixed_cost_return_pct = (
                (max(0.0, fixed_round_trip_cost_usd) / trade_notional_usd) * 100.0
                if trade_notional_usd > 0
                else 0.0
            )
            realized_return_pct = round(before_fixed_cost - fixed_cost_return_pct, 6)
            net_profit_usd = (
                round(trade_notional_usd * realized_return_pct / 100.0, 6)
                if trade_notional_usd > 0
                else None
            )

        outcomes.append(
            {
                "target_pct": target_pct,
                "target_price": round(target_price, 8),
                "target_price_gbp": _convert_like_for_gbp(
                    entry_price=entry_price,
                    target_price=target_price,
                    entry_price_gbp=entry_price_gbp,
                ),
                "status": status,
                "target_hit": status == "target_hit",
                "ambiguous": status == "ambiguous_stop_and_target",
                "stop_hit_before_target": status == "stop_hit_before_target",
                "exit_at": exit_at.isoformat() if exit_at is not None else None,
                "exit_price": round(exit_price, 8) if exit_price is not None else None,
                "exit_price_gbp": (
                    round(exit_price_gbp, 8) if exit_price_gbp is not None else None
                ),
                "realized_return_pct": realized_return_pct,
                "net_profit_usd_on_reference_notional": net_profit_usd,
            }
        )
    return outcomes


def _build_proposal_id(
    *,
    tick_id: str,
    strategy_id: str,
    source: str,
    symbol: str,
) -> str:
    safe_strategy = strategy_id.lower().replace(".", "_")
    safe_source = source.lower().replace("/", "_")
    safe_symbol = symbol.upper().replace("/", "_")
    return f"{tick_id}:{safe_strategy}:{safe_source}:{safe_symbol}"


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_value(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [value for value in (_to_float(row.get(key)) for row in rows) if value is not None]
    if not values:
        return None
    return max(values)


def _min_value(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [value for value in (_to_float(row.get(key)) for row in rows) if value is not None]
    if not values:
        return None
    return min(values)


def _convert_like_for_gbp(
    *,
    entry_price: float,
    target_price: float,
    entry_price_gbp: float | None,
) -> float | None:
    if entry_price_gbp is None or entry_price == 0:
        return None
    return round(entry_price_gbp * (target_price / entry_price), 8)


def _apply_long_entry_friction(*, price: float, spread_bps: float, slippage_bps: float) -> float:
    total_bps = max(0.0, spread_bps / 2.0) + max(0.0, slippage_bps)
    adjusted = price * (1.0 + (total_bps / 10_000.0))
    return max(0.0, adjusted)


def _apply_long_exit_friction(*, price: float, spread_bps: float, slippage_bps: float) -> float:
    total_bps = max(0.0, spread_bps / 2.0) + max(0.0, slippage_bps)
    adjusted = price * (1.0 - (total_bps / 10_000.0))
    return max(0.0, adjusted)


def _effective_risk_pct(
    *,
    entry_price: float,
    stop_loss_price: float | None,
    fallback_risk_pct: float,
    execution_spread_bps: float,
    entry_slippage_bps: float,
    exit_slippage_bps: float,
) -> float:
    if stop_loss_price is None or stop_loss_price <= 0 or entry_price <= 0:
        return fallback_risk_pct

    effective_entry_price = _apply_long_entry_friction(
        price=entry_price,
        spread_bps=execution_spread_bps,
        slippage_bps=entry_slippage_bps,
    )
    effective_stop_price = _apply_long_exit_friction(
        price=stop_loss_price,
        spread_bps=execution_spread_bps,
        slippage_bps=exit_slippage_bps,
    )
    if effective_entry_price <= 0:
        return fallback_risk_pct

    effective_risk = ((effective_entry_price - effective_stop_price) / effective_entry_price) * 100.0
    if effective_risk <= 0:
        return fallback_risk_pct
    return round(effective_risk, 6)


def _scale_like_price(
    *,
    base_price: float | None,
    adjusted_price: float | None,
    base_like: float | None,
) -> float | None:
    if base_price in (None, 0) or adjusted_price is None or base_like is None:
        return base_like
    return round(base_like * (adjusted_price / base_price), 8)


def _compute_fitness_score(
    *,
    outcome_status: str,
    realized_return_pct: float,
    risk_pct: float,
) -> float:
    if outcome_status == "ambiguous_range":
        return 0.0
    if risk_pct <= 0:
        return round(realized_return_pct, 6)

    r_multiple = realized_return_pct / risk_pct
    score = r_multiple * 50.0
    if score > 100.0:
        score = 100.0
    if score < -100.0:
        score = -100.0
    return round(score, 6)
