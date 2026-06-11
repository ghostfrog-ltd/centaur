from __future__ import annotations

from datetime import datetime
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.framework.runtime.slack import SlackNotificationError, SlackWebhookClient


PAPER_CANARY_EXECUTION_MODE = "paper_canary"
PAPER_CANARY_BROKER_ID = "alpaca_paper"
PAPER_CANARY_MAX_OPEN_TRADES = 1
PAPER_CANARY_MAX_NOTIONAL_USD = 10.0
PAPER_CANARY_COOLDOWN_MINUTES = 60
PAPER_CANARY_MAX_NEW_ENTRIES_PER_DAY = 3


class PaperCanaryReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def start(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        timeframe: str,
        operator_override: str,
    ) -> dict[str, Any]:
        normalized_override = str(operator_override or "").strip()
        if not normalized_override:
            raise ValueError("paper_canary_operator_override_required")
        now = datetime.now().astimezone()
        self.usage_ledger.activate_paper_canary(
            started_at=now,
            strategy_id=str(strategy_id or "").strip(),
            profile_id=str(profile_id or "").strip(),
            timeframe=str(timeframe or "").strip(),
            operator_override=normalized_override,
            broker_id=PAPER_CANARY_BROKER_ID,
            execution_mode=PAPER_CANARY_EXECUTION_MODE,
        )
        self._send_start_notification(
            strategy_id=strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            operator_override=normalized_override,
            started_at=now,
        )
        return self.build_report()

    def build_report(self) -> dict[str, Any]:
        state = self.usage_ledger.get_paper_canary_state() or {}
        recent_orders = self.usage_ledger.list_recent_paper_trade_orders(limit=250)
        canary_orders = [
            order for order in recent_orders if self._is_canary_order(order)
        ]
        active = bool(state.get("active"))
        today = datetime.now().astimezone().date()
        today_entry_orders = [
            order
            for order in canary_orders
            if str(order.get("side", "")).strip().lower() == "buy"
            and self._order_date(order) == today
        ]
        open_positions = self._open_canary_positions(canary_orders)
        realized_pl = round(
            sum(
                float(item.get("realized_pl_usd", 0.0) or 0.0)
                for item in self._closed_canary_round_trips(canary_orders)
                if self._order_date(item) == today
            ),
            6,
        )
        last_entry_at = state.get("last_entry_at")
        cooldown_remaining_minutes = 0
        cooldown_active = False
        if isinstance(last_entry_at, datetime):
            elapsed_minutes = (datetime.now().astimezone() - last_entry_at).total_seconds() / 60.0
            cooldown_remaining_minutes = max(
                0,
                int(PAPER_CANARY_COOLDOWN_MINUTES - elapsed_minutes),
            )
            cooldown_active = cooldown_remaining_minutes > 0
        return {
            "active": active,
            "execution_mode": PAPER_CANARY_EXECUTION_MODE,
            "paper_canary": True,
            "broker_id": str(state.get("broker_id", "") or PAPER_CANARY_BROKER_ID),
            "strategy_id": str(state.get("strategy_id", "") or ""),
            "profile_id": str(state.get("profile_id", "") or ""),
            "timeframe": str(state.get("timeframe", "") or ""),
            "operator_override": str(state.get("operator_override", "") or ""),
            "started_at": state.get("started_at"),
            "last_entry_at": last_entry_at,
            "cooldown_active": cooldown_active,
            "cooldown_remaining_minutes": cooldown_remaining_minutes,
            "daily_trade_count": len(today_entry_orders),
            "realized_pnl_usd": realized_pl,
            "open_positions": open_positions,
            "rejection_reasons": list(state.get("recent_rejection_reasons", []) or []),
            "limits": {
                "max_open_trades": PAPER_CANARY_MAX_OPEN_TRADES,
                "max_notional_usd": PAPER_CANARY_MAX_NOTIONAL_USD,
                "cooldown_minutes": PAPER_CANARY_COOLDOWN_MINUTES,
                "max_new_entries_per_day": PAPER_CANARY_MAX_NEW_ENTRIES_PER_DAY,
                "no_compounding": True,
                "no_live_trading": True,
                "no_automatic_scaling": True,
                "operator_override_required": True,
            },
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        lines = [
            "Paper Canary Status",
            f"active={'yes' if report.get('active') else 'no'}",
            f"execution_mode={report.get('execution_mode', PAPER_CANARY_EXECUTION_MODE)}",
            f"strategy={report.get('strategy_id', '-')}/{report.get('profile_id', '-')}/{report.get('timeframe', '-')}",
            f"broker={report.get('broker_id', PAPER_CANARY_BROKER_ID)} | live_trading_allowed=no | scaling=off | compounding=off",
            f"started_at={report.get('started_at') or '-'}",
            f"last_entry_at={report.get('last_entry_at') or '-'} | cooldown_active={'yes' if report.get('cooldown_active') else 'no'} | cooldown_remaining_minutes={int(report.get('cooldown_remaining_minutes', 0) or 0)}",
            f"daily_trade_count={int(report.get('daily_trade_count', 0) or 0)} | realised_pnl_usd={float(report.get('realized_pnl_usd', 0.0) or 0.0):.2f}",
            f"open_positions={len(list(report.get('open_positions', []) or []))}",
            f"rejection_reasons={', '.join(report.get('rejection_reasons', []) or []) or '-'}",
        ]
        return "\n".join(lines)

    def _send_start_notification(
        self,
        *,
        strategy_id: str,
        profile_id: str,
        timeframe: str,
        operator_override: str,
        started_at: datetime,
    ) -> None:
        if not bool(getattr(self.config, "slack_alerts_enabled", False)):
            return
        webhook_url = str(getattr(self.config, "slack_webhook_url", "") or "").strip()
        if not webhook_url:
            return
        client = SlackWebhookClient(
            webhook_url=webhook_url,
            timeout_seconds=int(
                getattr(self.config, "slack_request_timeout_seconds", 5) or 5
            ),
        )
        text = (
            "[Project Centaur] INFO: Paper canary mode started\n"
            f"strategy={strategy_id}/{profile_id}/{timeframe} | broker={PAPER_CANARY_BROKER_ID} | "
            f"execution_mode={PAPER_CANARY_EXECUTION_MODE} | started_at={started_at.isoformat(timespec='seconds')} | "
            f"override={operator_override}"
        )
        try:
            client.post_message(text)
            self.usage_ledger.record_notification_event(
                tick_id="paper_canary_start",
                channel="slack",
                event_key=f"paper_canary_started:{started_at.date().isoformat()}:{strategy_id}:{profile_id}:{timeframe}",
                level="info",
                summary="Paper canary mode started",
                detail=text,
                status="sent",
                metadata={"paper_canary": True, "execution_mode": PAPER_CANARY_EXECUTION_MODE},
                sent_at=started_at,
            )
        except (SlackNotificationError, Exception):
            return

    def _is_canary_order(self, order: dict[str, Any]) -> bool:
        raw = order.get("raw_json", {})
        if not isinstance(raw, dict):
            raw = {}
        return (
            str(order.get("mode", "")).strip().lower() == PAPER_CANARY_EXECUTION_MODE
            or bool(raw.get("paper_canary"))
            or str(raw.get("execution_mode", "")).strip().lower() == PAPER_CANARY_EXECUTION_MODE
        )

    def _order_date(self, order: dict[str, Any]) -> datetime.date | None:
        for key in ("submitted_at", "captured_at", "updated_at"):
            value = order.get(key)
            if isinstance(value, datetime):
                return value.astimezone().date()
        return None

    def _open_canary_positions(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        for order in sorted(
            orders,
            key=lambda item: item.get("submitted_at") or item.get("captured_at") or datetime.min,
        ):
            symbol = str(order.get("symbol", "")).upper()
            if not symbol:
                continue
            side = str(order.get("side", "")).strip().lower()
            status = str(order.get("status", "")).strip().lower()
            if side == "buy" and status not in {"canceled", "cancelled", "rejected"}:
                positions[symbol] = {
                    "symbol": symbol,
                    "strategy_id": str(order.get("strategy_id", "") or ""),
                    "profile_id": str(order.get("profile_id", "") or ""),
                    "submitted_at": order.get("submitted_at") or order.get("captured_at"),
                    "notional_usd": float(order.get("notional_usd", 0.0) or 0.0),
                    "status": status,
                }
            elif side == "sell" and symbol in positions and status not in {"canceled", "cancelled", "rejected"}:
                positions.pop(symbol, None)
        return list(positions.values())

    def _closed_canary_round_trips(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buys_by_symbol: dict[str, dict[str, Any]] = {}
        closed: list[dict[str, Any]] = []
        for order in sorted(
            orders,
            key=lambda item: item.get("submitted_at") or item.get("captured_at") or datetime.min,
        ):
            symbol = str(order.get("symbol", "")).upper()
            side = str(order.get("side", "")).strip().lower()
            status = str(order.get("status", "")).strip().lower()
            if side == "buy" and status == "filled":
                buys_by_symbol[symbol] = order
            elif side == "sell" and status == "filled" and symbol in buys_by_symbol:
                entry = buys_by_symbol.pop(symbol)
                qty = float(order.get("filled_qty") or entry.get("filled_qty") or 0.0)
                sell_price = float(order.get("filled_avg_price") or 0.0)
                buy_price = float(entry.get("filled_avg_price") or 0.0)
                closed.append(
                    {
                        **order,
                        "realized_pl_usd": round((sell_price - buy_price) * qty, 6),
                    }
                )
        return closed
