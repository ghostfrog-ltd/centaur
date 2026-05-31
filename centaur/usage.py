from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import RuntimeConfig, SourcePricing
from app.core.instruments import default_instrument_registry
from .models import ApiUsageSummary, TickReport

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover
    psycopg2 = None
    sql = None
    RealDictCursor = None


class UsageLedger:
    """Persistence gateway for live operations, reports, and audit trails.

    PostgreSQL is the production operations store. SQLite remains available for
    explicit local/dev use, but a configured or required Postgres store must fail
    closed instead of silently rerouting live monitoring or control ticks.
    """

    def __init__(self, *, config: RuntimeConfig) -> None:
        self.config = config
        self.db_path = config.usage_ledger_db_path
        self.instrument_registry = default_instrument_registry()
        self.backend = "sqlite"
        self.backend_detail = str(self.db_path)
        self.fallback_reason: str | None = None

        if self._should_try_postgres():
            try:
                self._ensure_postgres_schema()
                self.backend = "postgres"
                self.backend_detail = (
                    f"postgres:{self.config.database_url_source or 'configured'}"
                    f"{self._postgres_schema_detail()}"
                )
                return
            except Exception as exc:  # pragma: no cover
                if self._postgres_required():
                    raise RuntimeError(
                        "PostgreSQL operations store is required but unavailable; "
                        "refusing SQLite fallback for live operation/monitoring."
                    ) from exc
                self.fallback_reason = f"{type(exc).__name__}: {exc}"
        elif self._postgres_required():
            raise RuntimeError(
                "PostgreSQL operations store is required but not available; "
                "check DATABASE_URL/POSTGRES_* settings and psycopg2 installation."
            )

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_sqlite_schema()
        if self.fallback_reason:
            self.backend_detail = f"{self.db_path} | fallback={self.fallback_reason}"

    def record_api_call(
        self,
        *,
        tick_id: str,
        requested_at: datetime,
        source: str,
        endpoint: str,
        request_count: int = 1,
        success: bool = True,
        input_units: int = 0,
        output_units: int = 0,
        estimated_cost_usd: float | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        usage_date = requested_at.date()
        cost = self._resolve_estimated_cost(
            source=source,
            request_count=request_count,
            input_units=input_units,
            output_units=output_units,
            estimated_cost_usd=estimated_cost_usd,
        )
        payload = {
            "usage_date": usage_date.isoformat(),
            "requested_at": requested_at.isoformat(),
            "tick_id": tick_id,
            "source": source,
            "endpoint": endpoint,
            "request_count": request_count,
            "success_count": request_count if success else 0,
            "error_count": 0 if success else request_count,
            "input_units": input_units,
            "output_units": output_units,
            "estimated_cost_usd": cost,
            "notes": notes,
            "metadata_json": self._to_json(metadata or {}),
        }

        if self.backend == "postgres":
            self._record_api_call_postgres(payload)
        else:
            self._record_api_call_sqlite(payload)

        return {
            "usage_date": usage_date.isoformat(),
            "source": source,
            "endpoint": endpoint,
            "request_count": request_count,
            "success": success,
            "input_units": input_units,
            "output_units": output_units,
            "estimated_cost_usd": cost,
            "notes": notes or "",
        }

    def record_tick_run(self, report: TickReport) -> bool:
        payload = {
            "tick_id": report.tick_id,
            "started_at": report.started_at.isoformat(),
            "ended_at": report.ended_at.isoformat(),
            "status": report.status,
            "duration_seconds": report.duration_seconds,
            "step_count": len(report.step_profiles),
            "error_count": len(
                [profile for profile in report.step_profiles if profile.status != "ok"]
            ),
            "tick_api_request_count": report.tick_api_request_count,
            "tick_estimated_cost_usd": report.tick_estimated_cost_usd,
            "daily_api_request_count": report.daily_api_request_count,
            "daily_estimated_cost_usd": report.daily_estimated_cost_usd,
            "budget_status": report.budget_status,
            "operations_backend": report.operations_backend,
            "last_error": self._last_error_message(report),
            "step_profiles_json": self._to_json(self._serialize_step_profiles(report)),
            "state_snapshot_json": self._to_json(report.state_snapshot),
        }

        if self.backend == "postgres":
            self._record_tick_run_postgres(payload)
        else:
            self._record_tick_run_sqlite(payload)
        return True

    def upsert_daily_protection_state(
        self,
        *,
        session_date: date,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str = "",
    ) -> dict[str, Any]:
        if self.backend == "postgres":
            row = self._upsert_daily_protection_state_postgres(
                session_date=session_date,
                market_open_at=market_open_at,
                tick_id=tick_id,
                checked_at=checked_at,
                current_equity=current_equity,
                max_daily_drawdown_usd=max_daily_drawdown_usd,
                system_status=system_status,
                notes=notes,
            )
        else:
            row = self._upsert_daily_protection_state_sqlite(
                session_date=session_date,
                market_open_at=market_open_at,
                tick_id=tick_id,
                checked_at=checked_at,
                current_equity=current_equity,
                max_daily_drawdown_usd=max_daily_drawdown_usd,
                system_status=system_status,
                notes=notes,
            )
        return self._normalize_daily_protection_row(row)

    def increment_daily_stale_order_count(
        self,
        *,
        session_date: date,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> int:
        if count <= 0:
            row = self.get_daily_protection_state(session_date=session_date)
            return int(row.get("stale_orders_reaped_count", 0) or 0) if row else 0
        if self.backend == "postgres":
            row = self._increment_daily_stale_order_count_postgres(
                session_date=session_date,
                tick_id=tick_id,
                checked_at=checked_at,
                count=count,
            )
        else:
            row = self._increment_daily_stale_order_count_sqlite(
                session_date=session_date,
                tick_id=tick_id,
                checked_at=checked_at,
                count=count,
            )
        normalized = self._normalize_daily_protection_row(row) if row else {}
        return int(normalized.get("stale_orders_reaped_count", 0) or 0)

    def get_daily_protection_state(self, *, session_date: date) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_daily_protection_state_postgres(session_date=session_date)
        else:
            row = self._get_daily_protection_state_sqlite(session_date=session_date)
        if row is None:
            return None
        return self._normalize_daily_protection_row(row)

    def upsert_broker_daily_protection_state(
        self,
        *,
        session_date: date,
        broker_id: str,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create/update a broker-specific daily drawdown protection row.

        Live readiness uses this instead of the paper-only table so each broker
        can keep an independent session baseline, protection latch, stale-order
        count, and audit note trail.
        """
        if self.backend == "postgres":
            row = self._upsert_broker_daily_protection_state_postgres(
                session_date=session_date,
                broker_id=broker_id,
                market_open_at=market_open_at,
                tick_id=tick_id,
                checked_at=checked_at,
                current_equity=current_equity,
                max_daily_drawdown_usd=max_daily_drawdown_usd,
                system_status=system_status,
                notes=notes,
            )
        else:
            row = self._upsert_broker_daily_protection_state_sqlite(
                session_date=session_date,
                broker_id=broker_id,
                market_open_at=market_open_at,
                tick_id=tick_id,
                checked_at=checked_at,
                current_equity=current_equity,
                max_daily_drawdown_usd=max_daily_drawdown_usd,
                system_status=system_status,
                notes=notes,
            )
        return self._normalize_daily_protection_row(row)

    def get_broker_daily_protection_state(
        self,
        *,
        session_date: date,
        broker_id: str,
    ) -> dict[str, Any] | None:
        """Return the broker-specific session protection row if it exists."""
        if self.backend == "postgres":
            row = self._get_broker_daily_protection_state_postgres(
                session_date=session_date,
                broker_id=broker_id,
            )
        else:
            row = self._get_broker_daily_protection_state_sqlite(
                session_date=session_date,
                broker_id=broker_id,
            )
        if row is None:
            return None
        return self._normalize_daily_protection_row(row)

    def increment_broker_daily_stale_order_count(
        self,
        *,
        session_date: date,
        broker_id: str,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> int:
        """Record broker-specific stale-order cleanup in the protection audit."""
        if count <= 0:
            row = self.get_broker_daily_protection_state(
                session_date=session_date,
                broker_id=broker_id,
            )
            return int(row.get("stale_orders_reaped_count", 0) or 0) if row else 0
        if self.backend == "postgres":
            row = self._increment_broker_daily_stale_order_count_postgres(
                session_date=session_date,
                broker_id=broker_id,
                tick_id=tick_id,
                checked_at=checked_at,
                count=count,
            )
        else:
            row = self._increment_broker_daily_stale_order_count_sqlite(
                session_date=session_date,
                broker_id=broker_id,
                tick_id=tick_id,
                checked_at=checked_at,
                count=count,
            )
        normalized = self._normalize_daily_protection_row(row) if row else {}
        return int(normalized.get("stale_orders_reaped_count", 0) or 0)

    def backfill_api_costs(self) -> dict[str, Any]:
        if self.backend == "postgres":
            return self._backfill_api_costs_postgres()
        return self._backfill_api_costs_sqlite()

    def record_latest_bars(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        source: str,
        bars_by_symbol: dict[str, dict[str, Any]],
        quote_currency: str = "USD",
        usd_to_gbp: float | None = None,
    ) -> int:
        rows = []
        for symbol, bar in bars_by_symbol.items():
            open_price = self._to_float(bar.get("o"))
            high_price = self._to_float(bar.get("h"))
            low_price = self._to_float(bar.get("l"))
            close_price = self._to_float(bar.get("c"))
            asset_class = str(bar.get("asset_class") or "").strip().lower()
            if not asset_class:
                source_text = str(source or "").strip().lower()
                asset_class = "crypto" if "crypto" in source_text or "/" in symbol else "equity"
            instrument = self._instrument_metadata(
                item=bar,
                symbol=str(symbol),
                asset_class=asset_class,
                source=source,
            )

            rows.append(
                {
                    "tick_id": tick_id,
                    "captured_at": captured_at.isoformat(),
                    "source": source,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "canonical_instrument_id": instrument["canonical_instrument_id"],
                    "venue": instrument["venue"],
                    "venue_symbol": instrument["venue_symbol"],
                    "bar_timestamp": bar.get("t"),
                    "quote_currency": quote_currency,
                    "usd_to_gbp_rate": usd_to_gbp,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "open_price_gbp": self._convert_to_gbp(
                        open_price,
                        quote_currency=quote_currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "high_price_gbp": self._convert_to_gbp(
                        high_price,
                        quote_currency=quote_currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "low_price_gbp": self._convert_to_gbp(
                        low_price,
                        quote_currency=quote_currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "close_price_gbp": self._convert_to_gbp(
                        close_price,
                        quote_currency=quote_currency,
                        usd_to_gbp=usd_to_gbp,
                    ),
                    "volume": bar.get("v"),
                    "trade_count": bar.get("n"),
                    "vwap": self._to_float(bar.get("vw")),
                    "raw_json": self._to_json(bar),
                }
            )

        if not rows:
            return 0

        if self.backend == "postgres":
            self._record_latest_bars_postgres(rows)
        else:
            self._record_latest_bars_sqlite(rows)
        return len(rows)

    def record_historical_bars(
        self,
        *,
        batch_id: str,
        captured_at: datetime,
        source: str,
        asset_class: str,
        timeframe: str,
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        quote_currency: str = "USD",
        usd_to_gbp: float | None = None,
    ) -> int:
        rows = []
        for symbol, bars in bars_by_symbol.items():
            for bar in bars:
                open_price = self._to_float(bar.get("o"))
                high_price = self._to_float(bar.get("h"))
                low_price = self._to_float(bar.get("l"))
                close_price = self._to_float(bar.get("c"))
                instrument = self._instrument_metadata(
                    item=bar,
                    symbol=str(symbol),
                    asset_class=asset_class,
                    source=source,
                )
                rows.append(
                    {
                        "batch_id": batch_id,
                        "captured_at": captured_at.isoformat(),
                        "source": source,
                        "asset_class": asset_class,
                        "canonical_instrument_id": instrument["canonical_instrument_id"],
                        "venue": instrument["venue"],
                        "venue_symbol": instrument["venue_symbol"],
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "bar_timestamp": bar.get("t"),
                        "quote_currency": quote_currency,
                        "usd_to_gbp_rate": usd_to_gbp,
                        "open_price": open_price,
                        "high_price": high_price,
                        "low_price": low_price,
                        "close_price": close_price,
                        "open_price_gbp": self._convert_to_gbp(
                            open_price,
                            quote_currency=quote_currency,
                            usd_to_gbp=usd_to_gbp,
                        ),
                        "high_price_gbp": self._convert_to_gbp(
                            high_price,
                            quote_currency=quote_currency,
                            usd_to_gbp=usd_to_gbp,
                        ),
                        "low_price_gbp": self._convert_to_gbp(
                            low_price,
                            quote_currency=quote_currency,
                            usd_to_gbp=usd_to_gbp,
                        ),
                        "close_price_gbp": self._convert_to_gbp(
                            close_price,
                            quote_currency=quote_currency,
                            usd_to_gbp=usd_to_gbp,
                        ),
                        "volume": bar.get("v"),
                        "trade_count": bar.get("n"),
                        "vwap": self._to_float(bar.get("vw")),
                        "raw_json": self._to_json(bar),
                    }
                )

        if not rows:
            return 0

        if self.backend == "postgres":
            self._record_historical_bars_postgres(rows)
        else:
            self._record_historical_bars_sqlite(rows)
        return len(rows)

    def record_fx_reference_rate(self, *, rate: dict[str, Any]) -> None:
        if self.backend == "postgres":
            self._record_fx_reference_rate_postgres(rate)
        else:
            self._record_fx_reference_rate_sqlite(rate)

    def record_discovery_candidates(
        self,
        *,
        tick_id: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        if self.backend == "postgres":
            self._record_discovery_candidates_postgres(
                tick_id=tick_id,
                candidates=candidates,
            )
        else:
            self._record_discovery_candidates_sqlite(
                tick_id=tick_id,
                candidates=candidates,
            )

    def record_gemini_analyses(
        self,
        *,
        tick_id: str,
        analyses: list[dict[str, Any]],
    ) -> None:
        if self.backend == "postgres":
            self._record_gemini_analyses_postgres(
                tick_id=tick_id,
                analyses=analyses,
            )
        else:
            self._record_gemini_analyses_sqlite(
                tick_id=tick_id,
                analyses=analyses,
            )

    def record_strategy_candidate_signals(
        self,
        *,
        tick_id: str,
        signals: list[dict[str, Any]],
    ) -> None:
        signals = [self._with_instrument_metadata(item) for item in signals]
        if self.backend == "postgres":
            self._record_strategy_candidate_signals_postgres(
                tick_id=tick_id,
                signals=signals,
            )
        else:
            self._record_strategy_candidate_signals_sqlite(
                tick_id=tick_id,
                signals=signals,
            )

    def get_strategy_threshold_adaptive_state(self) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_strategy_threshold_adaptive_state_postgres()
        else:
            row = self._get_strategy_threshold_adaptive_state_sqlite()
        if row is None:
            return None
        normalized = dict(row)
        if "updated_at" in normalized:
            normalized["updated_at"] = self._normalize_db_datetime_value(
                normalized["updated_at"]
            )
        if "advice_json" in normalized:
            normalized["advice_json"] = self._from_json(
                normalized["advice_json"],
                default={},
            )
        return normalized

    def record_strategy_threshold_adaptive_state(
        self,
        *,
        effective_threshold: float,
        updated_at: datetime,
        source_tick_id: str,
        reason: str,
        advice: dict[str, Any],
    ) -> None:
        row = {
            "state_id": "current",
            "effective_threshold": float(effective_threshold),
            "updated_at": updated_at.isoformat(),
            "source_tick_id": str(source_tick_id),
            "reason": str(reason),
            "advice_json": self._to_json(advice),
        }
        if self.backend == "postgres":
            self._record_strategy_threshold_adaptive_state_postgres(row=row)
        else:
            self._record_strategy_threshold_adaptive_state_sqlite(row=row)

    def record_paper_trade_orders(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        orders: list[dict[str, Any]],
        broker_id: str | None = None,
    ) -> int:
        if not orders:
            return 0

        rows = [
            self._paper_order_row(
                tick_id=tick_id,
                captured_at=captured_at,
                order=order,
                broker_id=broker_id,
            )
            for order in orders
        ]
        rows = [row for row in rows if row["order_id"]]
        if not rows:
            return 0
        if self.backend == "postgres":
            self._record_paper_trade_orders_postgres(rows=rows)
        else:
            self._record_paper_trade_orders_sqlite(rows=rows)
        return len(rows)

    def record_broker_account_snapshot(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        broker_id: str,
        summary: dict[str, Any],
        raw_account: dict[str, Any],
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        row = self._broker_account_snapshot_row(
            tick_id=tick_id,
            captured_at=captured_at,
            broker_id=broker_id,
            summary=summary,
            raw_account=raw_account,
            positions=positions or [],
        )
        if self.backend == "postgres":
            self._record_broker_account_snapshots_postgres(rows=[row])
        else:
            self._record_broker_account_snapshots_sqlite(rows=[row])

    def record_execution_router_intent(
        self,
        *,
        tick_id: str,
        recorded_at: datetime,
        environment: str,
        mode: str,
        lane: str,
        action: str,
        broker_id: str,
        status: str,
        strategy_id: str = "",
        intended_order: dict[str, Any] | None = None,
    ) -> None:
        """Persist dry-run/router intents for audit without mutating brokers."""
        order_payload = intended_order or {}
        symbol = str(order_payload.get("symbol") or "").strip().upper()
        order_id = str(order_payload.get("order_id") or "").strip()
        asset_class = str(order_payload.get("asset_class") or "").strip().lower()
        if not asset_class:
            asset_class = "crypto" if "/" in symbol else "equity"
        instrument = self._instrument_metadata(
            item=order_payload,
            symbol=symbol,
            asset_class=asset_class,
            broker_id=broker_id,
        )
        row = {
            "tick_id": str(tick_id),
            "recorded_at": recorded_at.isoformat(),
            "environment": str(environment or "").strip().lower() or "paper",
            "mode": str(mode or "").strip().lower() or "paper",
            "lane": str(lane or "").strip().lower(),
            "action": str(action or "").strip().lower(),
            "broker_id": str(broker_id or "").strip().lower(),
            "status": str(status or "").strip().lower(),
            "strategy_id": str(strategy_id or ""),
            "symbol": symbol,
            "order_id": order_id,
            "canonical_instrument_id": instrument["canonical_instrument_id"],
            "venue": instrument["venue"],
            "venue_symbol": instrument["venue_symbol"],
            "intended_order_json": self._to_json(order_payload),
        }
        if self.backend == "postgres":
            self._record_execution_router_intent_postgres(row=row)
        else:
            self._record_execution_router_intent_sqlite(row=row)

    def record_shadow_trade_proposals(
        self,
        *,
        proposals: list[dict[str, Any]],
    ) -> None:
        proposals = [self._with_instrument_metadata(item) for item in proposals]
        if self.backend == "postgres":
            self._record_shadow_trade_proposals_postgres(proposals=proposals)
        else:
            self._record_shadow_trade_proposals_sqlite(proposals=proposals)

    def record_shadow_trade_outcomes(
        self,
        *,
        outcomes: list[dict[str, Any]],
    ) -> int:
        if not outcomes:
            return 0

        outcomes = [self._with_instrument_metadata(item) for item in outcomes]
        if self.backend == "postgres":
            self._record_shadow_trade_outcomes_postgres(outcomes=outcomes)
        else:
            self._record_shadow_trade_outcomes_sqlite(outcomes=outcomes)
        return len(outcomes)

    def record_strategy_fitness_snapshots(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        summaries: list[dict[str, Any]],
        environment: str = "paper",
        mode: str = "paper",
        source_environment: str = "shadow",
        broker_id: str = "alpaca_paper",
        data_provider: str = "alpaca",
        execution_provider: str = "shadow",
    ) -> int:
        if not summaries:
            return 0

        rows = []
        for item in summaries:
            row = {
                "tick_id": tick_id,
                "captured_at": captured_at.isoformat(),
                "environment": str(item.get("environment") or environment or "paper"),
                "mode": str(item.get("mode") or mode or "paper"),
                "source_environment": str(
                    item.get("source_environment") or source_environment or "shadow"
                ),
                "broker_id": str(item.get("broker_id") or broker_id or ""),
                "data_provider": str(
                    item.get("data_provider") or data_provider or "alpaca"
                ),
                "execution_provider": str(
                    item.get("execution_provider") or execution_provider or "shadow"
                ),
                "strategy_id": str(item.get("strategy_id", "")),
                "strategy_family": str(item.get("strategy_family", "")),
                "profile_id": str(item.get("profile_id", "")),
                "asset_class": str(item.get("asset_class", "")),
                "checkpoint_code": str(item.get("checkpoint_code", "")),
                "lookback_days": int(item.get("lookback_days", 0) or 0),
                "fitness_rank": int(item.get("fitness_rank", 0) or 0),
                "evaluated_proposals": int(item.get("evaluated_proposals", 0) or 0),
                "checkpoints_evaluated": int(item.get("checkpoints_evaluated", 0) or 0),
                "win_count": int(item.get("win_count", 0) or 0),
                "loss_count": int(item.get("loss_count", 0) or 0),
                "target_hit_count": int(item.get("target_hit_count", 0) or 0),
                "stop_hit_count": int(item.get("stop_hit_count", 0) or 0),
                "time_exit_count": int(item.get("time_exit_count", 0) or 0),
                "ambiguous_count": int(item.get("ambiguous_count", 0) or 0),
                "win_rate": float(item.get("win_rate", 0) or 0),
                "loss_rate": float(item.get("loss_rate", 0) or 0),
                "target_hit_rate": float(item.get("target_hit_rate", 0) or 0),
                "stop_hit_rate": float(item.get("stop_hit_rate", 0) or 0),
                "time_exit_rate": float(item.get("time_exit_rate", 0) or 0),
                "ambiguous_rate": float(item.get("ambiguous_rate", 0) or 0),
                "avg_fitness_score": float(item.get("avg_fitness_score", 0) or 0),
                "avg_realized_return_pct": float(
                    item.get("avg_realized_return_pct", 0) or 0
                ),
                "avg_max_favorable_excursion_pct": float(
                    item.get("avg_max_favorable_excursion_pct", 0) or 0
                ),
                "avg_max_adverse_excursion_pct": float(
                    item.get("avg_max_adverse_excursion_pct", 0) or 0
                ),
                "avg_signal_score": float(item.get("avg_signal_score", 0) or 0),
                "avg_signal_confidence": float(
                    item.get("avg_signal_confidence", 0) or 0
                ),
                "avg_discovery_score": float(item.get("avg_discovery_score", 0) or 0),
                "sample_weight": float(item.get("sample_weight", 0) or 0),
                "composite_fitness_score": float(
                    item.get("composite_fitness_score", 0) or 0
                ),
                "first_proposed_at": item.get("first_proposed_at"),
                "last_evaluated_at": item.get("last_evaluated_at"),
                "raw_json": self._to_json(item),
            }
            rows.append(row)

        if self.backend == "postgres":
            self._record_strategy_fitness_snapshots_postgres(rows)
        else:
            self._record_strategy_fitness_snapshots_sqlite(rows)
        return len(rows)

    def list_recent_shadow_proposal_keys(
        self,
        *,
        since: datetime,
    ) -> set[tuple[str, str, str]]:
        if self.backend == "postgres":
            rows = self._list_recent_shadow_proposal_keys_postgres(since=since)
        else:
            rows = self._list_recent_shadow_proposal_keys_sqlite(since=since)
        return {
            (
                str(row["strategy_id"]),
                str(row["source"]),
                str(row["symbol"]).upper(),
            )
            for row in rows
            if row.get("strategy_id") and row.get("source") and row.get("symbol")
        }

    def list_due_shadow_trade_outcomes(
        self,
        *,
        as_of: datetime,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_due_shadow_trade_outcomes_postgres(
                as_of=as_of,
                limit=limit,
            )
        else:
            rows = self._list_due_shadow_trade_outcomes_sqlite(
                as_of=as_of,
                limit=limit,
            )

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("proposed_at", "due_at", "evaluated_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            if "raw_json" in normalized:
                normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
            normalized_rows.append(normalized)
        return normalized_rows

    def list_strategy_fitness_rows(
        self,
        *,
        as_of: datetime,
        lookback_days: int = 0,
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_strategy_fitness_rows_postgres(
                as_of=as_of,
                lookback_days=lookback_days,
            )
        else:
            rows = self._list_strategy_fitness_rows_sqlite(
                as_of=as_of,
                lookback_days=lookback_days,
            )

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("first_proposed_at", "last_evaluated_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            normalized_rows.append(normalized)
        return normalized_rows

    def list_shadow_proposal_events(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_shadow_proposal_events_postgres(
                start_at=start_at,
                end_at=end_at,
            )
        else:
            rows = self._list_shadow_proposal_events_sqlite(
                start_at=start_at,
                end_at=end_at,
            )

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if "proposed_at" in normalized:
                normalized["proposed_at"] = self._normalize_db_datetime_value(
                    normalized["proposed_at"]
                )
            normalized_rows.append(normalized)
        return normalized_rows

    def get_market_bars_for_window(
        self,
        *,
        source: str,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for timeframe in self._preferred_historical_timeframes(
            start_at=start_at,
            end_at=end_at,
        ):
            if self.backend == "postgres":
                rows = self._get_historical_bars_for_window_postgres(
                    source=source,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_at=start_at,
                    end_at=end_at,
                )
            else:
                rows = self._get_historical_bars_for_window_sqlite(
                    source=source,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_at=start_at,
                    end_at=end_at,
                )
            if rows:
                break

        if not rows:
            if self.backend == "postgres":
                rows = self._get_market_bars_for_window_postgres(
                    source=source,
                    symbol=symbol,
                    start_at=start_at,
                    end_at=end_at,
                )
            else:
                rows = self._get_market_bars_for_window_sqlite(
                    source=source,
                    symbol=symbol,
                    start_at=start_at,
                    end_at=end_at,
                )

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("captured_at", "bar_timestamp"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            normalized_rows.append(normalized)
        return normalized_rows

    def get_latest_fx_reference(self, *, source: str) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_latest_fx_reference_postgres(source=source)
        else:
            row = self._get_latest_fx_reference_sqlite(source=source)

        if row is None:
            return None

        normalized = dict(row)
        provider_date = normalized.get("provider_date")
        if hasattr(provider_date, "isoformat"):
            normalized["provider_date"] = provider_date.isoformat()

        fetched_at = normalized.get("fetched_at")
        if isinstance(fetched_at, str):
            normalized["fetched_at"] = datetime.fromisoformat(fetched_at)
        return normalized

    def get_latest_bars_for_tick(
        self,
        *,
        tick_id: str,
        sources: list[str],
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            return self._get_latest_bars_for_tick_postgres(
                tick_id=tick_id,
                sources=sources,
            )
        return self._get_latest_bars_for_tick_sqlite(tick_id=tick_id, sources=sources)

    def list_historical_bars(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_historical_bars_postgres(
                timeframe=timeframe,
                sources=sources,
                start_at=start_at,
                end_at=end_at,
                symbols=symbols or [],
            )
        else:
            rows = self._list_historical_bars_sqlite(
                timeframe=timeframe,
                sources=sources,
                start_at=start_at,
                end_at=end_at,
                symbols=symbols or [],
            )

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if "bar_timestamp" in normalized:
                normalized["bar_timestamp"] = self._normalize_db_datetime_value(
                    normalized["bar_timestamp"]
                )
            if "captured_at" in normalized:
                normalized["captured_at"] = self._normalize_db_datetime_value(
                    normalized["captured_at"]
                )
            normalized_rows.append(normalized)
        return normalized_rows

    def get_previous_bars(
        self,
        *,
        tick_id: str,
        symbol_keys: list[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if self.backend == "postgres":
            return self._get_previous_bars_postgres(
                tick_id=tick_id,
                symbol_keys=symbol_keys,
            )
        return self._get_previous_bars_sqlite(tick_id=tick_id, symbol_keys=symbol_keys)

    def list_daily_usage(self, *, usage_date: date) -> list[ApiUsageSummary]:
        if self.backend == "postgres":
            rows = self._list_daily_usage_postgres(usage_date=usage_date)
        else:
            rows = self._list_daily_usage_sqlite(usage_date=usage_date)
        return [self._row_to_summary(row) for row in rows]

    def list_tick_usage(self, *, tick_id: str, usage_date: date) -> list[ApiUsageSummary]:
        if self.backend == "postgres":
            rows = self._list_tick_usage_postgres(tick_id=tick_id, usage_date=usage_date)
        else:
            rows = self._list_tick_usage_sqlite(tick_id=tick_id, usage_date=usage_date)
        return [self._row_to_summary(row) for row in rows]

    def get_latest_tick_run(self) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_latest_tick_run_postgres()
        else:
            row = self._get_latest_tick_run_sqlite()
        if row is None:
            return None

        normalized = dict(row)
        for key in ("started_at", "ended_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        for key in ("step_profiles_json", "state_snapshot_json"):
            if key in normalized:
                normalized[key] = self._from_json(normalized[key], default={})
        return normalized

    def get_first_tick_run(self) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_first_tick_run_postgres()
        else:
            row = self._get_first_tick_run_sqlite()
        if row is None:
            return None

        normalized = dict(row)
        for key in ("started_at", "ended_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        for key in ("step_profiles_json", "state_snapshot_json"):
            if key in normalized:
                normalized[key] = self._from_json(normalized[key], default={})
        return normalized

    def get_first_account_tick_run(self) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_first_account_tick_run_postgres()
        else:
            row = self._get_first_account_tick_run_sqlite()
        if row is None:
            return None

        normalized = dict(row)
        for key in ("started_at", "ended_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        for key in ("step_profiles_json", "state_snapshot_json"):
            if key in normalized:
                normalized[key] = self._from_json(normalized[key], default={})
        return normalized

    def get_latest_tick_run_before(self, *, started_before: datetime) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_latest_tick_run_before_postgres(started_before=started_before)
        else:
            row = self._get_latest_tick_run_before_sqlite(started_before=started_before)
        if row is None:
            return None

        normalized = dict(row)
        for key in ("started_at", "ended_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        for key in ("step_profiles_json", "state_snapshot_json"):
            if key in normalized:
                normalized[key] = self._from_json(normalized[key], default={})
        return normalized

    def get_tick_run(self, *, tick_id: str) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_tick_run_postgres(tick_id=tick_id)
        else:
            row = self._get_tick_run_sqlite(tick_id=tick_id)
        if row is None:
            return None

        normalized = dict(row)
        for key in ("started_at", "ended_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        for key in ("step_profiles_json", "state_snapshot_json"):
            if key in normalized:
                normalized[key] = self._from_json(normalized[key], default={})
        return normalized

    def _normalize_daily_protection_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        session_date = normalized.get("session_date")
        if hasattr(session_date, "isoformat"):
            normalized["session_date"] = session_date.isoformat()
        for key in (
            "market_open_at",
            "first_checked_at",
            "last_checked_at",
            "protection_triggered_at",
        ):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        return normalized

    def list_recent_paper_trade_orders(self, *, limit: int = 5) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_recent_paper_trade_orders_postgres(limit=limit)
        else:
            rows = self._list_recent_paper_trade_orders_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("captured_at", "submitted_at", "updated_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            if "raw_json" in normalized:
                normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
            normalized_rows.append(normalized)
        return normalized_rows

    def list_recent_broker_account_snapshots(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_recent_broker_account_snapshots_postgres(limit=limit)
        else:
            rows = self._list_recent_broker_account_snapshots_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if "captured_at" in normalized:
                normalized["captured_at"] = self._normalize_db_datetime_value(
                    normalized["captured_at"]
                )
            if "raw_json" in normalized:
                normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
            normalized_rows.append(normalized)
        return normalized_rows

    def list_recent_execution_router_intents(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_recent_execution_router_intents_postgres(limit=limit)
        else:
            rows = self._list_recent_execution_router_intents_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if "recorded_at" in normalized:
                normalized["recorded_at"] = self._normalize_db_datetime_value(
                    normalized["recorded_at"]
                )
            if "intended_order_json" in normalized:
                normalized["intended_order_json"] = self._from_json(
                    normalized["intended_order_json"],
                    default={},
                )
            normalized_rows.append(normalized)
        return normalized_rows

    def get_broker_account_high_water(
        self,
        *,
        broker_id: str,
        since: datetime,
    ) -> dict[str, Any] | None:
        """Return the highest recorded equity for a broker since a session start.

        The trailing-drawdown observer uses this as read-only evidence. It does
        not mutate protection state or trading gates; the persisted tick snapshot
        records what a future high-water guard would have done.
        """
        normalized_broker_id = str(broker_id).strip().lower()
        if not normalized_broker_id:
            return None
        if self.backend == "postgres":
            row = self._get_broker_account_high_water_postgres(
                broker_id=normalized_broker_id,
                since=since,
            )
        else:
            row = self._get_broker_account_high_water_sqlite(
                broker_id=normalized_broker_id,
                since=since,
            )
        if row is None:
            return None
        normalized = dict(row)
        if "captured_at" in normalized:
            normalized["captured_at"] = self._normalize_db_datetime_value(
                normalized["captured_at"]
            )
        if "raw_json" in normalized:
            normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
        return normalized

    def get_first_paper_trade_order(self, *, broker_id: str | None = None) -> dict[str, Any] | None:
        if self.backend == "postgres":
            row = self._get_first_paper_trade_order_postgres(broker_id=broker_id)
        else:
            row = self._get_first_paper_trade_order_sqlite(broker_id=broker_id)
        if row is None:
            return None

        normalized = dict(row)
        for key in ("captured_at", "submitted_at", "updated_at"):
            if key in normalized:
                normalized[key] = self._normalize_db_datetime_value(normalized[key])
        if "raw_json" in normalized:
            normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
        return normalized

    def list_recent_shadow_trade_proposals(self, *, limit: int = 5) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_recent_shadow_trade_proposals_postgres(limit=limit)
        else:
            rows = self._list_recent_shadow_trade_proposals_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            if "proposed_at" in normalized:
                normalized["proposed_at"] = self._normalize_db_datetime_value(
                    normalized["proposed_at"]
                )
            if "raw_json" in normalized:
                normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
            normalized_rows.append(normalized)
        return normalized_rows

    def get_shadow_trade_proposal(self, *, proposal_id: str) -> dict[str, Any] | None:
        normalized_proposal_id = str(proposal_id).strip()
        if not normalized_proposal_id:
            return None
        if self.backend == "postgres":
            row = self._get_shadow_trade_proposal_postgres(
                proposal_id=normalized_proposal_id
            )
        else:
            row = self._get_shadow_trade_proposal_sqlite(
                proposal_id=normalized_proposal_id
            )
        if row is None:
            return None

        normalized = dict(row)
        if "proposed_at" in normalized:
            normalized["proposed_at"] = self._normalize_db_datetime_value(
                normalized["proposed_at"]
            )
        if "raw_json" in normalized:
            normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
        return normalized

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_recent_tick_runs_postgres(limit=limit)
        else:
            rows = self._list_recent_tick_runs_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("started_at", "ended_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            if "state_snapshot_json" in normalized:
                normalized["state_snapshot_json"] = self._from_json(
                    normalized["state_snapshot_json"],
                    default={},
                )
            normalized_rows.append(normalized)
        return normalized_rows

    def list_latest_strategy_fitness_snapshots(self, *, limit: int = 8) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_latest_strategy_fitness_snapshots_postgres(limit=limit)
        else:
            rows = self._list_latest_strategy_fitness_snapshots_sqlite(limit=limit)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("captured_at", "first_proposed_at", "last_evaluated_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            if "raw_json" in normalized:
                normalized["raw_json"] = self._from_json(normalized["raw_json"], default={})
            normalized_rows.append(normalized)
        return normalized_rows

    def list_strategy_training_volume(self) -> list[dict[str, Any]]:
        if self.backend == "postgres":
            rows = self._list_strategy_training_volume_postgres()
        else:
            rows = self._list_strategy_training_volume_sqlite()

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for key in ("first_proposed_at", "last_proposed_at"):
                if key in normalized:
                    normalized[key] = self._normalize_db_datetime_value(normalized[key])
            normalized_rows.append(normalized)
        return normalized_rows

    def total_requests(self, summaries: list[ApiUsageSummary]) -> int:
        return sum(item.request_count for item in summaries)

    def total_estimated_cost_usd(self, summaries: list[ApiUsageSummary]) -> float:
        return sum(item.estimated_cost_usd for item in summaries)

    def budget_status(self, *, daily_estimated_cost_usd: float) -> str:
        if daily_estimated_cost_usd >= self.config.api_daily_cost_limit_usd:
            return "limit_exceeded"
        if daily_estimated_cost_usd >= self.config.api_daily_cost_warning_usd:
            return "warning"
        return "within_limit"

    def _should_try_postgres(self) -> bool:
        preference = self.config.operations_db_backend_preference
        if preference == "sqlite":
            return False
        if not self.config.postgres_configured or not self.config.database_url:
            return False
        if psycopg2 is None:
            return False
        return True

    def _postgres_required(self) -> bool:
        preference = self.config.operations_db_backend_preference
        if self.config.paper_execution_enabled or self.config.live_execution_enabled:
            return True
        if preference == "postgres":
            return True
        if preference == "sqlite":
            return False
        return bool(self.config.postgres_configured)

    def _resolve_estimated_cost(
        self,
        *,
        source: str,
        request_count: int,
        input_units: int,
        output_units: int,
        estimated_cost_usd: float | None,
    ) -> float:
        if estimated_cost_usd is not None:
            return round(float(estimated_cost_usd), 8)

        pricing = self.config.provider_pricing.get(source, SourcePricing(source=source))
        per_request_cost = request_count * pricing.cost_per_request_usd
        input_cost = (
            input_units / 1_000_000
        ) * pricing.input_cost_per_million_units_usd
        output_cost = (
            output_units / 1_000_000
        ) * pricing.output_cost_per_million_units_usd
        return round(per_request_cost + input_cost + output_cost, 8)

    def _build_repriced_api_event_updates(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[tuple[float, Any]], dict[str, Any]]:
        updates: list[tuple[float, Any]] = []
        events_scanned = 0
        events_cost_changed = 0
        zero_cost_events = 0
        gemini_events_scanned = 0
        gemini_events_with_tokens = 0
        gemini_events_nonzero_cost = 0

        for row in rows:
            events_scanned += 1
            source = str(row.get("source", "") or "")
            request_count = int(row.get("request_count", 0) or 0)
            input_units = int(row.get("input_units", 0) or 0)
            output_units = int(row.get("output_units", 0) or 0)
            existing_cost = round(float(row.get("estimated_cost_usd", 0) or 0), 8)
            repriced_cost = self._resolve_estimated_cost(
                source=source,
                request_count=request_count,
                input_units=input_units,
                output_units=output_units,
                estimated_cost_usd=None,
            )

            if abs(existing_cost - repriced_cost) > 1e-9:
                events_cost_changed += 1
            if repriced_cost <= 0:
                zero_cost_events += 1
            if source == "gemini_api":
                gemini_events_scanned += 1
                if input_units > 0 or output_units > 0:
                    gemini_events_with_tokens += 1
                if repriced_cost > 0:
                    gemini_events_nonzero_cost += 1

            updates.append((repriced_cost, row["id"]))

        return updates, {
            "events_scanned": events_scanned,
            "events_cost_changed": events_cost_changed,
            "zero_cost_events": zero_cost_events,
            "gemini_events_scanned": gemini_events_scanned,
            "gemini_events_with_tokens": gemini_events_with_tokens,
            "gemini_events_nonzero_cost": gemini_events_nonzero_cost,
        }

    def _build_daily_total_map(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        totals: dict[str, dict[str, Any]] = {}
        for row in rows:
            usage_date_key = self._normalize_usage_date_key(row.get("usage_date"))
            totals[usage_date_key] = {
                "request_count": int(row.get("request_count", 0) or 0),
                "estimated_cost_usd": round(
                    float(row.get("estimated_cost_usd", 0) or 0),
                    8,
                ),
            }
        return totals

    def _build_tick_total_map(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        totals: dict[str, dict[str, Any]] = {}
        for row in rows:
            tick_id = str(row.get("tick_id", "") or "")
            if not tick_id:
                continue
            totals[tick_id] = {
                "request_count": int(row.get("request_count", 0) or 0),
                "estimated_cost_usd": round(
                    float(row.get("estimated_cost_usd", 0) or 0),
                    8,
                ),
            }
        return totals

    def _build_tick_cost_rollup_updates(
        self,
        tick_rows: list[dict[str, Any]],
        *,
        tick_totals: dict[str, dict[str, Any]],
        daily_totals: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        for row in tick_rows:
            tick_id = str(row.get("tick_id", "") or "")
            if not tick_id:
                continue
            usage_date_key = self._normalize_usage_date_key(row.get("started_at"))
            tick_total = tick_totals.get(
                tick_id,
                {"request_count": 0, "estimated_cost_usd": 0.0},
            )
            daily_total = daily_totals.get(
                usage_date_key,
                {"request_count": 0, "estimated_cost_usd": 0.0},
            )
            daily_estimated_cost_usd = round(
                float(daily_total.get("estimated_cost_usd", 0) or 0),
                8,
            )
            updates.append(
                {
                    "tick_id": tick_id,
                    "tick_api_request_count": int(tick_total.get("request_count", 0) or 0),
                    "tick_estimated_cost_usd": round(
                        float(tick_total.get("estimated_cost_usd", 0) or 0),
                        8,
                    ),
                    "daily_api_request_count": int(
                        daily_total.get("request_count", 0) or 0
                    ),
                    "daily_estimated_cost_usd": daily_estimated_cost_usd,
                    "budget_status": self.budget_status(
                        daily_estimated_cost_usd=daily_estimated_cost_usd
                    ),
                }
            )
        return updates

    def _backfill_api_costs_sqlite(self) -> dict[str, Any]:
        repriced_at = datetime.now().astimezone().isoformat()
        with self._connect_sqlite() as connection:
            event_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, source, request_count, input_units, output_units,
                           estimated_cost_usd
                    FROM api_request_events
                    ORDER BY id ASC
                    """
                ).fetchall()
            ]
            event_updates, stats = self._build_repriced_api_event_updates(event_rows)

            if event_updates:
                connection.executemany(
                    """
                    UPDATE api_request_events
                    SET estimated_cost_usd = ?
                    WHERE id = ?
                    """,
                    event_updates,
                )

            connection.execute("DELETE FROM api_daily_usage")
            connection.execute(
                """
                INSERT INTO api_daily_usage (
                    usage_date,
                    source,
                    request_count,
                    success_count,
                    error_count,
                    input_units,
                    output_units,
                    estimated_cost_usd,
                    updated_at
                )
                SELECT usage_date,
                       source,
                       COALESCE(SUM(request_count), 0),
                       COALESCE(SUM(success_count), 0),
                       COALESCE(SUM(error_count), 0),
                       COALESCE(SUM(input_units), 0),
                       COALESCE(SUM(output_units), 0),
                       COALESCE(SUM(estimated_cost_usd), 0),
                       ?
                FROM api_request_events
                GROUP BY usage_date, source
                """,
                (repriced_at,),
            )
            daily_rows_rebuilt = int(
                connection.execute(
                    "SELECT COUNT(*) AS row_count FROM api_daily_usage"
                ).fetchone()["row_count"]
            )

            tick_total_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT tick_id,
                           COALESCE(SUM(request_count), 0) AS request_count,
                           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                    FROM api_request_events
                    GROUP BY tick_id
                    """
                ).fetchall()
            ]
            daily_total_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT usage_date,
                           COALESCE(SUM(request_count), 0) AS request_count,
                           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                    FROM api_daily_usage
                    GROUP BY usage_date
                    """
                ).fetchall()
            ]
            tick_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT tick_id, started_at
                    FROM control_tick_runs
                    ORDER BY started_at ASC
                    """
                ).fetchall()
            ]
            tick_rollup_updates = self._build_tick_cost_rollup_updates(
                tick_rows,
                tick_totals=self._build_tick_total_map(tick_total_rows),
                daily_totals=self._build_daily_total_map(daily_total_rows),
            )
            if tick_rollup_updates:
                connection.executemany(
                    """
                    UPDATE control_tick_runs
                    SET tick_api_request_count = ?,
                        tick_estimated_cost_usd = ?,
                        daily_api_request_count = ?,
                        daily_estimated_cost_usd = ?,
                        budget_status = ?
                    WHERE tick_id = ?
                    """,
                    [
                        (
                            row["tick_api_request_count"],
                            row["tick_estimated_cost_usd"],
                            row["daily_api_request_count"],
                            row["daily_estimated_cost_usd"],
                            row["budget_status"],
                            row["tick_id"],
                        )
                        for row in tick_rollup_updates
                    ],
                )

        daily_total_cost = round(
            sum(
                float(row.get("estimated_cost_usd", 0) or 0)
                for row in daily_total_rows
            ),
            8,
        )
        return {
            "backend": self.backend,
            "repriced_at": repriced_at,
            "events_scanned": stats["events_scanned"],
            "events_cost_changed": stats["events_cost_changed"],
            "zero_cost_events": stats["zero_cost_events"],
            "gemini_events_scanned": stats["gemini_events_scanned"],
            "gemini_events_with_tokens": stats["gemini_events_with_tokens"],
            "gemini_events_nonzero_cost": stats["gemini_events_nonzero_cost"],
            "daily_rows_rebuilt": daily_rows_rebuilt,
            "tick_runs_updated": len(tick_rollup_updates),
            "total_estimated_cost_usd": daily_total_cost,
        }

    def _backfill_api_costs_postgres(self) -> dict[str, Any]:
        repriced_at = datetime.now().astimezone()
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, source, request_count, input_units, output_units,
                           estimated_cost_usd
                    FROM api_request_events
                    ORDER BY id ASC
                    """
                )
                event_rows = [dict(row) for row in cursor.fetchall()]
                event_updates, stats = self._build_repriced_api_event_updates(event_rows)

                if event_updates:
                    cursor.executemany(
                        """
                        UPDATE api_request_events
                        SET estimated_cost_usd = %s
                        WHERE id = %s
                        """,
                        event_updates,
                    )

                cursor.execute("TRUNCATE TABLE api_daily_usage")
                cursor.execute(
                    """
                    INSERT INTO api_daily_usage (
                        usage_date,
                        source,
                        request_count,
                        success_count,
                        error_count,
                        input_units,
                        output_units,
                        estimated_cost_usd,
                        updated_at
                    )
                    SELECT usage_date,
                           source,
                           COALESCE(SUM(request_count), 0),
                           COALESCE(SUM(success_count), 0),
                           COALESCE(SUM(error_count), 0),
                           COALESCE(SUM(input_units), 0),
                           COALESCE(SUM(output_units), 0),
                           COALESCE(SUM(estimated_cost_usd), 0),
                           %s
                    FROM api_request_events
                    GROUP BY usage_date, source
                    """,
                    (repriced_at,),
                )
                cursor.execute("SELECT COUNT(*) AS row_count FROM api_daily_usage")
                daily_rows_rebuilt = int(cursor.fetchone()["row_count"])

                cursor.execute(
                    """
                    SELECT tick_id,
                           COALESCE(SUM(request_count), 0) AS request_count,
                           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                    FROM api_request_events
                    GROUP BY tick_id
                    """
                )
                tick_total_rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT usage_date,
                           COALESCE(SUM(request_count), 0) AS request_count,
                           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                    FROM api_daily_usage
                    GROUP BY usage_date
                    """
                )
                daily_total_rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT tick_id, started_at
                    FROM control_tick_runs
                    ORDER BY started_at ASC
                    """
                )
                tick_rows = [dict(row) for row in cursor.fetchall()]
                tick_rollup_updates = self._build_tick_cost_rollup_updates(
                    tick_rows,
                    tick_totals=self._build_tick_total_map(tick_total_rows),
                    daily_totals=self._build_daily_total_map(daily_total_rows),
                )
                if tick_rollup_updates:
                    cursor.executemany(
                        """
                        UPDATE control_tick_runs
                        SET tick_api_request_count = %s,
                            tick_estimated_cost_usd = %s,
                            daily_api_request_count = %s,
                            daily_estimated_cost_usd = %s,
                            budget_status = %s
                        WHERE tick_id = %s
                        """,
                        [
                            (
                                row["tick_api_request_count"],
                                row["tick_estimated_cost_usd"],
                                row["daily_api_request_count"],
                                row["daily_estimated_cost_usd"],
                                row["budget_status"],
                                row["tick_id"],
                            )
                            for row in tick_rollup_updates
                        ],
                    )

        daily_total_cost = round(
            sum(
                float(row.get("estimated_cost_usd", 0) or 0)
                for row in daily_total_rows
            ),
            8,
        )
        return {
            "backend": self.backend,
            "repriced_at": repriced_at.isoformat(),
            "events_scanned": stats["events_scanned"],
            "events_cost_changed": stats["events_cost_changed"],
            "zero_cost_events": stats["zero_cost_events"],
            "gemini_events_scanned": stats["gemini_events_scanned"],
            "gemini_events_with_tokens": stats["gemini_events_with_tokens"],
            "gemini_events_nonzero_cost": stats["gemini_events_nonzero_cost"],
            "daily_rows_rebuilt": daily_rows_rebuilt,
            "tick_runs_updated": len(tick_rollup_updates),
            "total_estimated_cost_usd": daily_total_cost,
        }

    def _ensure_sqlite_schema(self) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_request_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usage_date TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    tick_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 1,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    input_units INTEGER NOT NULL DEFAULT 0,
                    output_units INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    notes TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_request_events_tick_id
                ON api_request_events (tick_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_request_events_usage_date_source
                ON api_request_events (usage_date, source)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_request_events_tick_usage
                ON api_request_events (tick_id, usage_date, source)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_daily_usage (
                    usage_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    input_units INTEGER NOT NULL DEFAULT 0,
                    output_units INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (usage_date, source)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS control_tick_runs (
                    tick_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    tick_api_request_count INTEGER NOT NULL DEFAULT 0,
                    tick_estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    daily_api_request_count INTEGER NOT NULL DEFAULT 0,
                    daily_estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    budget_status TEXT NOT NULL,
                    operations_backend TEXT NOT NULL,
                    last_error TEXT,
                    step_profiles_json TEXT NOT NULL DEFAULT '[]',
                    state_snapshot_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_control_tick_runs_started_at
                ON control_tick_runs (started_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_router_intents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tick_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'paper',
                    mode TEXT NOT NULL DEFAULT 'paper',
                    lane TEXT NOT NULL,
                    action TEXT NOT NULL,
                    broker_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    strategy_id TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL DEFAULT '',
                    order_id TEXT NOT NULL DEFAULT '',
                    canonical_instrument_id TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '',
                    venue_symbol TEXT NOT NULL DEFAULT '',
                    intended_order_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_router_intents_recorded
                ON execution_router_intents (recorded_at DESC, id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_router_intents_mode_status
                ON execution_router_intents (mode, status, recorded_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_router_intents_tick
                ON execution_router_intents (tick_id, recorded_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_protection_state (
                    session_date TEXT PRIMARY KEY,
                    market_open_at TEXT NOT NULL,
                    baseline_tick_id TEXT NOT NULL,
                    baseline_equity REAL NOT NULL DEFAULT 0,
                    first_checked_at TEXT NOT NULL,
                    last_tick_id TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    latest_equity REAL NOT NULL DEFAULT 0,
                    equity_drawdown_usd REAL NOT NULL DEFAULT 0,
                    max_daily_drawdown_usd REAL NOT NULL DEFAULT 0,
                    system_status TEXT NOT NULL DEFAULT 'active',
                    protection_triggered_at TEXT,
                    stale_orders_reaped_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_protection_state_status
                ON daily_protection_state (session_date, system_status)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_daily_protection_state (
                    session_date TEXT NOT NULL,
                    broker_id TEXT NOT NULL,
                    market_open_at TEXT NOT NULL,
                    baseline_tick_id TEXT NOT NULL,
                    baseline_equity REAL NOT NULL DEFAULT 0,
                    first_checked_at TEXT NOT NULL,
                    last_tick_id TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    latest_equity REAL NOT NULL DEFAULT 0,
                    equity_drawdown_usd REAL NOT NULL DEFAULT 0,
                    max_daily_drawdown_usd REAL NOT NULL DEFAULT 0,
                    system_status TEXT NOT NULL DEFAULT 'active',
                    protection_triggered_at TEXT,
                    stale_orders_reaped_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (session_date, broker_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_broker_daily_protection_state_status
                ON broker_daily_protection_state (broker_id, session_date, system_status)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_threshold_adaptive_state (
                    state_id TEXT PRIMARY KEY,
                    effective_threshold REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_tick_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    advice_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_account_snapshots (
                    tick_id TEXT NOT NULL,
                    broker_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    account_status TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'USD',
                    equity REAL,
                    cash REAL,
                    buying_power REAL,
                    portfolio_value REAL,
                    last_equity REAL,
                    position_market_value REAL,
                    open_position_unrealized_pl REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, broker_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_broker_captured
                ON broker_account_snapshots (broker_id, captured_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_captured
                ON broker_account_snapshots (captured_at DESC, broker_id ASC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_high_water
                ON broker_account_snapshots (broker_id, equity DESC, captured_at ASC)
                WHERE equity IS NOT NULL
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data_latest_bars (
                    tick_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bar_timestamp TEXT,
                    open_price REAL,
                    high_price REAL,
                    low_price REAL,
                    close_price REAL,
                    volume INTEGER,
                    trade_count INTEGER,
                    vwap REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, source, symbol)
                )
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="market_data_latest_bars",
                columns={
                    "quote_currency": "TEXT NOT NULL DEFAULT 'USD'",
                    "asset_class": "TEXT NOT NULL DEFAULT ''",
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                    "usd_to_gbp_rate": "REAL",
                    "open_price_gbp": "REAL",
                    "high_price_gbp": "REAL",
                    "low_price_gbp": "REAL",
                    "close_price_gbp": "REAL",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_symbol_timestamp
                ON market_data_latest_bars (symbol, bar_timestamp)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_window
                ON market_data_latest_bars (source, symbol, captured_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_instrument
                ON market_data_latest_bars (canonical_instrument_id, source, captured_at)
                WHERE canonical_instrument_id <> ''
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data_historical_bars (
                    batch_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    canonical_instrument_id TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '',
                    venue_symbol TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    bar_timestamp TEXT NOT NULL,
                    quote_currency TEXT NOT NULL DEFAULT 'USD',
                    usd_to_gbp_rate REAL,
                    open_price REAL,
                    high_price REAL,
                    low_price REAL,
                    close_price REAL,
                    open_price_gbp REAL,
                    high_price_gbp REAL,
                    low_price_gbp REAL,
                    close_price_gbp REAL,
                    volume INTEGER,
                    trade_count INTEGER,
                    vwap REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (source, symbol, timeframe, bar_timestamp)
                )
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="market_data_historical_bars",
                columns={
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_historical_bars_symbol_timeframe_timestamp
                ON market_data_historical_bars (symbol, timeframe, bar_timestamp)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_historical_bars_instrument_timeframe
                ON market_data_historical_bars (canonical_instrument_id, timeframe, bar_timestamp)
                WHERE canonical_instrument_id <> ''
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fx_reference_rates (
                    source TEXT NOT NULL,
                    provider_date TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    usd_per_eur REAL NOT NULL,
                    gbp_per_eur REAL NOT NULL,
                    usd_to_gbp REAL NOT NULL,
                    gbp_to_usd REAL NOT NULL,
                    mode TEXT NOT NULL,
                    raw_payload TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source, provider_date)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fx_reference_rates_fetched_at
                ON fx_reference_rates (fetched_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fx_reference_rates_source_fetched
                ON fx_reference_rates (source, fetched_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_candidates (
                    tick_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 0,
                    discovery_score REAL NOT NULL DEFAULT 0,
                    close_price REAL,
                    close_price_gbp REAL,
                    previous_close_price REAL,
                    movement_pct REAL,
                    volume INTEGER,
                    trade_count INTEGER,
                    bar_timestamp TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, source, symbol)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gemini_candidate_analyses (
                    tick_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action_bias TEXT NOT NULL,
                    opportunity_score REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    thesis TEXT NOT NULL DEFAULT '',
                    risks_json TEXT NOT NULL DEFAULT '[]',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, symbol)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_candidate_signals (
                    tick_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_family TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'long',
                    signal_rank INTEGER NOT NULL DEFAULT 0,
                    signal_score REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    entry_price REAL NOT NULL,
                    entry_price_gbp REAL,
                    stop_loss_price REAL NOT NULL,
                    stop_loss_price_gbp REAL,
                    target_price REAL NOT NULL,
                    target_price_gbp REAL,
                    risk_pct REAL NOT NULL DEFAULT 0,
                    target_return_pct REAL NOT NULL DEFAULT 0,
                    holding_window_code TEXT NOT NULL,
                    holding_window_minutes INTEGER NOT NULL DEFAULT 0,
                    movement_pct REAL,
                    discovery_score REAL NOT NULL DEFAULT 0,
                    rationale TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, strategy_id, source, symbol)
                )
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="strategy_candidate_signals",
                columns={
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_tick_id_score
                ON strategy_candidate_signals (tick_id, signal_score)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_tick_strategy
                ON strategy_candidate_signals (tick_id, strategy_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_instrument
                ON strategy_candidate_signals (canonical_instrument_id, strategy_id, tick_id)
                WHERE canonical_instrument_id <> ''
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trade_orders (
                    order_id TEXT PRIMARY KEY,
                    tick_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    submitted_at TEXT,
                    updated_at TEXT,
                    environment TEXT NOT NULL DEFAULT 'paper',
                    mode TEXT NOT NULL DEFAULT 'paper',
                    source_environment TEXT NOT NULL DEFAULT 'shadow',
                    broker_id TEXT NOT NULL DEFAULT 'alpaca_paper',
                    data_provider TEXT NOT NULL DEFAULT 'alpaca',
                    execution_provider TEXT NOT NULL DEFAULT 'alpaca_paper',
                    client_order_id TEXT NOT NULL DEFAULT '',
                    proposal_id TEXT NOT NULL DEFAULT '',
                    strategy_id TEXT NOT NULL DEFAULT '',
                    strategy_family TEXT NOT NULL DEFAULT '',
                    profile_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL DEFAULT '',
                    side TEXT NOT NULL DEFAULT '',
                    order_type TEXT NOT NULL DEFAULT '',
                    time_in_force TEXT NOT NULL DEFAULT '',
                    order_class TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    is_open INTEGER NOT NULL DEFAULT 0,
                    qty REAL,
                    filled_qty REAL,
                    notional_usd REAL,
                    filled_avg_price REAL,
                    limit_price REAL,
                    stop_price REAL,
                    take_profit_price REAL,
                    stop_loss_price REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="paper_trade_orders",
                columns={
                    "environment": "TEXT NOT NULL DEFAULT 'paper'",
                    "mode": "TEXT NOT NULL DEFAULT 'paper'",
                    "source_environment": "TEXT NOT NULL DEFAULT 'shadow'",
                    "broker_id": "TEXT NOT NULL DEFAULT 'alpaca_paper'",
                    "data_provider": "TEXT NOT NULL DEFAULT 'alpaca'",
                    "execution_provider": "TEXT NOT NULL DEFAULT 'alpaca_paper'",
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_captured_at
                ON paper_trade_orders (captured_at, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_symbol
                ON paper_trade_orders (symbol, submitted_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_activity
                ON paper_trade_orders (COALESCE(submitted_at, captured_at), order_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_broker_activity
                ON paper_trade_orders (broker_id, COALESCE(submitted_at, captured_at), order_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_env_broker_activity
                ON paper_trade_orders (environment, mode, broker_id, COALESCE(submitted_at, captured_at))
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_instrument_activity
                ON paper_trade_orders (canonical_instrument_id, venue, COALESCE(submitted_at, captured_at))
                WHERE canonical_instrument_id <> ''
                """
            )
            self._backfill_sqlite_instrument_metadata(
                connection,
                table_name="paper_trade_orders",
                timestamp_column="COALESCE(submitted_at, captured_at)",
                has_broker=True,
            )
            connection.execute(
                """
                UPDATE paper_trade_orders
                SET environment = 'live',
                    mode = 'live',
                    source_environment = CASE
                        WHEN proposal_id <> '' THEN 'paper'
                        ELSE 'live'
                    END,
                    execution_provider = broker_id
                WHERE broker_id LIKE '%_live'
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_strategy_side_status
                ON paper_trade_orders (strategy_id, side, status, submitted_at)
                WHERE proposal_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_proposal_side_submitted
                ON paper_trade_orders (proposal_id, side, submitted_at)
                WHERE proposal_id <> ''
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_trade_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    tick_id TEXT NOT NULL,
                    proposed_at TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'paper',
                    mode TEXT NOT NULL DEFAULT 'paper',
                    source_environment TEXT NOT NULL DEFAULT 'shadow',
                    data_provider TEXT NOT NULL DEFAULT 'alpaca',
                    execution_provider TEXT NOT NULL DEFAULT 'shadow',
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'long',
                    status TEXT NOT NULL DEFAULT 'active',
                    action_bias TEXT NOT NULL DEFAULT 'watch',
                    opportunity_score REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    discovery_score REAL NOT NULL DEFAULT 0,
                    entry_price REAL NOT NULL,
                    entry_price_gbp REAL,
                    stop_loss_price REAL NOT NULL,
                    stop_loss_price_gbp REAL,
                    target_price REAL NOT NULL,
                    target_price_gbp REAL,
                    risk_pct REAL NOT NULL DEFAULT 0,
                    target_return_pct REAL NOT NULL DEFAULT 0,
                    holding_window_code TEXT NOT NULL,
                    holding_window_minutes INTEGER NOT NULL DEFAULT 0,
                    thesis TEXT NOT NULL DEFAULT '',
                    risks_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="shadow_trade_proposals",
                columns={
                    "strategy_id": "TEXT NOT NULL DEFAULT ''",
                    "strategy_family": "TEXT NOT NULL DEFAULT ''",
                    "profile_id": "TEXT NOT NULL DEFAULT ''",
                    "signal_score": "REAL NOT NULL DEFAULT 0",
                    "signal_confidence": "REAL NOT NULL DEFAULT 0",
                    "rationale": "TEXT NOT NULL DEFAULT ''",
                    "environment": "TEXT NOT NULL DEFAULT 'paper'",
                    "mode": "TEXT NOT NULL DEFAULT 'paper'",
                    "source_environment": "TEXT NOT NULL DEFAULT 'shadow'",
                    "data_provider": "TEXT NOT NULL DEFAULT 'alpaca'",
                    "execution_provider": "TEXT NOT NULL DEFAULT 'shadow'",
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_source_symbol_proposed_at
                ON shadow_trade_proposals (source, symbol, proposed_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_proposed_at
                ON shadow_trade_proposals (proposed_at DESC, proposal_id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_strategy_training
                ON shadow_trade_proposals (strategy_id, proposed_at)
                WHERE strategy_id <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_env_source
                ON shadow_trade_proposals (environment, source_environment, mode, proposed_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_instrument
                ON shadow_trade_proposals (canonical_instrument_id, venue, proposed_at)
                WHERE canonical_instrument_id <> ''
                """
            )
            self._backfill_sqlite_instrument_metadata(
                connection,
                table_name="shadow_trade_proposals",
                timestamp_column="proposed_at",
                has_broker=False,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_trade_outcomes (
                    proposal_id TEXT NOT NULL,
                    checkpoint_code TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'paper',
                    mode TEXT NOT NULL DEFAULT 'paper',
                    source_environment TEXT NOT NULL DEFAULT 'shadow',
                    data_provider TEXT NOT NULL DEFAULT 'alpaca',
                    execution_provider TEXT NOT NULL DEFAULT 'shadow',
                    checkpoint_minutes INTEGER NOT NULL DEFAULT 0,
                    due_at TEXT NOT NULL,
                    evaluated_at TEXT,
                    outcome_status TEXT NOT NULL DEFAULT 'pending',
                    exit_price REAL,
                    exit_price_gbp REAL,
                    realized_return_pct REAL,
                    max_favorable_excursion_pct REAL,
                    max_adverse_excursion_pct REAL,
                    fitness_score REAL,
                    bars_observed INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (proposal_id, checkpoint_code)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_due_pending
                ON shadow_trade_outcomes (due_at, evaluated_at, outcome_status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_evaluated_proposal
                ON shadow_trade_outcomes (proposal_id, checkpoint_minutes)
                WHERE evaluated_at IS NOT NULL
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="shadow_trade_outcomes",
                columns={
                    "environment": "TEXT NOT NULL DEFAULT 'paper'",
                    "mode": "TEXT NOT NULL DEFAULT 'paper'",
                    "source_environment": "TEXT NOT NULL DEFAULT 'shadow'",
                    "data_provider": "TEXT NOT NULL DEFAULT 'alpaca'",
                    "execution_provider": "TEXT NOT NULL DEFAULT 'shadow'",
                    "canonical_instrument_id": "TEXT NOT NULL DEFAULT ''",
                    "venue": "TEXT NOT NULL DEFAULT ''",
                    "venue_symbol": "TEXT NOT NULL DEFAULT ''",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_instrument_due
                ON shadow_trade_outcomes (canonical_instrument_id, venue, due_at)
                WHERE canonical_instrument_id <> ''
                """
            )
            self._backfill_sqlite_shadow_outcome_instrument_metadata(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_fitness_snapshots (
                    tick_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'paper',
                    mode TEXT NOT NULL DEFAULT 'paper',
                    source_environment TEXT NOT NULL DEFAULT 'shadow',
                    broker_id TEXT NOT NULL DEFAULT 'alpaca_paper',
                    data_provider TEXT NOT NULL DEFAULT 'alpaca',
                    execution_provider TEXT NOT NULL DEFAULT 'shadow',
                    strategy_id TEXT NOT NULL,
                    strategy_family TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    checkpoint_code TEXT NOT NULL,
                    lookback_days INTEGER NOT NULL DEFAULT 0,
                    fitness_rank INTEGER NOT NULL DEFAULT 0,
                    evaluated_proposals INTEGER NOT NULL DEFAULT 0,
                    checkpoints_evaluated INTEGER NOT NULL DEFAULT 0,
                    win_count INTEGER NOT NULL DEFAULT 0,
                    loss_count INTEGER NOT NULL DEFAULT 0,
                    target_hit_count INTEGER NOT NULL DEFAULT 0,
                    stop_hit_count INTEGER NOT NULL DEFAULT 0,
                    time_exit_count INTEGER NOT NULL DEFAULT 0,
                    ambiguous_count INTEGER NOT NULL DEFAULT 0,
                    win_rate REAL NOT NULL DEFAULT 0,
                    loss_rate REAL NOT NULL DEFAULT 0,
                    target_hit_rate REAL NOT NULL DEFAULT 0,
                    stop_hit_rate REAL NOT NULL DEFAULT 0,
                    time_exit_rate REAL NOT NULL DEFAULT 0,
                    ambiguous_rate REAL NOT NULL DEFAULT 0,
                    avg_fitness_score REAL NOT NULL DEFAULT 0,
                    avg_realized_return_pct REAL NOT NULL DEFAULT 0,
                    avg_max_favorable_excursion_pct REAL NOT NULL DEFAULT 0,
                    avg_max_adverse_excursion_pct REAL NOT NULL DEFAULT 0,
                    avg_signal_score REAL NOT NULL DEFAULT 0,
                    avg_signal_confidence REAL NOT NULL DEFAULT 0,
                    avg_discovery_score REAL NOT NULL DEFAULT 0,
                    sample_weight REAL NOT NULL DEFAULT 0,
                    composite_fitness_score REAL NOT NULL DEFAULT 0,
                    first_proposed_at TEXT,
                    last_evaluated_at TEXT,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tick_id, strategy_id, asset_class, checkpoint_code)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_fitness_snapshots_rank
                ON strategy_fitness_snapshots (captured_at, fitness_rank, composite_fitness_score)
                """
            )
            self._ensure_sqlite_columns(
                connection,
                table_name="strategy_fitness_snapshots",
                columns={
                    "environment": "TEXT NOT NULL DEFAULT 'paper'",
                    "mode": "TEXT NOT NULL DEFAULT 'paper'",
                    "source_environment": "TEXT NOT NULL DEFAULT 'shadow'",
                    "broker_id": "TEXT NOT NULL DEFAULT 'alpaca_paper'",
                    "data_provider": "TEXT NOT NULL DEFAULT 'alpaca'",
                    "execution_provider": "TEXT NOT NULL DEFAULT 'shadow'",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_fitness_snapshots_env_source
                ON strategy_fitness_snapshots (environment, source_environment, mode, captured_at)
                """
            )

    def _ensure_postgres_schema(self) -> None:
        with self._connect_postgres(apply_schema=False) as connection:
            with connection.cursor() as cursor:
                self._ensure_postgres_namespace(cursor)
                # Status/report commands can start together; serialize bootstrap DDL
                # so concurrent CREATE INDEX IF NOT EXISTS calls do not race.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('centaur_usage_schema'))"
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_request_events (
                        id BIGSERIAL PRIMARY KEY,
                        usage_date DATE NOT NULL,
                        requested_at TIMESTAMPTZ NOT NULL,
                        tick_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 1,
                        success_count INTEGER NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        input_units INTEGER NOT NULL DEFAULT 0,
                        output_units INTEGER NOT NULL DEFAULT 0,
                        estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        currency TEXT NOT NULL DEFAULT 'USD',
                        notes TEXT,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_request_events_tick_id
                    ON api_request_events (tick_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_request_events_usage_date_source
                    ON api_request_events (usage_date, source)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_request_events_tick_usage
                    ON api_request_events (tick_id, usage_date, source)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_daily_usage (
                        usage_date DATE NOT NULL,
                        source TEXT NOT NULL,
                        request_count INTEGER NOT NULL DEFAULT 0,
                        success_count INTEGER NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        input_units INTEGER NOT NULL DEFAULT 0,
                        output_units INTEGER NOT NULL DEFAULT 0,
                        estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (usage_date, source)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_tick_runs (
                        tick_id TEXT PRIMARY KEY,
                        started_at TIMESTAMPTZ NOT NULL,
                        ended_at TIMESTAMPTZ NOT NULL,
                        status TEXT NOT NULL,
                        duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
                        step_count INTEGER NOT NULL DEFAULT 0,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        tick_api_request_count INTEGER NOT NULL DEFAULT 0,
                        tick_estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        daily_api_request_count INTEGER NOT NULL DEFAULT 0,
                        daily_estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        budget_status TEXT NOT NULL,
                        operations_backend TEXT NOT NULL,
                        last_error TEXT,
                        step_profiles_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        state_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_control_tick_runs_started_at
                    ON control_tick_runs (started_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_router_intents (
                        id BIGSERIAL PRIMARY KEY,
                        tick_id TEXT NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'paper',
                        mode TEXT NOT NULL DEFAULT 'paper',
                        lane TEXT NOT NULL,
                        action TEXT NOT NULL,
                        broker_id TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT '',
                        strategy_id TEXT NOT NULL DEFAULT '',
                        symbol TEXT NOT NULL DEFAULT '',
                        order_id TEXT NOT NULL DEFAULT '',
                        canonical_instrument_id TEXT NOT NULL DEFAULT '',
                        venue TEXT NOT NULL DEFAULT '',
                        venue_symbol TEXT NOT NULL DEFAULT '',
                        intended_order_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_router_intents_recorded
                    ON execution_router_intents (recorded_at DESC, id DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_router_intents_mode_status
                    ON execution_router_intents (mode, status, recorded_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_router_intents_tick
                    ON execution_router_intents (tick_id, recorded_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_protection_state (
                        session_date DATE PRIMARY KEY,
                        market_open_at TIMESTAMPTZ NOT NULL,
                        baseline_tick_id TEXT NOT NULL,
                        baseline_equity DOUBLE PRECISION NOT NULL DEFAULT 0,
                        first_checked_at TIMESTAMPTZ NOT NULL,
                        last_tick_id TEXT NOT NULL,
                        last_checked_at TIMESTAMPTZ NOT NULL,
                        latest_equity DOUBLE PRECISION NOT NULL DEFAULT 0,
                        equity_drawdown_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        max_daily_drawdown_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        system_status TEXT NOT NULL DEFAULT 'active',
                        protection_triggered_at TIMESTAMPTZ,
                        stale_orders_reaped_count INTEGER NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_daily_protection_state_status
                    ON daily_protection_state (session_date, system_status)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broker_daily_protection_state (
                        session_date DATE NOT NULL,
                        broker_id TEXT NOT NULL,
                        market_open_at TIMESTAMPTZ NOT NULL,
                        baseline_tick_id TEXT NOT NULL,
                        baseline_equity DOUBLE PRECISION NOT NULL DEFAULT 0,
                        first_checked_at TIMESTAMPTZ NOT NULL,
                        last_tick_id TEXT NOT NULL,
                        last_checked_at TIMESTAMPTZ NOT NULL,
                        latest_equity DOUBLE PRECISION NOT NULL DEFAULT 0,
                        equity_drawdown_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        max_daily_drawdown_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        system_status TEXT NOT NULL DEFAULT 'active',
                        protection_triggered_at TIMESTAMPTZ,
                        stale_orders_reaped_count INTEGER NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (session_date, broker_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_broker_daily_protection_state_status
                    ON broker_daily_protection_state (broker_id, session_date, system_status)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_threshold_adaptive_state (
                        state_id TEXT PRIMARY KEY,
                        effective_threshold DOUBLE PRECISION NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        source_tick_id TEXT NOT NULL DEFAULT '',
                        reason TEXT NOT NULL DEFAULT '',
                        advice_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broker_account_snapshots (
                        tick_id TEXT NOT NULL,
                        broker_id TEXT NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        account_status TEXT NOT NULL DEFAULT '',
                        currency TEXT NOT NULL DEFAULT 'USD',
                        equity DOUBLE PRECISION,
                        cash DOUBLE PRECISION,
                        buying_power DOUBLE PRECISION,
                        portfolio_value DOUBLE PRECISION,
                        last_equity DOUBLE PRECISION,
                        position_market_value DOUBLE PRECISION,
                        open_position_unrealized_pl DOUBLE PRECISION,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, broker_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_broker_captured
                    ON broker_account_snapshots (broker_id, captured_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_captured
                    ON broker_account_snapshots (captured_at DESC, broker_id ASC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_high_water
                    ON broker_account_snapshots (broker_id, equity DESC, captured_at ASC)
                    WHERE equity IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS market_data_latest_bars (
                        tick_id TEXT NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        source TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        bar_timestamp TIMESTAMPTZ,
                        open_price DOUBLE PRECISION,
                        high_price DOUBLE PRECISION,
                        low_price DOUBLE PRECISION,
                        close_price DOUBLE PRECISION,
                        volume BIGINT,
                        trade_count BIGINT,
                        vwap DOUBLE PRECISION,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, source, symbol)
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS quote_currency TEXT NOT NULL DEFAULT 'USD'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS asset_class TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS usd_to_gbp_rate DOUBLE PRECISION
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS open_price_gbp DOUBLE PRECISION
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS high_price_gbp DOUBLE PRECISION
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS low_price_gbp DOUBLE PRECISION
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_latest_bars
                    ADD COLUMN IF NOT EXISTS close_price_gbp DOUBLE PRECISION
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_symbol_timestamp
                    ON market_data_latest_bars (symbol, bar_timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_window
                    ON market_data_latest_bars (source, symbol, captured_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_market_data_latest_bars_instrument
                    ON market_data_latest_bars (canonical_instrument_id, source, captured_at DESC)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS market_data_historical_bars (
                        batch_id TEXT NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        source TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        canonical_instrument_id TEXT NOT NULL DEFAULT '',
                        venue TEXT NOT NULL DEFAULT '',
                        venue_symbol TEXT NOT NULL DEFAULT '',
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        bar_timestamp TIMESTAMPTZ NOT NULL,
                        quote_currency TEXT NOT NULL DEFAULT 'USD',
                        usd_to_gbp_rate DOUBLE PRECISION,
                        open_price DOUBLE PRECISION,
                        high_price DOUBLE PRECISION,
                        low_price DOUBLE PRECISION,
                        close_price DOUBLE PRECISION,
                        open_price_gbp DOUBLE PRECISION,
                        high_price_gbp DOUBLE PRECISION,
                        low_price_gbp DOUBLE PRECISION,
                        close_price_gbp DOUBLE PRECISION,
                        volume BIGINT,
                        trade_count BIGINT,
                        vwap DOUBLE PRECISION,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (source, symbol, timeframe, bar_timestamp)
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_historical_bars
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_historical_bars
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE market_data_historical_bars
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_market_data_historical_bars_symbol_timeframe_timestamp
                    ON market_data_historical_bars (symbol, timeframe, bar_timestamp)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_market_data_historical_bars_instrument_timeframe
                    ON market_data_historical_bars (canonical_instrument_id, timeframe, bar_timestamp DESC)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fx_reference_rates (
                        source TEXT NOT NULL,
                        provider_date DATE NOT NULL,
                        fetched_at TIMESTAMPTZ NOT NULL,
                        base_currency TEXT NOT NULL,
                        usd_per_eur DOUBLE PRECISION NOT NULL,
                        gbp_per_eur DOUBLE PRECISION NOT NULL,
                        usd_to_gbp DOUBLE PRECISION NOT NULL,
                        gbp_to_usd DOUBLE PRECISION NOT NULL,
                        mode TEXT NOT NULL,
                        raw_payload TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (source, provider_date)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_fx_reference_rates_fetched_at
                    ON fx_reference_rates (fetched_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_fx_reference_rates_source_fetched
                    ON fx_reference_rates (source, fetched_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS discovery_candidates (
                        tick_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        rank INTEGER NOT NULL,
                        selected BOOLEAN NOT NULL DEFAULT FALSE,
                        discovery_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        close_price DOUBLE PRECISION,
                        close_price_gbp DOUBLE PRECISION,
                        previous_close_price DOUBLE PRECISION,
                        movement_pct DOUBLE PRECISION,
                        volume BIGINT,
                        trade_count BIGINT,
                        bar_timestamp TIMESTAMPTZ,
                        note TEXT NOT NULL DEFAULT '',
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, source, symbol)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gemini_candidate_analyses (
                        tick_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        action_bias TEXT NOT NULL,
                        opportunity_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
                        thesis TEXT NOT NULL DEFAULT '',
                        risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, symbol)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_candidate_signals (
                        tick_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL,
                        strategy_family TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        direction TEXT NOT NULL DEFAULT 'long',
                        signal_rank INTEGER NOT NULL DEFAULT 0,
                        signal_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
                        entry_price DOUBLE PRECISION NOT NULL,
                        entry_price_gbp DOUBLE PRECISION,
                        stop_loss_price DOUBLE PRECISION NOT NULL,
                        stop_loss_price_gbp DOUBLE PRECISION,
                        target_price DOUBLE PRECISION NOT NULL,
                        target_price_gbp DOUBLE PRECISION,
                        risk_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        target_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        holding_window_code TEXT NOT NULL,
                        holding_window_minutes INTEGER NOT NULL DEFAULT 0,
                        movement_pct DOUBLE PRECISION,
                        discovery_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        rationale TEXT NOT NULL DEFAULT '',
                        note TEXT NOT NULL DEFAULT '',
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, strategy_id, source, symbol)
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_candidate_signals
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_candidate_signals
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_candidate_signals
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_tick_id_score
                    ON strategy_candidate_signals (tick_id, signal_score DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_tick_strategy
                    ON strategy_candidate_signals (tick_id, strategy_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_strategy_candidate_signals_instrument
                    ON strategy_candidate_signals (canonical_instrument_id, strategy_id, tick_id)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trade_orders (
                        order_id TEXT PRIMARY KEY,
                        tick_id TEXT NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        submitted_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ,
                        environment TEXT NOT NULL DEFAULT 'paper',
                        mode TEXT NOT NULL DEFAULT 'paper',
                        source_environment TEXT NOT NULL DEFAULT 'shadow',
                        broker_id TEXT NOT NULL DEFAULT 'alpaca_paper',
                        data_provider TEXT NOT NULL DEFAULT 'alpaca',
                        execution_provider TEXT NOT NULL DEFAULT 'alpaca_paper',
                        client_order_id TEXT NOT NULL DEFAULT '',
                        proposal_id TEXT NOT NULL DEFAULT '',
                        strategy_id TEXT NOT NULL DEFAULT '',
                        strategy_family TEXT NOT NULL DEFAULT '',
                        profile_id TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT '',
                        symbol TEXT NOT NULL,
                        asset_class TEXT NOT NULL DEFAULT '',
                        side TEXT NOT NULL DEFAULT '',
                        order_type TEXT NOT NULL DEFAULT '',
                        time_in_force TEXT NOT NULL DEFAULT '',
                        order_class TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT '',
                        is_open BOOLEAN NOT NULL DEFAULT FALSE,
                        qty DOUBLE PRECISION,
                        filled_qty DOUBLE PRECISION,
                        notional_usd DOUBLE PRECISION,
                        filled_avg_price DOUBLE PRECISION,
                        limit_price DOUBLE PRECISION,
                        stop_price DOUBLE PRECISION,
                        take_profit_price DOUBLE PRECISION,
                        stop_loss_price DOUBLE PRECISION,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS source_environment TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS broker_id TEXT NOT NULL DEFAULT 'alpaca_paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS data_provider TEXT NOT NULL DEFAULT 'alpaca'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS execution_provider TEXT NOT NULL DEFAULT 'alpaca_paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE paper_trade_orders
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_captured_at
                    ON paper_trade_orders (captured_at DESC, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_symbol
                    ON paper_trade_orders (symbol, submitted_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_activity
                    ON paper_trade_orders ((COALESCE(submitted_at, captured_at)), order_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_broker_activity
                    ON paper_trade_orders (broker_id, (COALESCE(submitted_at, captured_at)), order_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_env_broker_activity
                    ON paper_trade_orders (environment, mode, broker_id, (COALESCE(submitted_at, captured_at)) DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_instrument_activity
                    ON paper_trade_orders (canonical_instrument_id, venue, (COALESCE(submitted_at, captured_at)) DESC)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                self._backfill_postgres_instrument_metadata(
                    cursor,
                    table_name="paper_trade_orders",
                    has_broker=True,
                )
                cursor.execute(
                    """
                    UPDATE paper_trade_orders
                    SET environment = 'live',
                        mode = 'live',
                        source_environment = CASE
                            WHEN proposal_id <> '' THEN 'paper'
                            ELSE 'live'
                        END,
                        execution_provider = broker_id
                    WHERE broker_id LIKE '%_live'
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_strategy_side_status
                    ON paper_trade_orders (strategy_id, side, status, submitted_at DESC)
                    WHERE proposal_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_paper_trade_orders_proposal_side_submitted
                    ON paper_trade_orders (proposal_id, side, submitted_at DESC)
                    WHERE proposal_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shadow_trade_proposals (
                        proposal_id TEXT PRIMARY KEY,
                        tick_id TEXT NOT NULL,
                        proposed_at TIMESTAMPTZ NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'paper',
                        mode TEXT NOT NULL DEFAULT 'paper',
                        source_environment TEXT NOT NULL DEFAULT 'shadow',
                        data_provider TEXT NOT NULL DEFAULT 'alpaca',
                        execution_provider TEXT NOT NULL DEFAULT 'shadow',
                        source TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        direction TEXT NOT NULL DEFAULT 'long',
                        status TEXT NOT NULL DEFAULT 'active',
                        action_bias TEXT NOT NULL DEFAULT 'watch',
                        opportunity_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
                        discovery_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        entry_price DOUBLE PRECISION NOT NULL,
                        entry_price_gbp DOUBLE PRECISION,
                        stop_loss_price DOUBLE PRECISION NOT NULL,
                        stop_loss_price_gbp DOUBLE PRECISION,
                        target_price DOUBLE PRECISION NOT NULL,
                        target_price_gbp DOUBLE PRECISION,
                        risk_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        target_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        holding_window_code TEXT NOT NULL,
                        holding_window_minutes INTEGER NOT NULL DEFAULT 0,
                        thesis TEXT NOT NULL DEFAULT '',
                        risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        note TEXT NOT NULL DEFAULT '',
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS source_environment TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS data_provider TEXT NOT NULL DEFAULT 'alpaca'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS execution_provider TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS strategy_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS strategy_family TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS profile_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS signal_score DOUBLE PRECISION NOT NULL DEFAULT 0
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS signal_confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_proposals
                    ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_source_symbol_proposed_at
                    ON shadow_trade_proposals (source, symbol, proposed_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_proposed_at
                    ON shadow_trade_proposals (proposed_at DESC, proposal_id DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_strategy_training
                    ON shadow_trade_proposals (strategy_id, proposed_at)
                    WHERE strategy_id <> ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_env_source
                    ON shadow_trade_proposals (environment, source_environment, mode, proposed_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_proposals_instrument
                    ON shadow_trade_proposals (canonical_instrument_id, venue, proposed_at DESC)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                self._backfill_postgres_instrument_metadata(
                    cursor,
                    table_name="shadow_trade_proposals",
                    has_broker=False,
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shadow_trade_outcomes (
                        proposal_id TEXT NOT NULL,
                        checkpoint_code TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'paper',
                        mode TEXT NOT NULL DEFAULT 'paper',
                        source_environment TEXT NOT NULL DEFAULT 'shadow',
                        data_provider TEXT NOT NULL DEFAULT 'alpaca',
                        execution_provider TEXT NOT NULL DEFAULT 'shadow',
                        checkpoint_minutes INTEGER NOT NULL DEFAULT 0,
                        due_at TIMESTAMPTZ NOT NULL,
                        evaluated_at TIMESTAMPTZ,
                        outcome_status TEXT NOT NULL DEFAULT 'pending',
                        exit_price DOUBLE PRECISION,
                        exit_price_gbp DOUBLE PRECISION,
                        realized_return_pct DOUBLE PRECISION,
                        max_favorable_excursion_pct DOUBLE PRECISION,
                        max_adverse_excursion_pct DOUBLE PRECISION,
                        fitness_score DOUBLE PRECISION,
                        bars_observed INTEGER NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT '',
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (proposal_id, checkpoint_code)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_due_pending
                    ON shadow_trade_outcomes (due_at, evaluated_at, outcome_status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_evaluated_proposal
                    ON shadow_trade_outcomes (proposal_id, checkpoint_minutes)
                    WHERE evaluated_at IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS source_environment TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS data_provider TEXT NOT NULL DEFAULT 'alpaca'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS execution_provider TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS canonical_instrument_id TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE shadow_trade_outcomes
                    ADD COLUMN IF NOT EXISTS venue_symbol TEXT NOT NULL DEFAULT ''
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_shadow_trade_outcomes_instrument_due
                    ON shadow_trade_outcomes (canonical_instrument_id, venue, due_at)
                    WHERE canonical_instrument_id <> ''
                    """
                )
                self._backfill_postgres_shadow_outcome_instrument_metadata(cursor)
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS strategy_fitness_snapshots (
                        tick_id TEXT NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'paper',
                        mode TEXT NOT NULL DEFAULT 'paper',
                        source_environment TEXT NOT NULL DEFAULT 'shadow',
                        broker_id TEXT NOT NULL DEFAULT 'alpaca_paper',
                        data_provider TEXT NOT NULL DEFAULT 'alpaca',
                        execution_provider TEXT NOT NULL DEFAULT 'shadow',
                        strategy_id TEXT NOT NULL,
                        strategy_family TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        checkpoint_code TEXT NOT NULL,
                        lookback_days INTEGER NOT NULL DEFAULT 0,
                        fitness_rank INTEGER NOT NULL DEFAULT 0,
                        evaluated_proposals INTEGER NOT NULL DEFAULT 0,
                        checkpoints_evaluated INTEGER NOT NULL DEFAULT 0,
                        win_count INTEGER NOT NULL DEFAULT 0,
                        loss_count INTEGER NOT NULL DEFAULT 0,
                        target_hit_count INTEGER NOT NULL DEFAULT 0,
                        stop_hit_count INTEGER NOT NULL DEFAULT 0,
                        time_exit_count INTEGER NOT NULL DEFAULT 0,
                        ambiguous_count INTEGER NOT NULL DEFAULT 0,
                        win_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        loss_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        target_hit_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        stop_hit_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        time_exit_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        ambiguous_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_fitness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_realized_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_max_favorable_excursion_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_max_adverse_excursion_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_signal_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_signal_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
                        avg_discovery_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        sample_weight DOUBLE PRECISION NOT NULL DEFAULT 0,
                        composite_fitness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                        first_proposed_at TIMESTAMPTZ,
                        last_evaluated_at TIMESTAMPTZ,
                        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        PRIMARY KEY (tick_id, strategy_id, asset_class, checkpoint_code)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_strategy_fitness_snapshots_rank
                    ON strategy_fitness_snapshots (captured_at DESC, fitness_rank, composite_fitness_score DESC)
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS source_environment TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS broker_id TEXT NOT NULL DEFAULT 'alpaca_paper'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS data_provider TEXT NOT NULL DEFAULT 'alpaca'
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE strategy_fitness_snapshots
                    ADD COLUMN IF NOT EXISTS execution_provider TEXT NOT NULL DEFAULT 'shadow'
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_strategy_fitness_snapshots_env_source
                    ON strategy_fitness_snapshots (environment, source_environment, mode, captured_at DESC)
                    """
                )

    def _record_api_call_sqlite(self, payload: dict[str, Any]) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO api_request_events (
                    usage_date,
                    requested_at,
                    tick_id,
                    source,
                    endpoint,
                    request_count,
                    success_count,
                    error_count,
                    input_units,
                    output_units,
                    estimated_cost_usd,
                    currency,
                    notes,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?)
                """,
                (
                    payload["usage_date"],
                    payload["requested_at"],
                    payload["tick_id"],
                    payload["source"],
                    payload["endpoint"],
                    payload["request_count"],
                    payload["success_count"],
                    payload["error_count"],
                    payload["input_units"],
                    payload["output_units"],
                    payload["estimated_cost_usd"],
                    payload["notes"],
                    payload["metadata_json"],
                ),
            )
            connection.execute(
                """
                INSERT INTO api_daily_usage (
                    usage_date,
                    source,
                    request_count,
                    success_count,
                    error_count,
                    input_units,
                    output_units,
                    estimated_cost_usd,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, source) DO UPDATE SET
                    request_count = api_daily_usage.request_count + excluded.request_count,
                    success_count = api_daily_usage.success_count + excluded.success_count,
                    error_count = api_daily_usage.error_count + excluded.error_count,
                    input_units = api_daily_usage.input_units + excluded.input_units,
                    output_units = api_daily_usage.output_units + excluded.output_units,
                    estimated_cost_usd = api_daily_usage.estimated_cost_usd + excluded.estimated_cost_usd,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["usage_date"],
                    payload["source"],
                    payload["request_count"],
                    payload["success_count"],
                    payload["error_count"],
                    payload["input_units"],
                    payload["output_units"],
                    payload["estimated_cost_usd"],
                    datetime.now().astimezone().isoformat(),
                ),
            )

    def _record_api_call_postgres(self, payload: dict[str, Any]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO api_request_events (
                        usage_date,
                        requested_at,
                        tick_id,
                        source,
                        endpoint,
                        request_count,
                        success_count,
                        error_count,
                        input_units,
                        output_units,
                        estimated_cost_usd,
                        currency,
                        notes,
                        metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'USD', %s, %s::jsonb)
                    """,
                    (
                        payload["usage_date"],
                        payload["requested_at"],
                        payload["tick_id"],
                        payload["source"],
                        payload["endpoint"],
                        payload["request_count"],
                        payload["success_count"],
                        payload["error_count"],
                        payload["input_units"],
                        payload["output_units"],
                        payload["estimated_cost_usd"],
                        payload["notes"],
                        payload["metadata_json"],
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO api_daily_usage (
                        usage_date,
                        source,
                        request_count,
                        success_count,
                        error_count,
                        input_units,
                        output_units,
                        estimated_cost_usd,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(usage_date, source) DO UPDATE SET
                        request_count = api_daily_usage.request_count + EXCLUDED.request_count,
                        success_count = api_daily_usage.success_count + EXCLUDED.success_count,
                        error_count = api_daily_usage.error_count + EXCLUDED.error_count,
                        input_units = api_daily_usage.input_units + EXCLUDED.input_units,
                        output_units = api_daily_usage.output_units + EXCLUDED.output_units,
                        estimated_cost_usd = api_daily_usage.estimated_cost_usd + EXCLUDED.estimated_cost_usd,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        payload["usage_date"],
                        payload["source"],
                        payload["request_count"],
                        payload["success_count"],
                        payload["error_count"],
                        payload["input_units"],
                        payload["output_units"],
                        payload["estimated_cost_usd"],
                        datetime.now().astimezone(),
                    ),
                )

    def _record_tick_run_sqlite(self, payload: dict[str, Any]) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO control_tick_runs (
                    tick_id,
                    started_at,
                    ended_at,
                    status,
                    duration_seconds,
                    step_count,
                    error_count,
                    tick_api_request_count,
                    tick_estimated_cost_usd,
                    daily_api_request_count,
                    daily_estimated_cost_usd,
                    budget_status,
                    operations_backend,
                    last_error,
                    step_profiles_json,
                    state_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    status = excluded.status,
                    duration_seconds = excluded.duration_seconds,
                    step_count = excluded.step_count,
                    error_count = excluded.error_count,
                    tick_api_request_count = excluded.tick_api_request_count,
                    tick_estimated_cost_usd = excluded.tick_estimated_cost_usd,
                    daily_api_request_count = excluded.daily_api_request_count,
                    daily_estimated_cost_usd = excluded.daily_estimated_cost_usd,
                    budget_status = excluded.budget_status,
                    operations_backend = excluded.operations_backend,
                    last_error = excluded.last_error,
                    step_profiles_json = excluded.step_profiles_json,
                    state_snapshot_json = excluded.state_snapshot_json
                """,
                (
                    payload["tick_id"],
                    payload["started_at"],
                    payload["ended_at"],
                    payload["status"],
                    payload["duration_seconds"],
                    payload["step_count"],
                    payload["error_count"],
                    payload["tick_api_request_count"],
                    payload["tick_estimated_cost_usd"],
                    payload["daily_api_request_count"],
                    payload["daily_estimated_cost_usd"],
                    payload["budget_status"],
                    payload["operations_backend"],
                    payload["last_error"],
                    payload["step_profiles_json"],
                    payload["state_snapshot_json"],
                ),
            )

    def _record_tick_run_postgres(self, payload: dict[str, Any]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO control_tick_runs (
                        tick_id,
                        started_at,
                        ended_at,
                        status,
                        duration_seconds,
                        step_count,
                        error_count,
                        tick_api_request_count,
                        tick_estimated_cost_usd,
                        daily_api_request_count,
                        daily_estimated_cost_usd,
                        budget_status,
                        operations_backend,
                        last_error,
                        step_profiles_json,
                        state_snapshot_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT(tick_id) DO UPDATE SET
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at,
                        status = EXCLUDED.status,
                        duration_seconds = EXCLUDED.duration_seconds,
                        step_count = EXCLUDED.step_count,
                        error_count = EXCLUDED.error_count,
                        tick_api_request_count = EXCLUDED.tick_api_request_count,
                        tick_estimated_cost_usd = EXCLUDED.tick_estimated_cost_usd,
                        daily_api_request_count = EXCLUDED.daily_api_request_count,
                        daily_estimated_cost_usd = EXCLUDED.daily_estimated_cost_usd,
                        budget_status = EXCLUDED.budget_status,
                        operations_backend = EXCLUDED.operations_backend,
                        last_error = EXCLUDED.last_error,
                        step_profiles_json = EXCLUDED.step_profiles_json,
                        state_snapshot_json = EXCLUDED.state_snapshot_json
                    """,
                    (
                        payload["tick_id"],
                        payload["started_at"],
                        payload["ended_at"],
                        payload["status"],
                        payload["duration_seconds"],
                        payload["step_count"],
                        payload["error_count"],
                        payload["tick_api_request_count"],
                        payload["tick_estimated_cost_usd"],
                        payload["daily_api_request_count"],
                        payload["daily_estimated_cost_usd"],
                        payload["budget_status"],
                        payload["operations_backend"],
                        payload["last_error"],
                        payload["step_profiles_json"],
                        payload["state_snapshot_json"],
                    ),
                )

    def _record_execution_router_intent_sqlite(self, *, row: dict[str, Any]) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO execution_router_intents (
                    tick_id, recorded_at, environment, mode, lane, action,
                    broker_id, status, strategy_id, symbol, order_id,
                    canonical_instrument_id, venue, venue_symbol, intended_order_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["tick_id"],
                    row["recorded_at"],
                    row["environment"],
                    row["mode"],
                    row["lane"],
                    row["action"],
                    row["broker_id"],
                    row["status"],
                    row["strategy_id"],
                    row["symbol"],
                    row["order_id"],
                    row["canonical_instrument_id"],
                    row["venue"],
                    row["venue_symbol"],
                    row["intended_order_json"],
                ),
            )

    def _record_execution_router_intent_postgres(self, *, row: dict[str, Any]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO execution_router_intents (
                        tick_id, recorded_at, environment, mode, lane, action,
                        broker_id, status, strategy_id, symbol, order_id,
                        canonical_instrument_id, venue, venue_symbol, intended_order_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        row["tick_id"],
                        row["recorded_at"],
                        row["environment"],
                        row["mode"],
                        row["lane"],
                        row["action"],
                        row["broker_id"],
                        row["status"],
                        row["strategy_id"],
                        row["symbol"],
                        row["order_id"],
                        row["canonical_instrument_id"],
                        row["venue"],
                        row["venue_symbol"],
                        row["intended_order_json"],
                    ),
                )

    def _record_latest_bars_sqlite(self, rows: list[dict[str, Any]]) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO market_data_latest_bars (
                    tick_id,
                    captured_at,
                    source,
                    symbol,
                    asset_class,
                    canonical_instrument_id,
                    venue,
                    venue_symbol,
                    bar_timestamp,
                    quote_currency,
                    usd_to_gbp_rate,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    open_price_gbp,
                    high_price_gbp,
                    low_price_gbp,
                    close_price_gbp,
                    volume,
                    trade_count,
                    vwap,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, source, symbol) DO UPDATE SET
                    captured_at = excluded.captured_at,
                    asset_class = excluded.asset_class,
                    canonical_instrument_id = excluded.canonical_instrument_id,
                    venue = excluded.venue,
                    venue_symbol = excluded.venue_symbol,
                    bar_timestamp = excluded.bar_timestamp,
                    quote_currency = excluded.quote_currency,
                    usd_to_gbp_rate = excluded.usd_to_gbp_rate,
                    open_price = excluded.open_price,
                    high_price = excluded.high_price,
                    low_price = excluded.low_price,
                    close_price = excluded.close_price,
                    open_price_gbp = excluded.open_price_gbp,
                    high_price_gbp = excluded.high_price_gbp,
                    low_price_gbp = excluded.low_price_gbp,
                    close_price_gbp = excluded.close_price_gbp,
                    volume = excluded.volume,
                    trade_count = excluded.trade_count,
                    vwap = excluded.vwap,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        row["tick_id"],
                        row["captured_at"],
                        row["source"],
                        row["symbol"],
                        row["asset_class"],
                        row["canonical_instrument_id"],
                        row["venue"],
                        row["venue_symbol"],
                        row["bar_timestamp"],
                        row["quote_currency"],
                        row["usd_to_gbp_rate"],
                        row["open_price"],
                        row["high_price"],
                        row["low_price"],
                        row["close_price"],
                        row["open_price_gbp"],
                        row["high_price_gbp"],
                        row["low_price_gbp"],
                        row["close_price_gbp"],
                        row["volume"],
                        row["trade_count"],
                        row["vwap"],
                        row["raw_json"],
                    )
                    for row in rows
                ],
            )

    def _record_latest_bars_postgres(self, rows: list[dict[str, Any]]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO market_data_latest_bars (
                        tick_id,
                        captured_at,
                        source,
                        symbol,
                        asset_class,
                        canonical_instrument_id,
                        venue,
                        venue_symbol,
                        bar_timestamp,
                        quote_currency,
                        usd_to_gbp_rate,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        open_price_gbp,
                        high_price_gbp,
                        low_price_gbp,
                        close_price_gbp,
                        volume,
                        trade_count,
                        vwap,
                        raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(tick_id, source, symbol) DO UPDATE SET
                        captured_at = EXCLUDED.captured_at,
                        asset_class = EXCLUDED.asset_class,
                        canonical_instrument_id = EXCLUDED.canonical_instrument_id,
                        venue = EXCLUDED.venue,
                        venue_symbol = EXCLUDED.venue_symbol,
                        bar_timestamp = EXCLUDED.bar_timestamp,
                        quote_currency = EXCLUDED.quote_currency,
                        usd_to_gbp_rate = EXCLUDED.usd_to_gbp_rate,
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        open_price_gbp = EXCLUDED.open_price_gbp,
                        high_price_gbp = EXCLUDED.high_price_gbp,
                        low_price_gbp = EXCLUDED.low_price_gbp,
                        close_price_gbp = EXCLUDED.close_price_gbp,
                        volume = EXCLUDED.volume,
                        trade_count = EXCLUDED.trade_count,
                        vwap = EXCLUDED.vwap,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            row["tick_id"],
                            row["captured_at"],
                            row["source"],
                            row["symbol"],
                            row["asset_class"],
                            row["canonical_instrument_id"],
                            row["venue"],
                            row["venue_symbol"],
                            row["bar_timestamp"],
                            row["quote_currency"],
                            row["usd_to_gbp_rate"],
                            row["open_price"],
                            row["high_price"],
                            row["low_price"],
                            row["close_price"],
                            row["open_price_gbp"],
                            row["high_price_gbp"],
                            row["low_price_gbp"],
                            row["close_price_gbp"],
                            row["volume"],
                            row["trade_count"],
                            row["vwap"],
                            row["raw_json"],
                        )
                        for row in rows
                    ],
                )

    def _record_historical_bars_sqlite(self, rows: list[dict[str, Any]]) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO market_data_historical_bars (
                    batch_id,
                    captured_at,
                    source,
                    asset_class,
                    canonical_instrument_id,
                    venue,
                    venue_symbol,
                    symbol,
                    timeframe,
                    bar_timestamp,
                    quote_currency,
                    usd_to_gbp_rate,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    open_price_gbp,
                    high_price_gbp,
                    low_price_gbp,
                    close_price_gbp,
                    volume,
                    trade_count,
                    vwap,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, symbol, timeframe, bar_timestamp) DO UPDATE SET
                    batch_id = excluded.batch_id,
                    captured_at = excluded.captured_at,
                    asset_class = excluded.asset_class,
                    canonical_instrument_id = excluded.canonical_instrument_id,
                    venue = excluded.venue,
                    venue_symbol = excluded.venue_symbol,
                    quote_currency = excluded.quote_currency,
                    usd_to_gbp_rate = excluded.usd_to_gbp_rate,
                    open_price = excluded.open_price,
                    high_price = excluded.high_price,
                    low_price = excluded.low_price,
                    close_price = excluded.close_price,
                    open_price_gbp = excluded.open_price_gbp,
                    high_price_gbp = excluded.high_price_gbp,
                    low_price_gbp = excluded.low_price_gbp,
                    close_price_gbp = excluded.close_price_gbp,
                    volume = excluded.volume,
                    trade_count = excluded.trade_count,
                    vwap = excluded.vwap,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        row["batch_id"],
                        row["captured_at"],
                        row["source"],
                        row["asset_class"],
                        row["canonical_instrument_id"],
                        row["venue"],
                        row["venue_symbol"],
                        row["symbol"],
                        row["timeframe"],
                        row["bar_timestamp"],
                        row["quote_currency"],
                        row["usd_to_gbp_rate"],
                        row["open_price"],
                        row["high_price"],
                        row["low_price"],
                        row["close_price"],
                        row["open_price_gbp"],
                        row["high_price_gbp"],
                        row["low_price_gbp"],
                        row["close_price_gbp"],
                        row["volume"],
                        row["trade_count"],
                        row["vwap"],
                        row["raw_json"],
                    )
                    for row in rows
                ],
            )

    def _record_historical_bars_postgres(self, rows: list[dict[str, Any]]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO market_data_historical_bars (
                        batch_id,
                        captured_at,
                        source,
                        asset_class,
                        canonical_instrument_id,
                        venue,
                        venue_symbol,
                        symbol,
                        timeframe,
                        bar_timestamp,
                        quote_currency,
                        usd_to_gbp_rate,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        open_price_gbp,
                        high_price_gbp,
                        low_price_gbp,
                        close_price_gbp,
                        volume,
                        trade_count,
                        vwap,
                        raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(source, symbol, timeframe, bar_timestamp) DO UPDATE SET
                        batch_id = EXCLUDED.batch_id,
                        captured_at = EXCLUDED.captured_at,
                        asset_class = EXCLUDED.asset_class,
                        canonical_instrument_id = EXCLUDED.canonical_instrument_id,
                        venue = EXCLUDED.venue,
                        venue_symbol = EXCLUDED.venue_symbol,
                        quote_currency = EXCLUDED.quote_currency,
                        usd_to_gbp_rate = EXCLUDED.usd_to_gbp_rate,
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        open_price_gbp = EXCLUDED.open_price_gbp,
                        high_price_gbp = EXCLUDED.high_price_gbp,
                        low_price_gbp = EXCLUDED.low_price_gbp,
                        close_price_gbp = EXCLUDED.close_price_gbp,
                        volume = EXCLUDED.volume,
                        trade_count = EXCLUDED.trade_count,
                        vwap = EXCLUDED.vwap,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            row["batch_id"],
                            row["captured_at"],
                            row["source"],
                            row["asset_class"],
                            row["canonical_instrument_id"],
                            row["venue"],
                            row["venue_symbol"],
                            row["symbol"],
                            row["timeframe"],
                            row["bar_timestamp"],
                            row["quote_currency"],
                            row["usd_to_gbp_rate"],
                            row["open_price"],
                            row["high_price"],
                            row["low_price"],
                            row["close_price"],
                            row["open_price_gbp"],
                            row["high_price_gbp"],
                            row["low_price_gbp"],
                            row["close_price_gbp"],
                            row["volume"],
                            row["trade_count"],
                            row["vwap"],
                            row["raw_json"],
                        )
                        for row in rows
                    ],
                )

    def _record_fx_reference_rate_sqlite(self, rate: dict[str, Any]) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO fx_reference_rates (
                    source,
                    provider_date,
                    fetched_at,
                    base_currency,
                    usd_per_eur,
                    gbp_per_eur,
                    usd_to_gbp,
                    gbp_to_usd,
                    mode,
                    raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, provider_date) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    base_currency = excluded.base_currency,
                    usd_per_eur = excluded.usd_per_eur,
                    gbp_per_eur = excluded.gbp_per_eur,
                    usd_to_gbp = excluded.usd_to_gbp,
                    gbp_to_usd = excluded.gbp_to_usd,
                    mode = excluded.mode,
                    raw_payload = excluded.raw_payload
                """,
                (
                    rate["source"],
                    rate["provider_date"],
                    rate["fetched_at"],
                    rate["base_currency"],
                    rate["usd_per_eur"],
                    rate["gbp_per_eur"],
                    rate["usd_to_gbp"],
                    rate["gbp_to_usd"],
                    rate["mode"],
                    rate["raw_payload"],
                ),
            )

    def _record_fx_reference_rate_postgres(self, rate: dict[str, Any]) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO fx_reference_rates (
                        source,
                        provider_date,
                        fetched_at,
                        base_currency,
                        usd_per_eur,
                        gbp_per_eur,
                        usd_to_gbp,
                        gbp_to_usd,
                        mode,
                        raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(source, provider_date) DO UPDATE SET
                        fetched_at = EXCLUDED.fetched_at,
                        base_currency = EXCLUDED.base_currency,
                        usd_per_eur = EXCLUDED.usd_per_eur,
                        gbp_per_eur = EXCLUDED.gbp_per_eur,
                        usd_to_gbp = EXCLUDED.usd_to_gbp,
                        gbp_to_usd = EXCLUDED.gbp_to_usd,
                        mode = EXCLUDED.mode,
                        raw_payload = EXCLUDED.raw_payload
                    """,
                    (
                        rate["source"],
                        rate["provider_date"],
                        rate["fetched_at"],
                        rate["base_currency"],
                        rate["usd_per_eur"],
                        rate["gbp_per_eur"],
                        rate["usd_to_gbp"],
                        rate["gbp_to_usd"],
                        rate["mode"],
                        rate["raw_payload"],
                    ),
                )

    def _get_latest_fx_reference_sqlite(self, *, source: str) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT source, provider_date, fetched_at, base_currency,
                       usd_per_eur, gbp_per_eur, usd_to_gbp, gbp_to_usd,
                       mode, raw_payload
                FROM fx_reference_rates
                WHERE source = ?
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (source,),
            ).fetchone()
        return dict(row) if row else None

    def _get_latest_fx_reference_postgres(self, *, source: str) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT source, provider_date, fetched_at, base_currency,
                           usd_per_eur, gbp_per_eur, usd_to_gbp, gbp_to_usd,
                           mode, raw_payload
                    FROM fx_reference_rates
                    WHERE source = %s
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    (source,),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def _get_latest_bars_for_tick_sqlite(
        self,
        *,
        tick_id: str,
        sources: list[str],
    ) -> list[dict[str, Any]]:
        if not sources:
            return []

        placeholders = ",".join("?" for _ in sources)
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                f"""
                SELECT tick_id, source, symbol, asset_class,
                       canonical_instrument_id, venue, venue_symbol,
                       bar_timestamp, quote_currency,
                       open_price, high_price, low_price, close_price,
                       open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                       volume, trade_count, vwap
                FROM market_data_latest_bars
                WHERE tick_id = ? AND source IN ({placeholders})
                ORDER BY source, symbol
                """,
                (tick_id, *sources),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_latest_bars_for_tick_postgres(
        self,
        *,
        tick_id: str,
        sources: list[str],
    ) -> list[dict[str, Any]]:
        if not sources:
            return []

        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT tick_id, source, symbol, asset_class,
                           canonical_instrument_id, venue, venue_symbol,
                           bar_timestamp, quote_currency,
                           open_price, high_price, low_price, close_price,
                           open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                           volume, trade_count, vwap
                    FROM market_data_latest_bars
                    WHERE tick_id = %s AND source = ANY(%s)
                    ORDER BY source, symbol
                    """,
                    (tick_id, sources),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_previous_bars_sqlite(
        self,
        *,
        tick_id: str,
        symbol_keys: list[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        if not symbol_keys:
            return result

        with self._connect_sqlite() as connection:
            for source, symbol in symbol_keys:
                row = connection.execute(
                    """
                    SELECT tick_id, source, symbol, bar_timestamp, quote_currency,
                           open_price, high_price, low_price, close_price,
                           open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                           volume, trade_count, vwap
                    FROM market_data_latest_bars
                    WHERE source = ? AND symbol = ? AND tick_id != ?
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """,
                    (source, symbol, tick_id),
                ).fetchone()
                if row is not None:
                    result[(source, symbol)] = dict(row)
        return result

    def _get_previous_bars_postgres(
        self,
        *,
        tick_id: str,
        symbol_keys: list[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        if not symbol_keys:
            return result

        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                for source, symbol in symbol_keys:
                    cursor.execute(
                        """
                        SELECT tick_id, source, symbol, bar_timestamp, quote_currency,
                               open_price, high_price, low_price, close_price,
                               open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                               volume, trade_count, vwap
                        FROM market_data_latest_bars
                        WHERE source = %s AND symbol = %s AND tick_id != %s
                        ORDER BY captured_at DESC
                        LIMIT 1
                        """,
                        (source, symbol, tick_id),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        result[(source, symbol)] = dict(row)
        return result

    def _record_discovery_candidates_sqlite(
        self,
        *,
        tick_id: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO discovery_candidates (
                    tick_id, source, symbol, asset_class, rank, selected,
                    discovery_score, close_price, close_price_gbp, previous_close_price,
                    movement_pct, volume, trade_count, bar_timestamp, note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, source, symbol) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    rank = excluded.rank,
                    selected = excluded.selected,
                    discovery_score = excluded.discovery_score,
                    close_price = excluded.close_price,
                    close_price_gbp = excluded.close_price_gbp,
                    previous_close_price = excluded.previous_close_price,
                    movement_pct = excluded.movement_pct,
                    volume = excluded.volume,
                    trade_count = excluded.trade_count,
                    bar_timestamp = excluded.bar_timestamp,
                    note = excluded.note,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        tick_id,
                        item["source"],
                        item["symbol"],
                        item["asset_class"],
                        item["rank"],
                        1 if item["selected"] else 0,
                        item["discovery_score"],
                        item["close_price"],
                        item["close_price_gbp"],
                        item["previous_close_price"],
                        item["movement_pct"],
                        item["volume"],
                        item["trade_count"],
                        item["bar_timestamp"],
                        item["note"],
                        self._to_json(item),
                    )
                    for item in candidates
                ],
            )

    def _record_discovery_candidates_postgres(
        self,
        *,
        tick_id: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO discovery_candidates (
                        tick_id, source, symbol, asset_class, rank, selected,
                        discovery_score, close_price, close_price_gbp, previous_close_price,
                        movement_pct, volume, trade_count, bar_timestamp, note, raw_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(tick_id, source, symbol) DO UPDATE SET
                        asset_class = EXCLUDED.asset_class,
                        rank = EXCLUDED.rank,
                        selected = EXCLUDED.selected,
                        discovery_score = EXCLUDED.discovery_score,
                        close_price = EXCLUDED.close_price,
                        close_price_gbp = EXCLUDED.close_price_gbp,
                        previous_close_price = EXCLUDED.previous_close_price,
                        movement_pct = EXCLUDED.movement_pct,
                        volume = EXCLUDED.volume,
                        trade_count = EXCLUDED.trade_count,
                        bar_timestamp = EXCLUDED.bar_timestamp,
                        note = EXCLUDED.note,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            tick_id,
                            item["source"],
                            item["symbol"],
                            item["asset_class"],
                            item["rank"],
                            item["selected"],
                            item["discovery_score"],
                            item["close_price"],
                            item["close_price_gbp"],
                            item["previous_close_price"],
                            item["movement_pct"],
                            item["volume"],
                            item["trade_count"],
                            item["bar_timestamp"],
                            item["note"],
                            self._to_json(item),
                        )
                        for item in candidates
                    ],
                )

    def _record_gemini_analyses_sqlite(
        self,
        *,
        tick_id: str,
        analyses: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO gemini_candidate_analyses (
                    tick_id, symbol, action_bias, opportunity_score,
                    confidence, thesis, risks_json, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, symbol) DO UPDATE SET
                    action_bias = excluded.action_bias,
                    opportunity_score = excluded.opportunity_score,
                    confidence = excluded.confidence,
                    thesis = excluded.thesis,
                    risks_json = excluded.risks_json,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        tick_id,
                        item["symbol"],
                        item.get("action_bias", "hold"),
                        item.get("opportunity_score", 0),
                        item.get("confidence", 0),
                        item.get("thesis", ""),
                        self._to_json(item.get("risks", [])),
                        self._to_json(item),
                    )
                    for item in analyses
                ],
            )

    def _record_gemini_analyses_postgres(
        self,
        *,
        tick_id: str,
        analyses: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO gemini_candidate_analyses (
                        tick_id, symbol, action_bias, opportunity_score,
                        confidence, thesis, risks_json, raw_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT(tick_id, symbol) DO UPDATE SET
                        action_bias = EXCLUDED.action_bias,
                        opportunity_score = EXCLUDED.opportunity_score,
                        confidence = EXCLUDED.confidence,
                        thesis = EXCLUDED.thesis,
                        risks_json = EXCLUDED.risks_json,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            tick_id,
                            item["symbol"],
                            item.get("action_bias", "hold"),
                            item.get("opportunity_score", 0),
                            item.get("confidence", 0),
                            item.get("thesis", ""),
                            self._to_json(item.get("risks", [])),
                            self._to_json(item),
                        )
                        for item in analyses
                    ],
                )

    def _record_strategy_candidate_signals_sqlite(
        self,
        *,
        tick_id: str,
        signals: list[dict[str, Any]],
    ) -> None:
        if not signals:
            return

        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO strategy_candidate_signals (
                    tick_id, strategy_id, strategy_family, profile_id, source, symbol,
                    asset_class, canonical_instrument_id, venue, venue_symbol,
                    direction, signal_rank, signal_score, confidence,
                    entry_price, entry_price_gbp, stop_loss_price, stop_loss_price_gbp,
                    target_price, target_price_gbp, risk_pct, target_return_pct,
                    holding_window_code, holding_window_minutes, movement_pct,
                    discovery_score, rationale, note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, strategy_id, source, symbol) DO UPDATE SET
                    strategy_family = excluded.strategy_family,
                    profile_id = excluded.profile_id,
                    asset_class = excluded.asset_class,
                    canonical_instrument_id = excluded.canonical_instrument_id,
                    venue = excluded.venue,
                    venue_symbol = excluded.venue_symbol,
                    direction = excluded.direction,
                    signal_rank = excluded.signal_rank,
                    signal_score = excluded.signal_score,
                    confidence = excluded.confidence,
                    entry_price = excluded.entry_price,
                    entry_price_gbp = excluded.entry_price_gbp,
                    stop_loss_price = excluded.stop_loss_price,
                    stop_loss_price_gbp = excluded.stop_loss_price_gbp,
                    target_price = excluded.target_price,
                    target_price_gbp = excluded.target_price_gbp,
                    risk_pct = excluded.risk_pct,
                    target_return_pct = excluded.target_return_pct,
                    holding_window_code = excluded.holding_window_code,
                    holding_window_minutes = excluded.holding_window_minutes,
                    movement_pct = excluded.movement_pct,
                    discovery_score = excluded.discovery_score,
                    rationale = excluded.rationale,
                    note = excluded.note,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        tick_id,
                        item["strategy_id"],
                        item["strategy_family"],
                        item["profile_id"],
                        item["source"],
                        item["symbol"],
                        item["asset_class"],
                        item.get("canonical_instrument_id", ""),
                        item.get("venue", ""),
                        item.get("venue_symbol", item.get("symbol", "")),
                        item.get("direction", "long"),
                        item.get("signal_rank", 0),
                        item.get("signal_score", 0),
                        item.get("confidence", 0),
                        item["entry_price"],
                        item.get("entry_price_gbp"),
                        item["stop_loss_price"],
                        item.get("stop_loss_price_gbp"),
                        item["target_price"],
                        item.get("target_price_gbp"),
                        item.get("risk_pct", 0),
                        item.get("target_return_pct", 0),
                        item["holding_window_code"],
                        item["holding_window_minutes"],
                        item.get("movement_pct"),
                        item.get("discovery_score", 0),
                        item.get("rationale", ""),
                        item.get("note", ""),
                        self._to_json(item),
                    )
                    for item in signals
                ],
            )

    def _record_strategy_candidate_signals_postgres(
        self,
        *,
        tick_id: str,
        signals: list[dict[str, Any]],
    ) -> None:
        if not signals:
            return

        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO strategy_candidate_signals (
                        tick_id, strategy_id, strategy_family, profile_id, source, symbol,
                        asset_class, canonical_instrument_id, venue, venue_symbol,
                        direction, signal_rank, signal_score, confidence,
                        entry_price, entry_price_gbp, stop_loss_price, stop_loss_price_gbp,
                        target_price, target_price_gbp, risk_pct, target_return_pct,
                        holding_window_code, holding_window_minutes, movement_pct,
                        discovery_score, rationale, note, raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(tick_id, strategy_id, source, symbol) DO UPDATE SET
                        strategy_family = EXCLUDED.strategy_family,
                        profile_id = EXCLUDED.profile_id,
                        asset_class = EXCLUDED.asset_class,
                        canonical_instrument_id = EXCLUDED.canonical_instrument_id,
                        venue = EXCLUDED.venue,
                        venue_symbol = EXCLUDED.venue_symbol,
                        direction = EXCLUDED.direction,
                        signal_rank = EXCLUDED.signal_rank,
                        signal_score = EXCLUDED.signal_score,
                        confidence = EXCLUDED.confidence,
                        entry_price = EXCLUDED.entry_price,
                        entry_price_gbp = EXCLUDED.entry_price_gbp,
                        stop_loss_price = EXCLUDED.stop_loss_price,
                        stop_loss_price_gbp = EXCLUDED.stop_loss_price_gbp,
                        target_price = EXCLUDED.target_price,
                        target_price_gbp = EXCLUDED.target_price_gbp,
                        risk_pct = EXCLUDED.risk_pct,
                        target_return_pct = EXCLUDED.target_return_pct,
                        holding_window_code = EXCLUDED.holding_window_code,
                        holding_window_minutes = EXCLUDED.holding_window_minutes,
                        movement_pct = EXCLUDED.movement_pct,
                        discovery_score = EXCLUDED.discovery_score,
                        rationale = EXCLUDED.rationale,
                        note = EXCLUDED.note,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            tick_id,
                            item["strategy_id"],
                            item["strategy_family"],
                            item["profile_id"],
                            item["source"],
                            item["symbol"],
                            item["asset_class"],
                            item.get("canonical_instrument_id", ""),
                            item.get("venue", ""),
                            item.get("venue_symbol", item.get("symbol", "")),
                            item.get("direction", "long"),
                            item.get("signal_rank", 0),
                            item.get("signal_score", 0),
                            item.get("confidence", 0),
                            item["entry_price"],
                            item.get("entry_price_gbp"),
                            item["stop_loss_price"],
                            item.get("stop_loss_price_gbp"),
                            item["target_price"],
                            item.get("target_price_gbp"),
                            item.get("risk_pct", 0),
                            item.get("target_return_pct", 0),
                            item["holding_window_code"],
                            item["holding_window_minutes"],
                            item.get("movement_pct"),
                            item.get("discovery_score", 0),
                            item.get("rationale", ""),
                            item.get("note", ""),
                            self._to_json(item),
                        )
                        for item in signals
                    ],
                )

    def _get_strategy_threshold_adaptive_state_sqlite(self) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT state_id, effective_threshold, updated_at, source_tick_id,
                       reason, advice_json
                FROM strategy_threshold_adaptive_state
                WHERE state_id = 'current'
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_strategy_threshold_adaptive_state_postgres(self) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT state_id, effective_threshold, updated_at, source_tick_id,
                           reason, advice_json
                    FROM strategy_threshold_adaptive_state
                    WHERE state_id = 'current'
                    """
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _record_strategy_threshold_adaptive_state_sqlite(
        self,
        *,
        row: dict[str, Any],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO strategy_threshold_adaptive_state (
                    state_id, effective_threshold, updated_at, source_tick_id,
                    reason, advice_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_id) DO UPDATE SET
                    effective_threshold = excluded.effective_threshold,
                    updated_at = excluded.updated_at,
                    source_tick_id = excluded.source_tick_id,
                    reason = excluded.reason,
                    advice_json = excluded.advice_json
                """,
                (
                    row["state_id"],
                    row["effective_threshold"],
                    row["updated_at"],
                    row["source_tick_id"],
                    row["reason"],
                    row["advice_json"],
                ),
            )

    def _record_strategy_threshold_adaptive_state_postgres(
        self,
        *,
        row: dict[str, Any],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_threshold_adaptive_state (
                        state_id, effective_threshold, updated_at, source_tick_id,
                        reason, advice_json
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(state_id) DO UPDATE SET
                        effective_threshold = EXCLUDED.effective_threshold,
                        updated_at = EXCLUDED.updated_at,
                        source_tick_id = EXCLUDED.source_tick_id,
                        reason = EXCLUDED.reason,
                        advice_json = EXCLUDED.advice_json
                    """,
                    (
                        row["state_id"],
                        row["effective_threshold"],
                        row["updated_at"],
                        row["source_tick_id"],
                        row["reason"],
                        row["advice_json"],
                    ),
                )

    def _backfill_sqlite_instrument_metadata(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        timestamp_column: str,
        has_broker: bool,
    ) -> None:
        del timestamp_column
        broker_expr = "broker_id" if has_broker else "''"
        connection.execute(
            f"""
            UPDATE {table_name}
            SET canonical_instrument_id = CASE
                    WHEN canonical_instrument_id <> '' THEN canonical_instrument_id
                    WHEN lower(asset_class) = 'crypto' AND instr(upper(symbol), '/') > 0
                        THEN replace(upper(symbol), '/', '-') || '-SPOT'
                    WHEN lower(asset_class) = 'crypto' AND upper(symbol) LIKE '%USDT'
                        THEN substr(upper(symbol), 1, length(upper(symbol)) - 4) || '-USD-SPOT'
                    WHEN lower(asset_class) = 'crypto' AND upper(symbol) LIKE '%USD'
                        THEN substr(upper(symbol), 1, length(upper(symbol)) - 3) || '-USD-SPOT'
                    WHEN lower(asset_class) IN ('equity', 'etf')
                        THEN upper(symbol) || '-US-EQUITY'
                    ELSE upper(symbol)
                END,
                venue = CASE
                    WHEN venue <> '' THEN venue
                    WHEN lower(COALESCE(source, '')) LIKE '%alpaca%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%alpaca%' THEN 'alpaca'
                    WHEN lower(COALESCE(source, '')) LIKE '%binance%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%binance%' THEN 'binance'
                    WHEN lower(COALESCE(source, '')) LIKE '%coinbase%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%coinbase%' THEN 'coinbase'
                    ELSE venue
                END,
                venue_symbol = CASE
                    WHEN venue_symbol <> '' THEN venue_symbol
                    ELSE upper(symbol)
                END
            WHERE symbol <> ''
              AND (canonical_instrument_id = '' OR venue = '' OR venue_symbol = '')
            """
        )

    def _backfill_postgres_instrument_metadata(
        self,
        cursor: Any,
        *,
        table_name: str,
        has_broker: bool,
    ) -> None:
        broker_expr = "broker_id" if has_broker else "''"
        cursor.execute(
            f"""
            UPDATE {table_name}
            SET canonical_instrument_id = CASE
                    WHEN canonical_instrument_id <> '' THEN canonical_instrument_id
                    WHEN lower(asset_class) = 'crypto' AND strpos(upper(symbol), '/') > 0
                        THEN replace(upper(symbol), '/', '-') || '-SPOT'
                    WHEN lower(asset_class) = 'crypto' AND upper(symbol) LIKE '%USDT'
                        THEN substring(upper(symbol) from 1 for length(upper(symbol)) - 4) || '-USD-SPOT'
                    WHEN lower(asset_class) = 'crypto' AND upper(symbol) LIKE '%USD'
                        THEN substring(upper(symbol) from 1 for length(upper(symbol)) - 3) || '-USD-SPOT'
                    WHEN lower(asset_class) IN ('equity', 'etf')
                        THEN upper(symbol) || '-US-EQUITY'
                    ELSE upper(symbol)
                END,
                venue = CASE
                    WHEN venue <> '' THEN venue
                    WHEN lower(COALESCE(source, '')) LIKE '%alpaca%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%alpaca%' THEN 'alpaca'
                    WHEN lower(COALESCE(source, '')) LIKE '%binance%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%binance%' THEN 'binance'
                    WHEN lower(COALESCE(source, '')) LIKE '%coinbase%'
                      OR lower(COALESCE({broker_expr}, '')) LIKE '%coinbase%' THEN 'coinbase'
                    ELSE venue
                END,
                venue_symbol = CASE
                    WHEN venue_symbol <> '' THEN venue_symbol
                    ELSE upper(symbol)
                END
            WHERE symbol <> ''
              AND (canonical_instrument_id = '' OR venue = '' OR venue_symbol = '')
            """
        )

    def _backfill_sqlite_shadow_outcome_instrument_metadata(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            UPDATE shadow_trade_outcomes
            SET canonical_instrument_id = COALESCE(
                    (
                        SELECT NULLIF(p.canonical_instrument_id, '')
                        FROM shadow_trade_proposals p
                        WHERE p.proposal_id = shadow_trade_outcomes.proposal_id
                    ),
                    canonical_instrument_id
                ),
                venue = COALESCE(
                    (
                        SELECT NULLIF(p.venue, '')
                        FROM shadow_trade_proposals p
                        WHERE p.proposal_id = shadow_trade_outcomes.proposal_id
                    ),
                    venue
                ),
                venue_symbol = COALESCE(
                    (
                        SELECT NULLIF(p.venue_symbol, '')
                        FROM shadow_trade_proposals p
                        WHERE p.proposal_id = shadow_trade_outcomes.proposal_id
                    ),
                    venue_symbol
                )
            WHERE EXISTS (
                SELECT 1
                FROM shadow_trade_proposals p
                WHERE p.proposal_id = shadow_trade_outcomes.proposal_id
            )
              AND (canonical_instrument_id = '' OR venue = '' OR venue_symbol = '')
            """
        )

    def _backfill_postgres_shadow_outcome_instrument_metadata(self, cursor: Any) -> None:
        cursor.execute(
            """
            UPDATE shadow_trade_outcomes o
            SET canonical_instrument_id = COALESCE(NULLIF(p.canonical_instrument_id, ''), o.canonical_instrument_id),
                venue = COALESCE(NULLIF(p.venue, ''), o.venue),
                venue_symbol = COALESCE(NULLIF(p.venue_symbol, ''), o.venue_symbol)
            FROM shadow_trade_proposals p
            WHERE p.proposal_id = o.proposal_id
              AND (o.canonical_instrument_id = '' OR o.venue = '' OR o.venue_symbol = '')
            """
        )

    def _record_broker_account_snapshots_sqlite(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO broker_account_snapshots (
                    tick_id, broker_id, captured_at, account_status, currency,
                    equity, cash, buying_power, portfolio_value, last_equity,
                    position_market_value, open_position_unrealized_pl, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, broker_id) DO UPDATE SET
                    captured_at = excluded.captured_at,
                    account_status = excluded.account_status,
                    currency = excluded.currency,
                    equity = excluded.equity,
                    cash = excluded.cash,
                    buying_power = excluded.buying_power,
                    portfolio_value = excluded.portfolio_value,
                    last_equity = excluded.last_equity,
                    position_market_value = excluded.position_market_value,
                    open_position_unrealized_pl = excluded.open_position_unrealized_pl,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        row["tick_id"],
                        row["broker_id"],
                        row["captured_at"],
                        row["account_status"],
                        row["currency"],
                        row["equity"],
                        row["cash"],
                        row["buying_power"],
                        row["portfolio_value"],
                        row["last_equity"],
                        row["position_market_value"],
                        row["open_position_unrealized_pl"],
                        row["raw_json"],
                    )
                    for row in rows
                ],
            )

    def _record_broker_account_snapshots_postgres(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO broker_account_snapshots (
                        tick_id, broker_id, captured_at, account_status, currency,
                        equity, cash, buying_power, portfolio_value, last_equity,
                        position_market_value, open_position_unrealized_pl, raw_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(tick_id, broker_id) DO UPDATE SET
                        captured_at = EXCLUDED.captured_at,
                        account_status = EXCLUDED.account_status,
                        currency = EXCLUDED.currency,
                        equity = EXCLUDED.equity,
                        cash = EXCLUDED.cash,
                        buying_power = EXCLUDED.buying_power,
                        portfolio_value = EXCLUDED.portfolio_value,
                        last_equity = EXCLUDED.last_equity,
                        position_market_value = EXCLUDED.position_market_value,
                        open_position_unrealized_pl = EXCLUDED.open_position_unrealized_pl,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            row["tick_id"],
                            row["broker_id"],
                            row["captured_at"],
                            row["account_status"],
                            row["currency"],
                            row["equity"],
                            row["cash"],
                            row["buying_power"],
                            row["portfolio_value"],
                            row["last_equity"],
                            row["position_market_value"],
                            row["open_position_unrealized_pl"],
                            row["raw_json"],
                        )
                        for row in rows
                    ],
                )

    def _record_paper_trade_orders_sqlite(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO paper_trade_orders (
                    order_id, tick_id, captured_at, submitted_at, updated_at,
                    environment, mode, source_environment, broker_id, data_provider,
                    execution_provider, canonical_instrument_id, venue, venue_symbol,
                    client_order_id, proposal_id, strategy_id, strategy_family,
                    profile_id, source, symbol, asset_class, side, order_type,
                    time_in_force, order_class, status, is_open, qty, filled_qty,
                    notional_usd, filled_avg_price, limit_price, stop_price,
                    take_profit_price, stop_loss_price, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    tick_id = excluded.tick_id,
                    captured_at = excluded.captured_at,
                    submitted_at = COALESCE(excluded.submitted_at, paper_trade_orders.submitted_at),
                    updated_at = COALESCE(excluded.updated_at, paper_trade_orders.updated_at),
                    environment = COALESCE(NULLIF(excluded.environment, ''), paper_trade_orders.environment),
                    mode = COALESCE(NULLIF(excluded.mode, ''), paper_trade_orders.mode),
                    source_environment = COALESCE(NULLIF(excluded.source_environment, ''), paper_trade_orders.source_environment),
                    broker_id = COALESCE(NULLIF(excluded.broker_id, ''), paper_trade_orders.broker_id),
                    data_provider = COALESCE(NULLIF(excluded.data_provider, ''), paper_trade_orders.data_provider),
                    execution_provider = COALESCE(NULLIF(excluded.execution_provider, ''), paper_trade_orders.execution_provider),
                    canonical_instrument_id = COALESCE(NULLIF(excluded.canonical_instrument_id, ''), paper_trade_orders.canonical_instrument_id),
                    venue = COALESCE(NULLIF(excluded.venue, ''), paper_trade_orders.venue),
                    venue_symbol = COALESCE(NULLIF(excluded.venue_symbol, ''), paper_trade_orders.venue_symbol),
                    client_order_id = CASE
                        WHEN excluded.client_order_id <> '' THEN excluded.client_order_id
                        ELSE paper_trade_orders.client_order_id
                    END,
                    proposal_id = CASE
                        WHEN excluded.proposal_id <> '' THEN excluded.proposal_id
                        ELSE paper_trade_orders.proposal_id
                    END,
                    strategy_id = CASE
                        WHEN excluded.strategy_id <> '' THEN excluded.strategy_id
                        ELSE paper_trade_orders.strategy_id
                    END,
                    strategy_family = CASE
                        WHEN excluded.strategy_family <> '' THEN excluded.strategy_family
                        ELSE paper_trade_orders.strategy_family
                    END,
                    profile_id = CASE
                        WHEN excluded.profile_id <> '' THEN excluded.profile_id
                        ELSE paper_trade_orders.profile_id
                    END,
                    source = CASE
                        WHEN excluded.source <> '' THEN excluded.source
                        ELSE paper_trade_orders.source
                    END,
                    symbol = excluded.symbol,
                    asset_class = CASE
                        WHEN excluded.asset_class <> '' THEN excluded.asset_class
                        ELSE paper_trade_orders.asset_class
                    END,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    time_in_force = excluded.time_in_force,
                    order_class = excluded.order_class,
                    status = excluded.status,
                    is_open = excluded.is_open,
                    qty = COALESCE(excluded.qty, paper_trade_orders.qty),
                    filled_qty = COALESCE(excluded.filled_qty, paper_trade_orders.filled_qty),
                    notional_usd = COALESCE(excluded.notional_usd, paper_trade_orders.notional_usd),
                    filled_avg_price = COALESCE(excluded.filled_avg_price, paper_trade_orders.filled_avg_price),
                    limit_price = COALESCE(excluded.limit_price, paper_trade_orders.limit_price),
                    stop_price = COALESCE(excluded.stop_price, paper_trade_orders.stop_price),
                    take_profit_price = COALESCE(excluded.take_profit_price, paper_trade_orders.take_profit_price),
                    stop_loss_price = COALESCE(excluded.stop_loss_price, paper_trade_orders.stop_loss_price),
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        row["order_id"],
                        row["tick_id"],
                        row["captured_at"],
                        row["submitted_at"],
                        row["updated_at"],
                        row["environment"],
                        row["mode"],
                        row["source_environment"],
                        row["broker_id"],
                        row["data_provider"],
                        row["execution_provider"],
                        row["canonical_instrument_id"],
                        row["venue"],
                        row["venue_symbol"],
                        row["client_order_id"],
                        row["proposal_id"],
                        row["strategy_id"],
                        row["strategy_family"],
                        row["profile_id"],
                        row["source"],
                        row["symbol"],
                        row["asset_class"],
                        row["side"],
                        row["order_type"],
                        row["time_in_force"],
                        row["order_class"],
                        row["status"],
                        row["is_open"],
                        row["qty"],
                        row["filled_qty"],
                        row["notional_usd"],
                        row["filled_avg_price"],
                        row["limit_price"],
                        row["stop_price"],
                        row["take_profit_price"],
                        row["stop_loss_price"],
                        row["raw_json"],
                    )
                    for row in rows
                ],
            )

    def _record_paper_trade_orders_postgres(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO paper_trade_orders (
                        order_id, tick_id, captured_at, submitted_at, updated_at,
                        environment, mode, source_environment, broker_id, data_provider,
                        execution_provider, canonical_instrument_id, venue, venue_symbol,
                        client_order_id, proposal_id, strategy_id, strategy_family,
                        profile_id, source, symbol, asset_class, side, order_type,
                        time_in_force, order_class, status, is_open, qty, filled_qty,
                        notional_usd, filled_avg_price, limit_price, stop_price,
                        take_profit_price, stop_loss_price, raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(order_id) DO UPDATE SET
                        tick_id = EXCLUDED.tick_id,
                        captured_at = EXCLUDED.captured_at,
                        submitted_at = COALESCE(EXCLUDED.submitted_at, paper_trade_orders.submitted_at),
                        updated_at = COALESCE(EXCLUDED.updated_at, paper_trade_orders.updated_at),
                        environment = COALESCE(NULLIF(EXCLUDED.environment, ''), paper_trade_orders.environment),
                        mode = COALESCE(NULLIF(EXCLUDED.mode, ''), paper_trade_orders.mode),
                        source_environment = COALESCE(NULLIF(EXCLUDED.source_environment, ''), paper_trade_orders.source_environment),
                        broker_id = COALESCE(NULLIF(EXCLUDED.broker_id, ''), paper_trade_orders.broker_id),
                        data_provider = COALESCE(NULLIF(EXCLUDED.data_provider, ''), paper_trade_orders.data_provider),
                        execution_provider = COALESCE(NULLIF(EXCLUDED.execution_provider, ''), paper_trade_orders.execution_provider),
                        canonical_instrument_id = COALESCE(NULLIF(EXCLUDED.canonical_instrument_id, ''), paper_trade_orders.canonical_instrument_id),
                        venue = COALESCE(NULLIF(EXCLUDED.venue, ''), paper_trade_orders.venue),
                        venue_symbol = COALESCE(NULLIF(EXCLUDED.venue_symbol, ''), paper_trade_orders.venue_symbol),
                        client_order_id = COALESCE(NULLIF(EXCLUDED.client_order_id, ''), paper_trade_orders.client_order_id),
                        proposal_id = COALESCE(NULLIF(EXCLUDED.proposal_id, ''), paper_trade_orders.proposal_id),
                        strategy_id = COALESCE(NULLIF(EXCLUDED.strategy_id, ''), paper_trade_orders.strategy_id),
                        strategy_family = COALESCE(NULLIF(EXCLUDED.strategy_family, ''), paper_trade_orders.strategy_family),
                        profile_id = COALESCE(NULLIF(EXCLUDED.profile_id, ''), paper_trade_orders.profile_id),
                        source = COALESCE(NULLIF(EXCLUDED.source, ''), paper_trade_orders.source),
                        symbol = EXCLUDED.symbol,
                        asset_class = COALESCE(NULLIF(EXCLUDED.asset_class, ''), paper_trade_orders.asset_class),
                        side = EXCLUDED.side,
                        order_type = EXCLUDED.order_type,
                        time_in_force = EXCLUDED.time_in_force,
                        order_class = EXCLUDED.order_class,
                        status = EXCLUDED.status,
                        is_open = EXCLUDED.is_open,
                        qty = COALESCE(EXCLUDED.qty, paper_trade_orders.qty),
                        filled_qty = COALESCE(EXCLUDED.filled_qty, paper_trade_orders.filled_qty),
                        notional_usd = COALESCE(EXCLUDED.notional_usd, paper_trade_orders.notional_usd),
                        filled_avg_price = COALESCE(EXCLUDED.filled_avg_price, paper_trade_orders.filled_avg_price),
                        limit_price = COALESCE(EXCLUDED.limit_price, paper_trade_orders.limit_price),
                        stop_price = COALESCE(EXCLUDED.stop_price, paper_trade_orders.stop_price),
                        take_profit_price = COALESCE(EXCLUDED.take_profit_price, paper_trade_orders.take_profit_price),
                        stop_loss_price = COALESCE(EXCLUDED.stop_loss_price, paper_trade_orders.stop_loss_price),
                        raw_json = COALESCE(paper_trade_orders.raw_json, '{}'::jsonb) || EXCLUDED.raw_json
                    """,
                    [
                        (
                            row["order_id"],
                            row["tick_id"],
                            row["captured_at"],
                            row["submitted_at"],
                            row["updated_at"],
                            row["environment"],
                            row["mode"],
                            row["source_environment"],
                            row["broker_id"],
                            row["data_provider"],
                            row["execution_provider"],
                            row["canonical_instrument_id"],
                            row["venue"],
                            row["venue_symbol"],
                            row["client_order_id"],
                            row["proposal_id"],
                            row["strategy_id"],
                            row["strategy_family"],
                            row["profile_id"],
                            row["source"],
                            row["symbol"],
                            row["asset_class"],
                            row["side"],
                            row["order_type"],
                            row["time_in_force"],
                            row["order_class"],
                            row["status"],
                            row["is_open"],
                            row["qty"],
                            row["filled_qty"],
                            row["notional_usd"],
                            row["filled_avg_price"],
                            row["limit_price"],
                            row["stop_price"],
                            row["take_profit_price"],
                            row["stop_loss_price"],
                            row["raw_json"],
                        )
                        for row in rows
                    ],
                )

    def _record_shadow_trade_proposals_sqlite(
        self,
        *,
        proposals: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO shadow_trade_proposals (
                    proposal_id, tick_id, proposed_at, strategy_id, strategy_family, profile_id,
                    environment, mode, source_environment, data_provider, execution_provider,
                    canonical_instrument_id, venue, venue_symbol,
                    source, symbol, asset_class, direction, status, action_bias, opportunity_score,
                    signal_score, signal_confidence, confidence,
                    discovery_score, entry_price, entry_price_gbp, stop_loss_price,
                    stop_loss_price_gbp, target_price, target_price_gbp, risk_pct,
                    target_return_pct, holding_window_code, holding_window_minutes,
                    thesis, risks_json, rationale, note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    environment = excluded.environment,
                    mode = excluded.mode,
                    source_environment = excluded.source_environment,
                    data_provider = excluded.data_provider,
                    execution_provider = excluded.execution_provider,
                    canonical_instrument_id = excluded.canonical_instrument_id,
                    venue = excluded.venue,
                    venue_symbol = excluded.venue_symbol,
                    strategy_id = excluded.strategy_id,
                    strategy_family = excluded.strategy_family,
                    profile_id = excluded.profile_id,
                    status = excluded.status,
                    action_bias = excluded.action_bias,
                    opportunity_score = excluded.opportunity_score,
                    signal_score = excluded.signal_score,
                    signal_confidence = excluded.signal_confidence,
                    confidence = excluded.confidence,
                    discovery_score = excluded.discovery_score,
                    entry_price = excluded.entry_price,
                    entry_price_gbp = excluded.entry_price_gbp,
                    stop_loss_price = excluded.stop_loss_price,
                    stop_loss_price_gbp = excluded.stop_loss_price_gbp,
                    target_price = excluded.target_price,
                    target_price_gbp = excluded.target_price_gbp,
                    risk_pct = excluded.risk_pct,
                    target_return_pct = excluded.target_return_pct,
                    holding_window_code = excluded.holding_window_code,
                    holding_window_minutes = excluded.holding_window_minutes,
                    thesis = excluded.thesis,
                    risks_json = excluded.risks_json,
                    rationale = excluded.rationale,
                    note = excluded.note,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        item["proposal_id"],
                        item["tick_id"],
                        item["proposed_at"],
                        item.get("strategy_id", ""),
                        item.get("strategy_family", ""),
                        item.get("profile_id", ""),
                        item.get("environment", "paper"),
                        item.get("mode", "paper"),
                        item.get("source_environment", "shadow"),
                        item.get("data_provider", item.get("source", "alpaca")),
                        item.get("execution_provider", "shadow"),
                        item.get("canonical_instrument_id", ""),
                        item.get("venue", ""),
                        item.get("venue_symbol", item.get("symbol", "")),
                        item["source"],
                        item["symbol"],
                        item["asset_class"],
                        item.get("direction", "long"),
                        item.get("status", "active"),
                        item.get("action_bias", "watch"),
                        item.get("opportunity_score", 0),
                        item.get("signal_score", item.get("opportunity_score", 0)),
                        item.get("signal_confidence", item.get("confidence", 0)),
                        item.get("confidence", 0),
                        item.get("discovery_score", 0),
                        item["entry_price"],
                        item.get("entry_price_gbp"),
                        item["stop_loss_price"],
                        item.get("stop_loss_price_gbp"),
                        item["target_price"],
                        item.get("target_price_gbp"),
                        item.get("risk_pct", 0),
                        item.get("target_return_pct", 0),
                        item["holding_window_code"],
                        item["holding_window_minutes"],
                        item.get("thesis", ""),
                        self._to_json(item.get("risks", [])),
                        item.get("rationale", ""),
                        item.get("note", ""),
                        self._to_json(item),
                    )
                    for item in proposals
                ],
            )
            checkpoint_rows = []
            for item in proposals:
                for checkpoint in item.get("checkpoint_windows", []):
                    checkpoint_rows.append(
                        (
                            item["proposal_id"],
                            checkpoint["checkpoint_code"],
                            item.get("environment", "paper"),
                            item.get("mode", "paper"),
                            item.get("source_environment", "shadow"),
                            item.get("data_provider", item.get("source", "alpaca")),
                            item.get("execution_provider", "shadow"),
                            item.get("canonical_instrument_id", ""),
                            item.get("venue", ""),
                            item.get("venue_symbol", item.get("symbol", "")),
                            checkpoint["checkpoint_minutes"],
                            checkpoint["due_at"],
                            "pending",
                        )
                    )
            if checkpoint_rows:
                connection.executemany(
                    """
                    INSERT INTO shadow_trade_outcomes (
                        proposal_id, checkpoint_code, environment, mode,
                        source_environment, data_provider, execution_provider,
                        canonical_instrument_id, venue, venue_symbol,
                        checkpoint_minutes, due_at, outcome_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id, checkpoint_code) DO NOTHING
                    """,
                    checkpoint_rows,
                )

    def _record_shadow_trade_proposals_postgres(
        self,
        *,
        proposals: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                INSERT INTO shadow_trade_proposals (
                        proposal_id, tick_id, proposed_at, strategy_id, strategy_family, profile_id,
                        environment, mode, source_environment, data_provider, execution_provider,
                        canonical_instrument_id, venue, venue_symbol,
                        source, symbol, asset_class, direction, status, action_bias, opportunity_score,
                        signal_score, signal_confidence, confidence,
                        discovery_score, entry_price, entry_price_gbp, stop_loss_price,
                        stop_loss_price_gbp, target_price, target_price_gbp, risk_pct,
                        target_return_pct, holding_window_code, holding_window_minutes,
                        thesis, risks_json, rationale, note, raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        environment = EXCLUDED.environment,
                        mode = EXCLUDED.mode,
                        source_environment = EXCLUDED.source_environment,
                        data_provider = EXCLUDED.data_provider,
                        execution_provider = EXCLUDED.execution_provider,
                        canonical_instrument_id = EXCLUDED.canonical_instrument_id,
                        venue = EXCLUDED.venue,
                        venue_symbol = EXCLUDED.venue_symbol,
                        strategy_id = EXCLUDED.strategy_id,
                        strategy_family = EXCLUDED.strategy_family,
                        profile_id = EXCLUDED.profile_id,
                        status = EXCLUDED.status,
                        action_bias = EXCLUDED.action_bias,
                        opportunity_score = EXCLUDED.opportunity_score,
                        signal_score = EXCLUDED.signal_score,
                        signal_confidence = EXCLUDED.signal_confidence,
                        confidence = EXCLUDED.confidence,
                        discovery_score = EXCLUDED.discovery_score,
                        entry_price = EXCLUDED.entry_price,
                        entry_price_gbp = EXCLUDED.entry_price_gbp,
                        stop_loss_price = EXCLUDED.stop_loss_price,
                        stop_loss_price_gbp = EXCLUDED.stop_loss_price_gbp,
                        target_price = EXCLUDED.target_price,
                        target_price_gbp = EXCLUDED.target_price_gbp,
                        risk_pct = EXCLUDED.risk_pct,
                        target_return_pct = EXCLUDED.target_return_pct,
                        holding_window_code = EXCLUDED.holding_window_code,
                        holding_window_minutes = EXCLUDED.holding_window_minutes,
                        thesis = EXCLUDED.thesis,
                        risks_json = EXCLUDED.risks_json,
                        rationale = EXCLUDED.rationale,
                        note = EXCLUDED.note,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            item["proposal_id"],
                            item["tick_id"],
                            item["proposed_at"],
                            item.get("strategy_id", ""),
                            item.get("strategy_family", ""),
                            item.get("profile_id", ""),
                            item.get("environment", "paper"),
                            item.get("mode", "paper"),
                            item.get("source_environment", "shadow"),
                            item.get("data_provider", item.get("source", "alpaca")),
                            item.get("execution_provider", "shadow"),
                            item.get("canonical_instrument_id", ""),
                            item.get("venue", ""),
                            item.get("venue_symbol", item.get("symbol", "")),
                            item["source"],
                            item["symbol"],
                            item["asset_class"],
                            item.get("direction", "long"),
                            item.get("status", "active"),
                            item.get("action_bias", "watch"),
                            item.get("opportunity_score", 0),
                            item.get("signal_score", item.get("opportunity_score", 0)),
                            item.get("signal_confidence", item.get("confidence", 0)),
                            item.get("confidence", 0),
                            item.get("discovery_score", 0),
                            item["entry_price"],
                            item.get("entry_price_gbp"),
                            item["stop_loss_price"],
                            item.get("stop_loss_price_gbp"),
                            item["target_price"],
                            item.get("target_price_gbp"),
                            item.get("risk_pct", 0),
                            item.get("target_return_pct", 0),
                            item["holding_window_code"],
                            item["holding_window_minutes"],
                            item.get("thesis", ""),
                            self._to_json(item.get("risks", [])),
                            item.get("rationale", ""),
                            item.get("note", ""),
                            self._to_json(item),
                        )
                        for item in proposals
                    ],
                )
                checkpoint_rows = []
                for item in proposals:
                    for checkpoint in item.get("checkpoint_windows", []):
                        checkpoint_rows.append(
                            (
                            item["proposal_id"],
                            checkpoint["checkpoint_code"],
                            item.get("environment", "paper"),
                            item.get("mode", "paper"),
                            item.get("source_environment", "shadow"),
                            item.get("data_provider", item.get("source", "alpaca")),
                            item.get("execution_provider", "shadow"),
                            item.get("canonical_instrument_id", ""),
                            item.get("venue", ""),
                            item.get("venue_symbol", item.get("symbol", "")),
                            checkpoint["checkpoint_minutes"],
                            checkpoint["due_at"],
                            "pending",
                            )
                        )
                if checkpoint_rows:
                    cursor.executemany(
                        """
                        INSERT INTO shadow_trade_outcomes (
                            proposal_id, checkpoint_code, environment, mode,
                            source_environment, data_provider, execution_provider,
                            canonical_instrument_id, venue, venue_symbol,
                            checkpoint_minutes, due_at, outcome_status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(proposal_id, checkpoint_code) DO NOTHING
                        """,
                        checkpoint_rows,
                    )

    def _record_shadow_trade_outcomes_sqlite(
        self,
        *,
        outcomes: list[dict[str, Any]],
    ) -> None:
        proposal_ids = sorted({str(item["proposal_id"]) for item in outcomes})
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO shadow_trade_outcomes (
                    proposal_id, checkpoint_code, checkpoint_minutes, due_at, evaluated_at,
                    environment, mode, source_environment, data_provider, execution_provider,
                    canonical_instrument_id, venue, venue_symbol,
                    outcome_status, exit_price, exit_price_gbp, realized_return_pct,
                    max_favorable_excursion_pct, max_adverse_excursion_pct, fitness_score,
                    bars_observed, notes, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id, checkpoint_code) DO UPDATE SET
                    checkpoint_minutes = excluded.checkpoint_minutes,
                    due_at = excluded.due_at,
                    evaluated_at = excluded.evaluated_at,
                    environment = excluded.environment,
                    mode = excluded.mode,
                    source_environment = excluded.source_environment,
                    data_provider = excluded.data_provider,
                    execution_provider = excluded.execution_provider,
                    canonical_instrument_id = excluded.canonical_instrument_id,
                    venue = excluded.venue,
                    venue_symbol = excluded.venue_symbol,
                    outcome_status = excluded.outcome_status,
                    exit_price = excluded.exit_price,
                    exit_price_gbp = excluded.exit_price_gbp,
                    realized_return_pct = excluded.realized_return_pct,
                    max_favorable_excursion_pct = excluded.max_favorable_excursion_pct,
                    max_adverse_excursion_pct = excluded.max_adverse_excursion_pct,
                    fitness_score = excluded.fitness_score,
                    bars_observed = excluded.bars_observed,
                    notes = excluded.notes,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        item["proposal_id"],
                        item["checkpoint_code"],
                        item.get("checkpoint_minutes", 0),
                        item["due_at"],
                        item.get("evaluated_at"),
                        item.get("environment", "paper"),
                        item.get("mode", "paper"),
                        item.get("source_environment", "shadow"),
                        item.get("data_provider", "alpaca"),
                        item.get("execution_provider", "shadow"),
                        item.get("canonical_instrument_id", ""),
                        item.get("venue", ""),
                        item.get("venue_symbol", item.get("symbol", "")),
                        item.get("outcome_status", "pending"),
                        item.get("exit_price"),
                        item.get("exit_price_gbp"),
                        item.get("realized_return_pct"),
                        item.get("max_favorable_excursion_pct"),
                        item.get("max_adverse_excursion_pct"),
                        item.get("fitness_score"),
                        item.get("bars_observed", 0),
                        item.get("notes", ""),
                        self._to_json(item),
                    )
                    for item in outcomes
                ],
            )
            if proposal_ids:
                placeholders = ",".join("?" for _ in proposal_ids)
                connection.execute(
                    f"""
                    UPDATE shadow_trade_proposals
                    SET status = 'completed'
                    WHERE proposal_id IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1
                          FROM shadow_trade_outcomes
                          WHERE shadow_trade_outcomes.proposal_id = shadow_trade_proposals.proposal_id
                            AND shadow_trade_outcomes.evaluated_at IS NULL
                      )
                    """,
                    tuple(proposal_ids),
                )

    def _record_shadow_trade_outcomes_postgres(
        self,
        *,
        outcomes: list[dict[str, Any]],
    ) -> None:
        proposal_ids = sorted({str(item["proposal_id"]) for item in outcomes})
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO shadow_trade_outcomes (
                        proposal_id, checkpoint_code, checkpoint_minutes, due_at, evaluated_at,
                        environment, mode, source_environment, data_provider, execution_provider,
                        canonical_instrument_id, venue, venue_symbol,
                        outcome_status, exit_price, exit_price_gbp, realized_return_pct,
                        max_favorable_excursion_pct, max_adverse_excursion_pct, fitness_score,
                        bars_observed, notes, raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(proposal_id, checkpoint_code) DO UPDATE SET
                        checkpoint_minutes = EXCLUDED.checkpoint_minutes,
                        due_at = EXCLUDED.due_at,
                        evaluated_at = EXCLUDED.evaluated_at,
                        environment = EXCLUDED.environment,
                        mode = EXCLUDED.mode,
                        source_environment = EXCLUDED.source_environment,
                        data_provider = EXCLUDED.data_provider,
                        execution_provider = EXCLUDED.execution_provider,
                        canonical_instrument_id = EXCLUDED.canonical_instrument_id,
                        venue = EXCLUDED.venue,
                        venue_symbol = EXCLUDED.venue_symbol,
                        outcome_status = EXCLUDED.outcome_status,
                        exit_price = EXCLUDED.exit_price,
                        exit_price_gbp = EXCLUDED.exit_price_gbp,
                        realized_return_pct = EXCLUDED.realized_return_pct,
                        max_favorable_excursion_pct = EXCLUDED.max_favorable_excursion_pct,
                        max_adverse_excursion_pct = EXCLUDED.max_adverse_excursion_pct,
                        fitness_score = EXCLUDED.fitness_score,
                        bars_observed = EXCLUDED.bars_observed,
                        notes = EXCLUDED.notes,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            item["proposal_id"],
                            item["checkpoint_code"],
                            item.get("checkpoint_minutes", 0),
                            item["due_at"],
                            item.get("evaluated_at"),
                            item.get("environment", "paper"),
                            item.get("mode", "paper"),
                            item.get("source_environment", "shadow"),
                            item.get("data_provider", "alpaca"),
                            item.get("execution_provider", "shadow"),
                            item.get("canonical_instrument_id", ""),
                            item.get("venue", ""),
                            item.get("venue_symbol", item.get("symbol", "")),
                            item.get("outcome_status", "pending"),
                            item.get("exit_price"),
                            item.get("exit_price_gbp"),
                            item.get("realized_return_pct"),
                            item.get("max_favorable_excursion_pct"),
                            item.get("max_adverse_excursion_pct"),
                            item.get("fitness_score"),
                            item.get("bars_observed", 0),
                            item.get("notes", ""),
                            self._to_json(item),
                        )
                        for item in outcomes
                    ],
                )
                if proposal_ids:
                    cursor.execute(
                        """
                        UPDATE shadow_trade_proposals
                        SET status = 'completed'
                        WHERE proposal_id = ANY(%s)
                          AND NOT EXISTS (
                              SELECT 1
                              FROM shadow_trade_outcomes
                              WHERE shadow_trade_outcomes.proposal_id = shadow_trade_proposals.proposal_id
                                AND shadow_trade_outcomes.evaluated_at IS NULL
                          )
                        """,
                        (proposal_ids,),
                    )

    def _record_strategy_fitness_snapshots_sqlite(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_sqlite() as connection:
            connection.executemany(
                """
                INSERT INTO strategy_fitness_snapshots (
                    tick_id, captured_at, environment, mode, source_environment,
                    broker_id, data_provider, execution_provider,
                    strategy_id, strategy_family, profile_id, asset_class,
                    checkpoint_code, lookback_days, fitness_rank,
                    evaluated_proposals, checkpoints_evaluated, win_count, loss_count,
                    target_hit_count, stop_hit_count, time_exit_count, ambiguous_count,
                    win_rate, loss_rate, target_hit_rate, stop_hit_rate, time_exit_rate,
                    ambiguous_rate, avg_fitness_score, avg_realized_return_pct,
                    avg_max_favorable_excursion_pct, avg_max_adverse_excursion_pct,
                    avg_signal_score, avg_signal_confidence, avg_discovery_score,
                    sample_weight, composite_fitness_score, first_proposed_at,
                    last_evaluated_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tick_id, strategy_id, asset_class, checkpoint_code) DO UPDATE SET
                    captured_at = excluded.captured_at,
                    environment = excluded.environment,
                    mode = excluded.mode,
                    source_environment = excluded.source_environment,
                    broker_id = excluded.broker_id,
                    data_provider = excluded.data_provider,
                    execution_provider = excluded.execution_provider,
                    strategy_family = excluded.strategy_family,
                    profile_id = excluded.profile_id,
                    lookback_days = excluded.lookback_days,
                    fitness_rank = excluded.fitness_rank,
                    evaluated_proposals = excluded.evaluated_proposals,
                    checkpoints_evaluated = excluded.checkpoints_evaluated,
                    win_count = excluded.win_count,
                    loss_count = excluded.loss_count,
                    target_hit_count = excluded.target_hit_count,
                    stop_hit_count = excluded.stop_hit_count,
                    time_exit_count = excluded.time_exit_count,
                    ambiguous_count = excluded.ambiguous_count,
                    win_rate = excluded.win_rate,
                    loss_rate = excluded.loss_rate,
                    target_hit_rate = excluded.target_hit_rate,
                    stop_hit_rate = excluded.stop_hit_rate,
                    time_exit_rate = excluded.time_exit_rate,
                    ambiguous_rate = excluded.ambiguous_rate,
                    avg_fitness_score = excluded.avg_fitness_score,
                    avg_realized_return_pct = excluded.avg_realized_return_pct,
                    avg_max_favorable_excursion_pct = excluded.avg_max_favorable_excursion_pct,
                    avg_max_adverse_excursion_pct = excluded.avg_max_adverse_excursion_pct,
                    avg_signal_score = excluded.avg_signal_score,
                    avg_signal_confidence = excluded.avg_signal_confidence,
                    avg_discovery_score = excluded.avg_discovery_score,
                    sample_weight = excluded.sample_weight,
                    composite_fitness_score = excluded.composite_fitness_score,
                    first_proposed_at = excluded.first_proposed_at,
                    last_evaluated_at = excluded.last_evaluated_at,
                    raw_json = excluded.raw_json
                """,
                [
                    (
                        row["tick_id"],
                        row["captured_at"],
                        row["environment"],
                        row["mode"],
                        row["source_environment"],
                        row["broker_id"],
                        row["data_provider"],
                        row["execution_provider"],
                        row["strategy_id"],
                        row["strategy_family"],
                        row["profile_id"],
                        row["asset_class"],
                        row["checkpoint_code"],
                        row["lookback_days"],
                        row["fitness_rank"],
                        row["evaluated_proposals"],
                        row["checkpoints_evaluated"],
                        row["win_count"],
                        row["loss_count"],
                        row["target_hit_count"],
                        row["stop_hit_count"],
                        row["time_exit_count"],
                        row["ambiguous_count"],
                        row["win_rate"],
                        row["loss_rate"],
                        row["target_hit_rate"],
                        row["stop_hit_rate"],
                        row["time_exit_rate"],
                        row["ambiguous_rate"],
                        row["avg_fitness_score"],
                        row["avg_realized_return_pct"],
                        row["avg_max_favorable_excursion_pct"],
                        row["avg_max_adverse_excursion_pct"],
                        row["avg_signal_score"],
                        row["avg_signal_confidence"],
                        row["avg_discovery_score"],
                        row["sample_weight"],
                        row["composite_fitness_score"],
                        row["first_proposed_at"],
                        row["last_evaluated_at"],
                        row["raw_json"],
                    )
                    for row in rows
                ],
            )

    def _record_strategy_fitness_snapshots_postgres(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        with self._connect_postgres() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO strategy_fitness_snapshots (
                        tick_id, captured_at, environment, mode, source_environment,
                        broker_id, data_provider, execution_provider,
                        strategy_id, strategy_family, profile_id, asset_class,
                        checkpoint_code, lookback_days, fitness_rank,
                        evaluated_proposals, checkpoints_evaluated, win_count, loss_count,
                        target_hit_count, stop_hit_count, time_exit_count, ambiguous_count,
                        win_rate, loss_rate, target_hit_rate, stop_hit_rate, time_exit_rate,
                        ambiguous_rate, avg_fitness_score, avg_realized_return_pct,
                        avg_max_favorable_excursion_pct, avg_max_adverse_excursion_pct,
                        avg_signal_score, avg_signal_confidence, avg_discovery_score,
                        sample_weight, composite_fitness_score, first_proposed_at,
                        last_evaluated_at, raw_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT(tick_id, strategy_id, asset_class, checkpoint_code) DO UPDATE SET
                        captured_at = EXCLUDED.captured_at,
                        environment = EXCLUDED.environment,
                        mode = EXCLUDED.mode,
                        source_environment = EXCLUDED.source_environment,
                        broker_id = EXCLUDED.broker_id,
                        data_provider = EXCLUDED.data_provider,
                        execution_provider = EXCLUDED.execution_provider,
                        strategy_family = EXCLUDED.strategy_family,
                        profile_id = EXCLUDED.profile_id,
                        lookback_days = EXCLUDED.lookback_days,
                        fitness_rank = EXCLUDED.fitness_rank,
                        evaluated_proposals = EXCLUDED.evaluated_proposals,
                        checkpoints_evaluated = EXCLUDED.checkpoints_evaluated,
                        win_count = EXCLUDED.win_count,
                        loss_count = EXCLUDED.loss_count,
                        target_hit_count = EXCLUDED.target_hit_count,
                        stop_hit_count = EXCLUDED.stop_hit_count,
                        time_exit_count = EXCLUDED.time_exit_count,
                        ambiguous_count = EXCLUDED.ambiguous_count,
                        win_rate = EXCLUDED.win_rate,
                        loss_rate = EXCLUDED.loss_rate,
                        target_hit_rate = EXCLUDED.target_hit_rate,
                        stop_hit_rate = EXCLUDED.stop_hit_rate,
                        time_exit_rate = EXCLUDED.time_exit_rate,
                        ambiguous_rate = EXCLUDED.ambiguous_rate,
                        avg_fitness_score = EXCLUDED.avg_fitness_score,
                        avg_realized_return_pct = EXCLUDED.avg_realized_return_pct,
                        avg_max_favorable_excursion_pct = EXCLUDED.avg_max_favorable_excursion_pct,
                        avg_max_adverse_excursion_pct = EXCLUDED.avg_max_adverse_excursion_pct,
                        avg_signal_score = EXCLUDED.avg_signal_score,
                        avg_signal_confidence = EXCLUDED.avg_signal_confidence,
                        avg_discovery_score = EXCLUDED.avg_discovery_score,
                        sample_weight = EXCLUDED.sample_weight,
                        composite_fitness_score = EXCLUDED.composite_fitness_score,
                        first_proposed_at = EXCLUDED.first_proposed_at,
                        last_evaluated_at = EXCLUDED.last_evaluated_at,
                        raw_json = EXCLUDED.raw_json
                    """,
                    [
                        (
                            row["tick_id"],
                            row["captured_at"],
                            row["environment"],
                            row["mode"],
                            row["source_environment"],
                            row["broker_id"],
                            row["data_provider"],
                            row["execution_provider"],
                            row["strategy_id"],
                            row["strategy_family"],
                            row["profile_id"],
                            row["asset_class"],
                            row["checkpoint_code"],
                            row["lookback_days"],
                            row["fitness_rank"],
                            row["evaluated_proposals"],
                            row["checkpoints_evaluated"],
                            row["win_count"],
                            row["loss_count"],
                            row["target_hit_count"],
                            row["stop_hit_count"],
                            row["time_exit_count"],
                            row["ambiguous_count"],
                            row["win_rate"],
                            row["loss_rate"],
                            row["target_hit_rate"],
                            row["stop_hit_rate"],
                            row["time_exit_rate"],
                            row["ambiguous_rate"],
                            row["avg_fitness_score"],
                            row["avg_realized_return_pct"],
                            row["avg_max_favorable_excursion_pct"],
                            row["avg_max_adverse_excursion_pct"],
                            row["avg_signal_score"],
                            row["avg_signal_confidence"],
                            row["avg_discovery_score"],
                            row["sample_weight"],
                            row["composite_fitness_score"],
                            row["first_proposed_at"],
                            row["last_evaluated_at"],
                            row["raw_json"],
                        )
                        for row in rows
                    ],
                )

    def _list_recent_shadow_proposal_keys_sqlite(
        self,
        *,
        since: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT strategy_id, source, symbol
                FROM shadow_trade_proposals
                WHERE proposed_at >= ?
                """,
                (since.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_shadow_proposal_keys_postgres(
        self,
        *,
        since: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT strategy_id, source, symbol
                    FROM shadow_trade_proposals
                    WHERE proposed_at >= %s
                    """,
                    (since,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_due_shadow_trade_outcomes_sqlite(
        self,
        *,
        as_of: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT o.proposal_id, o.checkpoint_code, o.checkpoint_minutes, o.due_at,
                       o.evaluated_at, p.proposed_at, p.source, p.symbol, p.asset_class,
                       p.environment, p.mode, p.source_environment, p.data_provider,
                       p.execution_provider, p.canonical_instrument_id, p.venue,
                       p.venue_symbol,
                       p.entry_price, p.entry_price_gbp, p.stop_loss_price, p.target_price,
                       p.risk_pct, p.holding_window_code, p.holding_window_minutes,
                       p.raw_json
                FROM shadow_trade_outcomes o
                JOIN shadow_trade_proposals p ON p.proposal_id = o.proposal_id
                WHERE o.evaluated_at IS NULL
                  AND o.due_at <= ?
                ORDER BY o.due_at ASC, o.proposal_id ASC
                LIMIT ?
                """,
                (as_of.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_due_shadow_trade_outcomes_postgres(
        self,
        *,
        as_of: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT o.proposal_id, o.checkpoint_code, o.checkpoint_minutes, o.due_at,
                           o.evaluated_at, p.proposed_at, p.source, p.symbol, p.asset_class,
                           p.environment, p.mode, p.source_environment, p.data_provider,
                           p.execution_provider, p.canonical_instrument_id, p.venue,
                           p.venue_symbol,
                           p.entry_price, p.entry_price_gbp, p.stop_loss_price, p.target_price,
                           p.risk_pct, p.holding_window_code, p.holding_window_minutes,
                           p.raw_json
                    FROM shadow_trade_outcomes o
                    JOIN shadow_trade_proposals p ON p.proposal_id = o.proposal_id
                    WHERE o.evaluated_at IS NULL
                      AND o.due_at <= %s
                    ORDER BY o.due_at ASC, o.proposal_id ASC
                    LIMIT %s
                    """,
                    (as_of, limit),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_strategy_fitness_rows_sqlite(
        self,
        *,
        as_of: datetime,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        cutoff = None
        if lookback_days > 0:
            cutoff = (as_of - timedelta(days=lookback_days)).isoformat()

        with self._connect_sqlite() as connection:
            if cutoff is None:
                rows = connection.execute(
                    """
                    SELECT p.strategy_id, p.strategy_family, p.profile_id, p.asset_class,
                           o.checkpoint_code, 0 AS lookback_days,
                           COUNT(DISTINCT p.proposal_id) AS evaluated_proposals,
                           COUNT(o.proposal_id) AS checkpoints_evaluated,
                           SUM(CASE WHEN o.realized_return_pct > 0 THEN 1 ELSE 0 END) AS win_count,
                           SUM(CASE WHEN o.realized_return_pct < 0 THEN 1 ELSE 0 END) AS loss_count,
                           SUM(CASE WHEN o.outcome_status = 'target_hit' THEN 1 ELSE 0 END) AS target_hit_count,
                           SUM(CASE WHEN o.outcome_status = 'stop_hit' THEN 1 ELSE 0 END) AS stop_hit_count,
                           SUM(CASE WHEN o.outcome_status = 'time_exit' THEN 1 ELSE 0 END) AS time_exit_count,
                           SUM(CASE WHEN o.outcome_status = 'ambiguous_range' THEN 1 ELSE 0 END) AS ambiguous_count,
                           AVG(o.fitness_score) AS avg_fitness_score,
                           AVG(o.realized_return_pct) AS avg_realized_return_pct,
                           AVG(o.max_favorable_excursion_pct) AS avg_max_favorable_excursion_pct,
                           AVG(o.max_adverse_excursion_pct) AS avg_max_adverse_excursion_pct,
                           AVG(p.signal_score) AS avg_signal_score,
                           AVG(p.signal_confidence) AS avg_signal_confidence,
                           AVG(p.discovery_score) AS avg_discovery_score,
                           MIN(p.proposed_at) AS first_proposed_at,
                           MAX(o.evaluated_at) AS last_evaluated_at
                    FROM shadow_trade_proposals p
                    JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                    WHERE p.strategy_id != ''
                      AND o.evaluated_at IS NOT NULL
                    GROUP BY p.strategy_id, p.strategy_family, p.profile_id, p.asset_class, o.checkpoint_code
                    ORDER BY avg_fitness_score DESC, checkpoints_evaluated DESC, p.strategy_id ASC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT p.strategy_id, p.strategy_family, p.profile_id, p.asset_class,
                           o.checkpoint_code, ? AS lookback_days,
                           COUNT(DISTINCT p.proposal_id) AS evaluated_proposals,
                           COUNT(o.proposal_id) AS checkpoints_evaluated,
                           SUM(CASE WHEN o.realized_return_pct > 0 THEN 1 ELSE 0 END) AS win_count,
                           SUM(CASE WHEN o.realized_return_pct < 0 THEN 1 ELSE 0 END) AS loss_count,
                           SUM(CASE WHEN o.outcome_status = 'target_hit' THEN 1 ELSE 0 END) AS target_hit_count,
                           SUM(CASE WHEN o.outcome_status = 'stop_hit' THEN 1 ELSE 0 END) AS stop_hit_count,
                           SUM(CASE WHEN o.outcome_status = 'time_exit' THEN 1 ELSE 0 END) AS time_exit_count,
                           SUM(CASE WHEN o.outcome_status = 'ambiguous_range' THEN 1 ELSE 0 END) AS ambiguous_count,
                           AVG(o.fitness_score) AS avg_fitness_score,
                           AVG(o.realized_return_pct) AS avg_realized_return_pct,
                           AVG(o.max_favorable_excursion_pct) AS avg_max_favorable_excursion_pct,
                           AVG(o.max_adverse_excursion_pct) AS avg_max_adverse_excursion_pct,
                           AVG(p.signal_score) AS avg_signal_score,
                           AVG(p.signal_confidence) AS avg_signal_confidence,
                           AVG(p.discovery_score) AS avg_discovery_score,
                           MIN(p.proposed_at) AS first_proposed_at,
                           MAX(o.evaluated_at) AS last_evaluated_at
                    FROM shadow_trade_proposals p
                    JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                    WHERE p.strategy_id != ''
                      AND o.evaluated_at IS NOT NULL
                      AND p.proposed_at >= ?
                    GROUP BY p.strategy_id, p.strategy_family, p.profile_id, p.asset_class, o.checkpoint_code
                    ORDER BY avg_fitness_score DESC, checkpoints_evaluated DESC, p.strategy_id ASC
                    """,
                    (lookback_days, cutoff),
                ).fetchall()
        return [dict(row) for row in rows]

    def _list_strategy_fitness_rows_postgres(
        self,
        *,
        as_of: datetime,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        cutoff = None
        if lookback_days > 0:
            cutoff = as_of - timedelta(days=lookback_days)

        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if cutoff is None:
                    cursor.execute(
                        """
                        SELECT p.strategy_id, p.strategy_family, p.profile_id, p.asset_class,
                               o.checkpoint_code, 0 AS lookback_days,
                               COUNT(DISTINCT p.proposal_id) AS evaluated_proposals,
                               COUNT(o.proposal_id) AS checkpoints_evaluated,
                               SUM(CASE WHEN o.realized_return_pct > 0 THEN 1 ELSE 0 END) AS win_count,
                               SUM(CASE WHEN o.realized_return_pct < 0 THEN 1 ELSE 0 END) AS loss_count,
                               SUM(CASE WHEN o.outcome_status = 'target_hit' THEN 1 ELSE 0 END) AS target_hit_count,
                               SUM(CASE WHEN o.outcome_status = 'stop_hit' THEN 1 ELSE 0 END) AS stop_hit_count,
                               SUM(CASE WHEN o.outcome_status = 'time_exit' THEN 1 ELSE 0 END) AS time_exit_count,
                               SUM(CASE WHEN o.outcome_status = 'ambiguous_range' THEN 1 ELSE 0 END) AS ambiguous_count,
                               AVG(o.fitness_score) AS avg_fitness_score,
                               AVG(o.realized_return_pct) AS avg_realized_return_pct,
                               AVG(o.max_favorable_excursion_pct) AS avg_max_favorable_excursion_pct,
                               AVG(o.max_adverse_excursion_pct) AS avg_max_adverse_excursion_pct,
                               AVG(p.signal_score) AS avg_signal_score,
                               AVG(p.signal_confidence) AS avg_signal_confidence,
                               AVG(p.discovery_score) AS avg_discovery_score,
                               MIN(p.proposed_at) AS first_proposed_at,
                               MAX(o.evaluated_at) AS last_evaluated_at
                        FROM shadow_trade_proposals p
                        JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                        WHERE p.strategy_id != ''
                          AND o.evaluated_at IS NOT NULL
                        GROUP BY p.strategy_id, p.strategy_family, p.profile_id, p.asset_class, o.checkpoint_code
                        ORDER BY avg_fitness_score DESC, checkpoints_evaluated DESC, p.strategy_id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT p.strategy_id, p.strategy_family, p.profile_id, p.asset_class,
                               o.checkpoint_code, %s AS lookback_days,
                               COUNT(DISTINCT p.proposal_id) AS evaluated_proposals,
                               COUNT(o.proposal_id) AS checkpoints_evaluated,
                               SUM(CASE WHEN o.realized_return_pct > 0 THEN 1 ELSE 0 END) AS win_count,
                               SUM(CASE WHEN o.realized_return_pct < 0 THEN 1 ELSE 0 END) AS loss_count,
                               SUM(CASE WHEN o.outcome_status = 'target_hit' THEN 1 ELSE 0 END) AS target_hit_count,
                               SUM(CASE WHEN o.outcome_status = 'stop_hit' THEN 1 ELSE 0 END) AS stop_hit_count,
                               SUM(CASE WHEN o.outcome_status = 'time_exit' THEN 1 ELSE 0 END) AS time_exit_count,
                               SUM(CASE WHEN o.outcome_status = 'ambiguous_range' THEN 1 ELSE 0 END) AS ambiguous_count,
                               AVG(o.fitness_score) AS avg_fitness_score,
                               AVG(o.realized_return_pct) AS avg_realized_return_pct,
                               AVG(o.max_favorable_excursion_pct) AS avg_max_favorable_excursion_pct,
                               AVG(o.max_adverse_excursion_pct) AS avg_max_adverse_excursion_pct,
                               AVG(p.signal_score) AS avg_signal_score,
                               AVG(p.signal_confidence) AS avg_signal_confidence,
                               AVG(p.discovery_score) AS avg_discovery_score,
                               MIN(p.proposed_at) AS first_proposed_at,
                               MAX(o.evaluated_at) AS last_evaluated_at
                        FROM shadow_trade_proposals p
                        JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                        WHERE p.strategy_id != ''
                          AND o.evaluated_at IS NOT NULL
                          AND p.proposed_at >= %s
                        GROUP BY p.strategy_id, p.strategy_family, p.profile_id, p.asset_class, o.checkpoint_code
                        ORDER BY avg_fitness_score DESC, checkpoints_evaluated DESC, p.strategy_id ASC
                        """,
                        (lookback_days, cutoff),
                    )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_shadow_proposal_events_sqlite(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT proposed_at, strategy_id, source, symbol
                FROM shadow_trade_proposals
                WHERE proposed_at >= ? AND proposed_at <= ?
                ORDER BY proposed_at ASC, proposal_id ASC
                """,
                (start_at.isoformat(), end_at.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_shadow_proposal_events_postgres(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT proposed_at, strategy_id, source, symbol
                    FROM shadow_trade_proposals
                    WHERE proposed_at >= %s AND proposed_at <= %s
                    ORDER BY proposed_at ASC, proposal_id ASC
                    """,
                    (start_at, end_at),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_market_bars_for_window_sqlite(
        self,
        *,
        source: str,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT captured_at, bar_timestamp, open_price, high_price, low_price,
                       close_price, open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                       volume, trade_count
                FROM market_data_latest_bars
                WHERE source = ? AND symbol = ?
                  AND captured_at >= ? AND captured_at <= ?
                ORDER BY captured_at ASC
                """,
                (
                    source,
                    symbol,
                    start_at.isoformat(),
                    end_at.isoformat(),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_historical_bars_sqlite(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None,
        end_at: datetime | None,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if not sources:
            return []

        conditions = ["timeframe = ?", f"source IN ({','.join('?' for _ in sources)})"]
        params: list[Any] = [timeframe, *sources]
        if start_at is not None:
            conditions.append("bar_timestamp >= ?")
            params.append(start_at.isoformat())
        if end_at is not None:
            conditions.append("bar_timestamp <= ?")
            params.append(end_at.isoformat())
        if symbols:
            conditions.append(f"symbol IN ({','.join('?' for _ in symbols)})")
            params.extend(symbols)

        where_clause = " AND ".join(conditions)
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                f"""
                SELECT batch_id, captured_at, source, asset_class, symbol, timeframe,
                       canonical_instrument_id, venue, venue_symbol,
                       bar_timestamp, quote_currency, usd_to_gbp_rate,
                       open_price, high_price, low_price, close_price,
                       open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                       volume, trade_count, vwap
                FROM market_data_historical_bars
                WHERE {where_clause}
                ORDER BY bar_timestamp ASC, source ASC, symbol ASC
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_historical_bars_for_window_sqlite(
        self,
        *,
        source: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT bar_timestamp AS captured_at, bar_timestamp, open_price, high_price, low_price,
                       close_price, open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                       volume, trade_count
                FROM market_data_historical_bars
                WHERE source = ? AND symbol = ? AND timeframe = ?
                  AND bar_timestamp >= ? AND bar_timestamp <= ?
                ORDER BY bar_timestamp ASC
                """,
                (
                    source,
                    symbol,
                    timeframe,
                    start_at.isoformat(),
                    end_at.isoformat(),
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_market_bars_for_window_postgres(
        self,
        *,
        source: str,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT captured_at, bar_timestamp, open_price, high_price, low_price,
                           close_price, open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                           volume, trade_count
                    FROM market_data_latest_bars
                    WHERE source = %s AND symbol = %s
                      AND captured_at >= %s AND captured_at <= %s
                    ORDER BY captured_at ASC
                    """,
                    (
                        source,
                        symbol,
                        start_at,
                        end_at,
                    ),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_historical_bars_postgres(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None,
        end_at: datetime | None,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        if not sources:
            return []

        conditions = ["timeframe = %s", "source = ANY(%s)"]
        params: list[Any] = [timeframe, sources]
        if start_at is not None:
            conditions.append("bar_timestamp >= %s")
            params.append(start_at)
        if end_at is not None:
            conditions.append("bar_timestamp <= %s")
            params.append(end_at)
        if symbols:
            conditions.append("symbol = ANY(%s)")
            params.append(symbols)

        where_clause = " AND ".join(conditions)
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT batch_id, captured_at, source, asset_class, symbol, timeframe,
                           canonical_instrument_id, venue, venue_symbol,
                           bar_timestamp, quote_currency, usd_to_gbp_rate,
                           open_price, high_price, low_price, close_price,
                           open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                           volume, trade_count, vwap
                    FROM market_data_historical_bars
                    WHERE {where_clause}
                    ORDER BY bar_timestamp ASC, source ASC, symbol ASC
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_historical_bars_for_window_postgres(
        self,
        *,
        source: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT bar_timestamp AS captured_at, bar_timestamp, open_price, high_price, low_price,
                           close_price, open_price_gbp, high_price_gbp, low_price_gbp, close_price_gbp,
                           volume, trade_count
                    FROM market_data_historical_bars
                    WHERE source = %s AND symbol = %s AND timeframe = %s
                      AND bar_timestamp >= %s AND bar_timestamp <= %s
                    ORDER BY bar_timestamp ASC
                    """,
                    (
                        source,
                        symbol,
                        timeframe,
                        start_at,
                        end_at,
                    ),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_daily_usage_sqlite(self, *, usage_date: date) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT usage_date, source, request_count, success_count, error_count,
                       input_units, output_units, estimated_cost_usd
                FROM api_daily_usage
                WHERE usage_date = ?
                ORDER BY estimated_cost_usd DESC, request_count DESC, source ASC
                """,
                (usage_date.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_daily_usage_postgres(self, *, usage_date: date) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT usage_date, source, request_count, success_count, error_count,
                           input_units, output_units, estimated_cost_usd
                    FROM api_daily_usage
                    WHERE usage_date = %s
                    ORDER BY estimated_cost_usd DESC, request_count DESC, source ASC
                    """,
                    (usage_date,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_tick_usage_sqlite(self, *, tick_id: str, usage_date: date) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT usage_date, source,
                       SUM(request_count) AS request_count,
                       SUM(success_count) AS success_count,
                       SUM(error_count) AS error_count,
                       SUM(input_units) AS input_units,
                       SUM(output_units) AS output_units,
                       SUM(estimated_cost_usd) AS estimated_cost_usd
                FROM api_request_events
                WHERE tick_id = ? AND usage_date = ?
                GROUP BY usage_date, source
                ORDER BY estimated_cost_usd DESC, request_count DESC, source ASC
                """,
                (tick_id, usage_date.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_tick_usage_postgres(self, *, tick_id: str, usage_date: date) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT usage_date, source,
                           SUM(request_count) AS request_count,
                           SUM(success_count) AS success_count,
                           SUM(error_count) AS error_count,
                           SUM(input_units) AS input_units,
                           SUM(output_units) AS output_units,
                           SUM(estimated_cost_usd) AS estimated_cost_usd
                    FROM api_request_events
                    WHERE tick_id = %s AND usage_date = %s
                    GROUP BY usage_date, source
                    ORDER BY estimated_cost_usd DESC, request_count DESC, source ASC
                    """,
                    (tick_id, usage_date),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_latest_tick_run_sqlite(self) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_tick_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_latest_tick_run_postgres(self) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM control_tick_runs
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_first_tick_run_sqlite(self) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_tick_runs
                ORDER BY started_at ASC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_first_tick_run_postgres(self) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM control_tick_runs
                    ORDER BY started_at ASC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_first_account_tick_run_sqlite(self) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_tick_runs
                WHERE state_snapshot_json LIKE '%"alpaca_account"%'
                ORDER BY started_at ASC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_first_account_tick_run_postgres(self) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM control_tick_runs
                    WHERE state_snapshot_json::text LIKE '%"alpaca_account"%'
                    ORDER BY started_at ASC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_latest_tick_run_before_sqlite(
        self,
        *,
        started_before: datetime,
    ) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_tick_runs
                WHERE started_at <= ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (started_before.isoformat(),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_latest_tick_run_before_postgres(
        self,
        *,
        started_before: datetime,
    ) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM control_tick_runs
                    WHERE started_at <= %s
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (started_before,),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_tick_run_sqlite(self, *, tick_id: str) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_tick_runs
                WHERE tick_id = ?
                LIMIT 1
                """,
                (tick_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_tick_run_postgres(self, *, tick_id: str) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM control_tick_runs
                    WHERE tick_id = %s
                    LIMIT 1
                    """,
                    (tick_id,),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_daily_protection_state_sqlite(self, *, session_date: date) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM daily_protection_state
                WHERE session_date = ?
                LIMIT 1
                """,
                (session_date.isoformat(),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_daily_protection_state_postgres(self, *, session_date: date) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM daily_protection_state
                    WHERE session_date = %s
                    LIMIT 1
                    """,
                    (session_date,),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _upsert_daily_protection_state_sqlite(
        self,
        *,
        session_date: date,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str,
    ) -> dict[str, Any]:
        protection_triggered_at = checked_at.isoformat() if system_status == "protected" else None
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                INSERT INTO daily_protection_state (
                    session_date, market_open_at, baseline_tick_id, baseline_equity,
                    first_checked_at, last_tick_id, last_checked_at, latest_equity,
                    equity_drawdown_usd, max_daily_drawdown_usd, system_status,
                    protection_triggered_at, stale_orders_reaped_count, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    last_tick_id = excluded.last_tick_id,
                    last_checked_at = excluded.last_checked_at,
                    latest_equity = excluded.latest_equity,
                    equity_drawdown_usd = excluded.equity_drawdown_usd,
                    max_daily_drawdown_usd = excluded.max_daily_drawdown_usd,
                    system_status = CASE
                        WHEN daily_protection_state.system_status = 'protected' OR excluded.system_status = 'protected'
                        THEN 'protected'
                        ELSE excluded.system_status
                    END,
                    protection_triggered_at = CASE
                        WHEN daily_protection_state.protection_triggered_at IS NOT NULL
                        THEN daily_protection_state.protection_triggered_at
                        WHEN excluded.system_status = 'protected'
                        THEN excluded.protection_triggered_at
                        ELSE NULL
                    END,
                    notes = CASE
                        WHEN excluded.notes <> '' THEN excluded.notes
                        ELSE daily_protection_state.notes
                    END
                """,
                (
                    session_date.isoformat(),
                    market_open_at.isoformat(),
                    tick_id,
                    current_equity,
                    checked_at.isoformat(),
                    tick_id,
                    checked_at.isoformat(),
                    current_equity,
                    0.0,
                    max_daily_drawdown_usd,
                    system_status,
                    protection_triggered_at,
                    notes,
                ),
            )
            connection.execute(
                """
                UPDATE daily_protection_state
                SET equity_drawdown_usd = ROUND(MAX(0, baseline_equity - latest_equity), 6)
                WHERE session_date = ?
                """,
                (session_date.isoformat(),),
            )
            row = connection.execute(
                """
                SELECT *
                FROM daily_protection_state
                WHERE session_date = ?
                LIMIT 1
                """,
                (session_date.isoformat(),),
            ).fetchone()
        return dict(row) if row is not None else {}

    def _upsert_daily_protection_state_postgres(
        self,
        *,
        session_date: date,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str,
    ) -> dict[str, Any]:
        protection_triggered_at = checked_at if system_status == "protected" else None
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO daily_protection_state (
                        session_date, market_open_at, baseline_tick_id, baseline_equity,
                        first_checked_at, last_tick_id, last_checked_at, latest_equity,
                        equity_drawdown_usd, max_daily_drawdown_usd, system_status,
                        protection_triggered_at, stale_orders_reaped_count, notes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, 0, %s
                    )
                    ON CONFLICT(session_date) DO UPDATE SET
                        last_tick_id = EXCLUDED.last_tick_id,
                        last_checked_at = EXCLUDED.last_checked_at,
                        latest_equity = EXCLUDED.latest_equity,
                        equity_drawdown_usd = GREATEST(0, daily_protection_state.baseline_equity - EXCLUDED.latest_equity),
                        max_daily_drawdown_usd = EXCLUDED.max_daily_drawdown_usd,
                        system_status = CASE
                            WHEN daily_protection_state.system_status = 'protected' OR EXCLUDED.system_status = 'protected'
                            THEN 'protected'
                            ELSE EXCLUDED.system_status
                        END,
                        protection_triggered_at = CASE
                            WHEN daily_protection_state.protection_triggered_at IS NOT NULL
                            THEN daily_protection_state.protection_triggered_at
                            WHEN EXCLUDED.system_status = 'protected'
                            THEN EXCLUDED.protection_triggered_at
                            ELSE NULL
                        END,
                        notes = CASE
                            WHEN EXCLUDED.notes <> '' THEN EXCLUDED.notes
                            ELSE daily_protection_state.notes
                        END
                    RETURNING *
                    """,
                    (
                        session_date,
                        market_open_at,
                        tick_id,
                        current_equity,
                        checked_at,
                        tick_id,
                        checked_at,
                        current_equity,
                        0.0,
                        max_daily_drawdown_usd,
                        system_status,
                        protection_triggered_at,
                        notes,
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else {}

    def _increment_daily_stale_order_count_sqlite(
        self,
        *,
        session_date: date,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                UPDATE daily_protection_state
                SET last_tick_id = ?,
                    last_checked_at = ?,
                    stale_orders_reaped_count = stale_orders_reaped_count + ?,
                    notes = CASE
                        WHEN notes = '' THEN ?
                        ELSE notes || ' | ' || ?
                    END
                WHERE session_date = ?
                """,
                (
                    tick_id,
                    checked_at.isoformat(),
                    count,
                    f"stale_orders_reaped+={count}",
                    f"stale_orders_reaped+={count}",
                    session_date.isoformat(),
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM daily_protection_state
                WHERE session_date = ?
                LIMIT 1
                """,
                (session_date.isoformat(),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _increment_daily_stale_order_count_postgres(
        self,
        *,
        session_date: date,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE daily_protection_state
                    SET last_tick_id = %s,
                        last_checked_at = %s,
                        stale_orders_reaped_count = stale_orders_reaped_count + %s,
                        notes = CASE
                            WHEN notes = '' THEN %s
                            ELSE notes || ' | ' || %s
                        END
                    WHERE session_date = %s
                    RETURNING *
                    """,
                    (
                        tick_id,
                        checked_at,
                        count,
                        f"stale_orders_reaped+={count}",
                        f"stale_orders_reaped+={count}",
                        session_date,
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _get_broker_daily_protection_state_sqlite(
        self,
        *,
        session_date: date,
        broker_id: str,
    ) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM broker_daily_protection_state
                WHERE session_date = ? AND broker_id = ?
                LIMIT 1
                """,
                (session_date.isoformat(), str(broker_id).strip().lower()),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_broker_daily_protection_state_postgres(
        self,
        *,
        session_date: date,
        broker_id: str,
    ) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM broker_daily_protection_state
                    WHERE session_date = %s AND broker_id = %s
                    LIMIT 1
                    """,
                    (session_date, str(broker_id).strip().lower()),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _upsert_broker_daily_protection_state_sqlite(
        self,
        *,
        session_date: date,
        broker_id: str,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str,
    ) -> dict[str, Any]:
        normalized_broker_id = str(broker_id).strip().lower()
        protection_triggered_at = checked_at.isoformat() if system_status == "protected" else None
        with self._connect_sqlite() as connection:
            # Preserve the first baseline and latch `protected` once reached for
            # the session; later equity recovery must not silently re-enable entries.
            connection.execute(
                """
                INSERT INTO broker_daily_protection_state (
                    session_date, broker_id, market_open_at, baseline_tick_id, baseline_equity,
                    first_checked_at, last_tick_id, last_checked_at, latest_equity,
                    equity_drawdown_usd, max_daily_drawdown_usd, system_status,
                    protection_triggered_at, stale_orders_reaped_count, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(session_date, broker_id) DO UPDATE SET
                    last_tick_id = excluded.last_tick_id,
                    last_checked_at = excluded.last_checked_at,
                    latest_equity = excluded.latest_equity,
                    equity_drawdown_usd = ROUND(MAX(0, broker_daily_protection_state.baseline_equity - excluded.latest_equity), 6),
                    max_daily_drawdown_usd = excluded.max_daily_drawdown_usd,
                    system_status = CASE
                        WHEN broker_daily_protection_state.system_status = 'protected' OR excluded.system_status = 'protected'
                        THEN 'protected'
                        ELSE excluded.system_status
                    END,
                    protection_triggered_at = CASE
                        WHEN broker_daily_protection_state.protection_triggered_at IS NOT NULL
                        THEN broker_daily_protection_state.protection_triggered_at
                        WHEN excluded.system_status = 'protected'
                        THEN excluded.protection_triggered_at
                        ELSE NULL
                    END,
                    notes = CASE
                        WHEN excluded.notes <> '' THEN excluded.notes
                        ELSE broker_daily_protection_state.notes
                    END
                """,
                (
                    session_date.isoformat(),
                    normalized_broker_id,
                    market_open_at.isoformat(),
                    tick_id,
                    current_equity,
                    checked_at.isoformat(),
                    tick_id,
                    checked_at.isoformat(),
                    current_equity,
                    0.0,
                    max_daily_drawdown_usd,
                    system_status,
                    protection_triggered_at,
                    notes,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM broker_daily_protection_state
                WHERE session_date = ? AND broker_id = ?
                LIMIT 1
                """,
                (session_date.isoformat(), normalized_broker_id),
            ).fetchone()
        return dict(row) if row is not None else {}

    def _upsert_broker_daily_protection_state_postgres(
        self,
        *,
        session_date: date,
        broker_id: str,
        market_open_at: datetime,
        tick_id: str,
        checked_at: datetime,
        current_equity: float,
        max_daily_drawdown_usd: float,
        system_status: str,
        notes: str,
    ) -> dict[str, Any]:
        normalized_broker_id = str(broker_id).strip().lower()
        protection_triggered_at = checked_at if system_status == "protected" else None
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                # Match the SQLite behavior: first baseline wins and protected
                # status stays latched for the broker/session.
                cursor.execute(
                    """
                    INSERT INTO broker_daily_protection_state (
                        session_date, broker_id, market_open_at, baseline_tick_id, baseline_equity,
                        first_checked_at, last_tick_id, last_checked_at, latest_equity,
                        equity_drawdown_usd, max_daily_drawdown_usd, system_status,
                        protection_triggered_at, stale_orders_reaped_count, notes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, 0, %s
                    )
                    ON CONFLICT(session_date, broker_id) DO UPDATE SET
                        last_tick_id = EXCLUDED.last_tick_id,
                        last_checked_at = EXCLUDED.last_checked_at,
                        latest_equity = EXCLUDED.latest_equity,
                        equity_drawdown_usd = GREATEST(0, broker_daily_protection_state.baseline_equity - EXCLUDED.latest_equity),
                        max_daily_drawdown_usd = EXCLUDED.max_daily_drawdown_usd,
                        system_status = CASE
                            WHEN broker_daily_protection_state.system_status = 'protected' OR EXCLUDED.system_status = 'protected'
                            THEN 'protected'
                            ELSE EXCLUDED.system_status
                        END,
                        protection_triggered_at = CASE
                            WHEN broker_daily_protection_state.protection_triggered_at IS NOT NULL
                            THEN broker_daily_protection_state.protection_triggered_at
                            WHEN EXCLUDED.system_status = 'protected'
                            THEN EXCLUDED.protection_triggered_at
                            ELSE NULL
                        END,
                        notes = CASE
                            WHEN EXCLUDED.notes <> '' THEN EXCLUDED.notes
                            ELSE broker_daily_protection_state.notes
                        END
                    RETURNING *
                    """,
                    (
                        session_date,
                        normalized_broker_id,
                        market_open_at,
                        tick_id,
                        current_equity,
                        checked_at,
                        tick_id,
                        checked_at,
                        current_equity,
                        0.0,
                        max_daily_drawdown_usd,
                        system_status,
                        protection_triggered_at,
                        notes,
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else {}

    def _increment_broker_daily_stale_order_count_sqlite(
        self,
        *,
        session_date: date,
        broker_id: str,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> dict[str, Any] | None:
        normalized_broker_id = str(broker_id).strip().lower()
        with self._connect_sqlite() as connection:
            connection.execute(
                """
                UPDATE broker_daily_protection_state
                SET last_tick_id = ?,
                    last_checked_at = ?,
                    stale_orders_reaped_count = stale_orders_reaped_count + ?,
                    notes = CASE
                        WHEN notes = '' THEN ?
                        ELSE notes || ' | ' || ?
                    END
                WHERE session_date = ? AND broker_id = ?
                """,
                (
                    tick_id,
                    checked_at.isoformat(),
                    count,
                    f"live_stale_orders_reaped+={count}",
                    f"live_stale_orders_reaped+={count}",
                    session_date.isoformat(),
                    normalized_broker_id,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM broker_daily_protection_state
                WHERE session_date = ? AND broker_id = ?
                LIMIT 1
                """,
                (session_date.isoformat(), normalized_broker_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def _increment_broker_daily_stale_order_count_postgres(
        self,
        *,
        session_date: date,
        broker_id: str,
        tick_id: str,
        checked_at: datetime,
        count: int,
    ) -> dict[str, Any] | None:
        normalized_broker_id = str(broker_id).strip().lower()
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE broker_daily_protection_state
                    SET last_tick_id = %s,
                        last_checked_at = %s,
                        stale_orders_reaped_count = stale_orders_reaped_count + %s,
                        notes = CASE
                            WHEN notes = '' THEN %s
                            ELSE notes || ' | ' || %s
                        END
                    WHERE session_date = %s AND broker_id = %s
                    RETURNING *
                    """,
                    (
                        tick_id,
                        checked_at,
                        count,
                        f"live_stale_orders_reaped+={count}",
                        f"live_stale_orders_reaped+={count}",
                        session_date,
                        normalized_broker_id,
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _list_recent_paper_trade_orders_sqlite(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_trade_orders
                ORDER BY COALESCE(submitted_at, captured_at) DESC, order_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_paper_trade_orders_postgres(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM paper_trade_orders
                    ORDER BY COALESCE(submitted_at, captured_at) DESC, order_id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_first_paper_trade_order_sqlite(
        self,
        *,
        broker_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_broker_id = str(broker_id or "").strip().lower()
        where_clause = "WHERE broker_id = ?" if normalized_broker_id else ""
        params = (normalized_broker_id,) if normalized_broker_id else tuple()
        with self._connect_sqlite() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM paper_trade_orders
                {where_clause}
                ORDER BY COALESCE(submitted_at, captured_at) ASC, order_id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_first_paper_trade_order_postgres(
        self,
        *,
        broker_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_broker_id = str(broker_id or "").strip().lower()
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if normalized_broker_id:
                    cursor.execute(
                        """
                        SELECT *
                        FROM paper_trade_orders
                        WHERE broker_id = %s
                        ORDER BY COALESCE(submitted_at, captured_at) ASC, order_id ASC
                        LIMIT 1
                        """,
                        (normalized_broker_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT *
                        FROM paper_trade_orders
                        ORDER BY COALESCE(submitted_at, captured_at) ASC, order_id ASC
                        LIMIT 1
                        """
                    )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _list_recent_broker_account_snapshots_sqlite(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM broker_account_snapshots
                ORDER BY captured_at DESC, broker_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_broker_account_snapshots_postgres(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM broker_account_snapshots
                    ORDER BY captured_at DESC, broker_id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_recent_execution_router_intents_sqlite(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM execution_router_intents
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_execution_router_intents_postgres(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM execution_router_intents
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_broker_account_high_water_sqlite(
        self,
        *,
        broker_id: str,
        since: datetime,
    ) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM broker_account_snapshots
                WHERE broker_id = ?
                  AND captured_at >= ?
                  AND equity IS NOT NULL
                ORDER BY equity DESC, captured_at ASC
                LIMIT 1
                """,
                (broker_id, since.isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_broker_account_high_water_postgres(
        self,
        *,
        broker_id: str,
        since: datetime,
    ) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM broker_account_snapshots
                    WHERE broker_id = %s
                      AND captured_at >= %s
                      AND equity IS NOT NULL
                    ORDER BY equity DESC, captured_at ASC
                    LIMIT 1
                    """,
                    (broker_id, since),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _list_recent_shadow_trade_proposals_sqlite(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM shadow_trade_proposals
                ORDER BY proposed_at DESC, proposal_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_shadow_trade_proposals_postgres(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM shadow_trade_proposals
                    ORDER BY proposed_at DESC, proposal_id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _get_shadow_trade_proposal_sqlite(self, *, proposal_id: str) -> dict[str, Any] | None:
        with self._connect_sqlite() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM shadow_trade_proposals
                WHERE proposal_id = ?
                LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _get_shadow_trade_proposal_postgres(self, *, proposal_id: str) -> dict[str, Any] | None:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM shadow_trade_proposals
                    WHERE proposal_id = %s
                    LIMIT 1
                    """,
                    (proposal_id,),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _list_recent_tick_runs_sqlite(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT tick_id, started_at, ended_at, status, duration_seconds,
                       tick_api_request_count, daily_api_request_count, budget_status,
                       last_error, state_snapshot_json
                FROM control_tick_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_recent_tick_runs_postgres(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT tick_id, started_at, ended_at, status, duration_seconds,
                           tick_api_request_count, daily_api_request_count, budget_status,
                           last_error, state_snapshot_json
                    FROM control_tick_runs
                    ORDER BY started_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_latest_strategy_fitness_snapshots_sqlite(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            latest_row = connection.execute(
                """
                SELECT captured_at
                FROM strategy_fitness_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
            if latest_row is None:
                return []
            captured_at = latest_row["captured_at"]
            rows = connection.execute(
                """
                SELECT *
                FROM strategy_fitness_snapshots
                WHERE captured_at = ?
                ORDER BY fitness_rank ASC, composite_fitness_score DESC
                LIMIT ?
                """,
                (captured_at, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_latest_strategy_fitness_snapshots_postgres(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    WITH latest_capture AS (
                        SELECT captured_at
                        FROM strategy_fitness_snapshots
                        ORDER BY captured_at DESC
                        LIMIT 1
                    )
                    SELECT s.*
                    FROM strategy_fitness_snapshots s
                    JOIN latest_capture lc ON s.captured_at = lc.captured_at
                    ORDER BY s.fitness_rank ASC, s.composite_fitness_score DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _list_strategy_training_volume_sqlite(self) -> list[dict[str, Any]]:
        with self._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT p.strategy_id,
                       COUNT(DISTINCT p.proposal_id) AS total_proposals,
                       MIN(p.proposed_at) AS first_proposed_at,
                       MAX(p.proposed_at) AS last_proposed_at,
                       COALESCE(SUM(CASE WHEN o.evaluated_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_outcomes
                FROM shadow_trade_proposals p
                LEFT JOIN shadow_trade_outcomes o
                  ON o.proposal_id = p.proposal_id
                WHERE p.strategy_id <> ''
                GROUP BY p.strategy_id
                ORDER BY p.strategy_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_strategy_training_volume_postgres(self) -> list[dict[str, Any]]:
        with self._connect_postgres() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT p.strategy_id,
                           COUNT(DISTINCT p.proposal_id) AS total_proposals,
                           MIN(p.proposed_at) AS first_proposed_at,
                           MAX(p.proposed_at) AS last_proposed_at,
                           COALESCE(SUM(CASE WHEN o.evaluated_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS evaluated_outcomes
                    FROM shadow_trade_proposals p
                    LEFT JOIN shadow_trade_outcomes o
                      ON o.proposal_id = p.proposal_id
                    WHERE p.strategy_id <> ''
                    GROUP BY p.strategy_id
                    ORDER BY p.strategy_id ASC
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _paper_order_row(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        order: dict[str, Any],
        broker_id: str | None = None,
    ) -> dict[str, Any]:
        symbol = str(order.get("symbol", "")).upper()
        asset_class = str(order.get("asset_class", "")).strip().lower()
        if not asset_class:
            asset_class = "crypto" if "/" in symbol else "equity"
        resolved_broker_id = str(
            order.get("broker_id") or broker_id or "alpaca_paper"
        ).strip().lower() or "alpaca_paper"
        metadata = self._order_environment_metadata(
            order=order,
            broker_id=resolved_broker_id,
        )
        instrument = self._instrument_metadata(
            item=order,
            symbol=symbol,
            asset_class=asset_class,
            source=str(order.get("source", "")),
            broker_id=resolved_broker_id,
        )

        take_profit = order.get("take_profit")
        stop_loss = order.get("stop_loss")
        take_profit_price = (
            self._to_float(take_profit.get("limit_price"))
            if isinstance(take_profit, dict)
            else self._to_float(order.get("planned_take_profit_price"))
        )
        stop_loss_price = (
            self._to_float(stop_loss.get("stop_price"))
            if isinstance(stop_loss, dict)
            else self._to_float(order.get("planned_stop_loss_price"))
        )
        status = str(order.get("status", "")).strip().lower()
        return {
            "order_id": str(order.get("id", "")).strip(),
            "tick_id": tick_id,
            "captured_at": captured_at.isoformat(),
            "submitted_at": order.get("submitted_at"),
            "updated_at": order.get("updated_at"),
            "environment": metadata["environment"],
            "mode": metadata["mode"],
            "source_environment": metadata["source_environment"],
            "broker_id": resolved_broker_id,
            "data_provider": metadata["data_provider"],
            "execution_provider": metadata["execution_provider"],
            "canonical_instrument_id": instrument["canonical_instrument_id"],
            "venue": instrument["venue"],
            "venue_symbol": instrument["venue_symbol"],
            "client_order_id": str(order.get("client_order_id", "")).strip(),
            "proposal_id": str(order.get("proposal_id", "")).strip(),
            "strategy_id": str(order.get("strategy_id", "")).strip(),
            "strategy_family": str(order.get("strategy_family", "")).strip(),
            "profile_id": str(order.get("profile_id", "")).strip(),
            "source": str(order.get("source", "")).strip(),
            "symbol": symbol,
            "asset_class": asset_class,
            "side": str(order.get("side", "")).strip().lower(),
            "order_type": str(order.get("type", "")).strip().lower(),
            "time_in_force": str(order.get("time_in_force", "")).strip().lower(),
            "order_class": str(order.get("order_class", "")).strip().lower(),
            "status": status,
            "is_open": self._order_status_is_open(status),
            "qty": self._to_float(order.get("qty")),
            "filled_qty": self._to_float(order.get("filled_qty")),
            "notional_usd": self._to_float(order.get("notional")),
            "filled_avg_price": self._to_float(order.get("filled_avg_price")),
            "limit_price": self._to_float(order.get("limit_price")),
            "stop_price": self._to_float(order.get("stop_price")),
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "raw_json": self._to_json(order),
        }

    def _instrument_metadata(
        self,
        *,
        item: dict[str, Any],
        symbol: str,
        asset_class: str,
        source: str = "",
        broker_id: str = "",
    ) -> dict[str, str]:
        venue = str(item.get("venue") or "").strip().lower()
        if not venue:
            source_text = str(source or item.get("source") or "").strip().lower()
            broker_text = str(broker_id or item.get("broker_id") or "").strip().lower()
            combined = f"{source_text} {broker_text}"
            if "alpaca" in combined:
                venue = "alpaca"
            elif "binance" in combined:
                venue = "binance"
            elif "coinbase" in combined:
                venue = "coinbase"
            elif "kraken" in combined:
                venue = "kraken"

        venue_symbol = str(item.get("venue_symbol") or symbol or "").strip().upper()
        instrument_ref = self.instrument_registry.reference_for(
            venue=venue,
            venue_symbol=venue_symbol,
            asset_class=asset_class,
            canonical_instrument_id=str(item.get("canonical_instrument_id") or ""),
        )
        canonical_id = instrument_ref.canonical_instrument_id
        venue = instrument_ref.venue
        venue_symbol = instrument_ref.venue_symbol
        if not canonical_id:
            canonical_id = self._fallback_canonical_instrument_id(
                symbol=venue_symbol,
                asset_class=asset_class,
            )
        return {
            "canonical_instrument_id": canonical_id,
            "venue": venue,
            "venue_symbol": venue_symbol,
        }

    def _with_instrument_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        symbol = str(item.get("symbol", "")).upper()
        asset_class = str(item.get("asset_class", "")).strip().lower()
        if not asset_class:
            asset_class = "crypto" if "/" in symbol else "equity"
        instrument = self._instrument_metadata(
            item=item,
            symbol=symbol,
            asset_class=asset_class,
            source=str(item.get("source", "")),
            broker_id=str(item.get("broker_id", "")),
        )
        return {
            **item,
            "canonical_instrument_id": instrument["canonical_instrument_id"],
            "venue": instrument["venue"],
            "venue_symbol": instrument["venue_symbol"],
        }

    def _fallback_canonical_instrument_id(
        self,
        *,
        symbol: str,
        asset_class: str,
    ) -> str:
        normalized_asset_class = str(asset_class or "").strip().lower()
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            return ""
        if normalized_asset_class == "crypto":
            if "/" in normalized_symbol:
                base, quote = normalized_symbol.split("/", 1)
            elif normalized_symbol.endswith("USD"):
                base, quote = normalized_symbol[:-3], "USD"
            elif normalized_symbol.endswith("USDT"):
                base, quote = normalized_symbol[:-4], "USD"
            else:
                return f"{normalized_symbol}-SPOT"
            return f"{base}-{quote.replace('USDT', 'USD')}-SPOT"
        if normalized_asset_class in {"equity", "etf"}:
            return f"{normalized_symbol}-US-EQUITY"
        return normalized_symbol

    def _order_environment_metadata(
        self,
        *,
        order: dict[str, Any],
        broker_id: str,
    ) -> dict[str, str]:
        """Infer explicit paper/live provenance for a broker order row."""
        normalized_broker = str(broker_id or "").strip().lower()
        inferred_environment = "live" if normalized_broker.endswith("_live") else "paper"
        environment = str(
            order.get("environment") or inferred_environment
        ).strip().lower()
        if environment not in {"paper", "live"}:
            environment = inferred_environment

        inferred_mode = "live" if environment == "live" else "paper"
        mode = str(order.get("mode") or inferred_mode).strip().lower()
        if mode not in {"shadow", "paper", "live_dry", "live"}:
            mode = inferred_mode

        source_environment = str(order.get("source_environment") or "").strip().lower()
        if source_environment not in {"shadow", "paper", "live", "backtest"}:
            if environment == "live" and str(order.get("proposal_id") or "").strip():
                source_environment = "paper"
            elif str(order.get("proposal_id") or "").strip():
                source_environment = "shadow"
            else:
                source_environment = environment

        source = str(order.get("source") or "").strip().lower()
        data_provider = str(order.get("data_provider") or "").strip().lower()
        if not data_provider:
            data_provider = "alpaca" if "alpaca" in normalized_broker or "alpaca" in source else source
        if not data_provider:
            data_provider = "unknown"

        execution_provider = str(order.get("execution_provider") or "").strip().lower()
        if not execution_provider:
            execution_provider = normalized_broker or "unknown"

        return {
            "environment": environment,
            "mode": mode,
            "source_environment": source_environment,
            "data_provider": data_provider,
            "execution_provider": execution_provider,
        }

    def _broker_account_snapshot_row(
        self,
        *,
        tick_id: str,
        captured_at: datetime,
        broker_id: str,
        summary: dict[str, Any],
        raw_account: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        currency = str(summary.get("currency") or raw_account.get("currency") or "USD").upper()
        position_market_value = self._to_float(raw_account.get("long_market_value"))
        if position_market_value is None:
            position_market_value = self._to_float(raw_account.get("position_market_value"))
        if position_market_value is None:
            position_market_value = round(
                sum(
                    self._to_float(position.get("market_value")) or 0.0
                    for position in positions
                    if isinstance(position, dict)
                ),
                6,
            )
        open_position_unrealized_pl = round(
            sum(
                self._to_float(position.get("unrealized_pl")) or 0.0
                for position in positions
                if isinstance(position, dict)
            ),
            6,
        )
        return {
            "tick_id": tick_id,
            "broker_id": str(broker_id).strip().lower(),
            "captured_at": captured_at.isoformat(),
            "account_status": str(summary.get("status") or raw_account.get("status") or "unknown"),
            "currency": currency,
            "equity": self._to_float(summary.get("equity") or raw_account.get("equity")),
            "cash": self._to_float(summary.get("cash") or raw_account.get("cash")),
            "buying_power": self._to_float(
                summary.get("buying_power") or raw_account.get("buying_power")
            ),
            "portfolio_value": self._to_float(
                summary.get("portfolio_value") or raw_account.get("portfolio_value")
            ),
            "last_equity": self._to_float(raw_account.get("last_equity")),
            "position_market_value": position_market_value,
            "open_position_unrealized_pl": open_position_unrealized_pl,
            "raw_json": self._to_json(
                {
                    "summary": summary,
                    "account": raw_account,
                    "positions": positions,
                }
            ),
        }

    def _connect_sqlite(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _connect_postgres(self, *, apply_schema: bool = True):
        if psycopg2 is None:  # pragma: no cover
            raise RuntimeError("psycopg2 is not installed.")
        connection = psycopg2.connect(self.config.database_url, connect_timeout=5)
        if apply_schema:
            with connection.cursor() as cursor:
                self._set_postgres_search_path(cursor)
        return connection

    def _ensure_postgres_namespace(self, cursor) -> None:
        schema_name = self._postgres_schema_name()
        if not schema_name:
            return
        if sql is None:  # pragma: no cover
            raise RuntimeError("psycopg2.sql is not available.")
        cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema_name)
            )
        )
        self._set_postgres_search_path(cursor)

    def _set_postgres_search_path(self, cursor) -> None:
        schema_name = self._postgres_schema_name()
        if not schema_name:
            return
        if sql is None:  # pragma: no cover
            raise RuntimeError("psycopg2.sql is not available.")
        cursor.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )

    def _postgres_schema_name(self) -> str:
        schema_name = str(getattr(self.config, "postgres_schema", "") or "").strip()
        if not schema_name:
            return ""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema_name):
            raise RuntimeError(f"Invalid PostgreSQL schema name: {schema_name!r}")
        return schema_name

    def _postgres_schema_detail(self) -> str:
        schema_name = str(getattr(self.config, "postgres_schema", "") or "").strip()
        return f":schema={schema_name}" if schema_name else ""

    def _row_to_summary(self, row: dict[str, Any]) -> ApiUsageSummary:
        usage_date = row["usage_date"]
        if hasattr(usage_date, "isoformat"):
            usage_date = usage_date.isoformat()

        return ApiUsageSummary(
            usage_date=str(usage_date),
            source=row["source"],
            request_count=int(row["request_count"]),
            success_count=int(row["success_count"]),
            error_count=int(row["error_count"]),
            input_units=int(row["input_units"]),
            output_units=int(row["output_units"]),
            estimated_cost_usd=float(row["estimated_cost_usd"]),
        )

    def _last_error_message(self, report: TickReport) -> str | None:
        for profile in reversed(report.step_profiles):
            if profile.error:
                return profile.error
        return None

    def _serialize_step_profiles(self, report: TickReport) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for profile in report.step_profiles:
            serialized.append(
                {
                    "name": profile.name,
                    "status": profile.status,
                    "started_at": profile.started_at.isoformat(),
                    "ended_at": profile.ended_at.isoformat(),
                    "duration_seconds": profile.duration_seconds,
                    "details": profile.details,
                    "error": profile.error,
                }
            )
        return serialized

    def _to_json(self, value: Any) -> str:
        return json.dumps(value, sort_keys=True, default=self._json_default)

    def _from_json(self, value: Any, *, default: Any) -> Any:
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def _json_default(self, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Value of type {type(value).__name__} is not JSON serializable")

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _convert_to_gbp(
        self,
        value: float | None,
        *,
        quote_currency: str,
        usd_to_gbp: float | None,
    ) -> float | None:
        if value is None:
            return None
        if quote_currency.upper() != "USD":
            return None
        if usd_to_gbp is None:
            return None
        return round(value * usd_to_gbp, 8)

    def _normalize_db_datetime_value(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    def _normalize_usage_date_key(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        raw = str(value)
        if "T" in raw or " " in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        return raw

    def _preferred_historical_timeframes(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[str, ...]:
        window_minutes = max(
            1,
            int((end_at - start_at).total_seconds() // 60),
        )
        if window_minutes <= 180:
            return ("1Min", "1Hour", "1Day")
        if window_minutes <= (60 * 24 * 7):
            return ("1Hour", "1Day", "1Min")
        return ("1Day", "1Hour", "1Min")

    def _order_status_is_open(self, status: str) -> bool:
        return status in {
            "new",
            "accepted",
            "pending_new",
            "accepted_for_bidding",
            "partially_filled",
            "held",
            "pending_replace",
            "pending_cancel",
        }

    def _ensure_sqlite_columns(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns.items():
            if column_name not in existing:
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )
