#!/usr/bin/env python3
"""One-shot audited flatten for explicitly named Alpaca Live positions.

This is an operator-approved emergency tool for unmanaged live positions. It
does not alter normal strategy policy: each sell still passes through
ExecutionRouter and LiveRiskGuard, and every submitted broker response is
persisted in the live broker order ledger for later review.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.framework.adapters.brokers import get_broker_adapter
from app.framework.adapters.execution import get_execution_adapter
from app.framework.adapters.market_data import get_market_data_adapter
from app.framework.runtime.execution_router import ExecutionRouter
from app.framework.runtime.models import TickContext
from app.framework.runtime.settings import load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.heartbeat.support import _build_client_order_id, _live_limit_buffer_bps


DEFAULT_SYMBOLS = ("AVGO", "FANG", "TEAM", "MCHP")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten explicitly named Alpaca Live positions through Centaur guards."
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated Alpaca Live symbols to sell. Default: AVGO,FANG,TEAM,MCHP.",
    )
    parser.add_argument(
        "--confirm-live-flatten",
        action="store_true",
        help="Required acknowledgement that this submits real Alpaca Live sell orders.",
    )
    parser.add_argument(
        "--replace-open-sells",
        action="store_true",
        help="Cancel existing open live sell orders for the requested symbols before resubmitting.",
    )
    parser.add_argument(
        "--limit-buffer-bps",
        type=float,
        default=None,
        help="Optional sell limit buffer override in basis points. Defaults to live config.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = tuple(
        dict.fromkeys(
            symbol.strip().upper()
            for symbol in str(args.symbols or "").split(",")
            if symbol.strip()
        )
    )
    if not symbols:
        print("No symbols supplied.")
        return 2
    if not args.confirm_live_flatten:
        print("Refusing live mutation without --confirm-live-flatten.")
        return 2

    started_at = datetime.now().astimezone()
    tick_id = "manual-live-flatten-" + started_at.strftime("%Y%m%d%H%M%S")
    config = load_runtime_config()
    usage_ledger = UsageLedger(config=config)
    context = TickContext(
        tick_id=tick_id,
        started_at=started_at,
        config=config,
        usage_ledger=usage_ledger,
        metadata={
            "operator_action": "human_requested_unmanaged_live_flatten",
            "symbols": list(symbols),
        },
    )

    live_adapter = get_broker_adapter(context, "alpaca_live")
    raw_account, account_summary, raw_positions, raw_orders = _sync_live_state(
        context=context,
        live_adapter=live_adapter,
        started_at=started_at,
    )
    usage_ledger.record_broker_account_snapshot(
        tick_id=tick_id,
        captured_at=started_at,
        broker_id="alpaca_live",
        summary=account_summary,
        raw_account=raw_account,
        positions=raw_positions,
    )

    if args.replace_open_sells:
        router = ExecutionRouter()
        canceled = 0
        for order in raw_orders:
            symbol = str(order.get("symbol", "")).strip().upper()
            if symbol not in symbols:
                continue
            if str(order.get("side", "")).strip().lower() != "sell":
                continue
            if not _order_status_is_open(order.get("status")):
                continue
            order_id = str(order.get("id") or order.get("order_id") or "").strip()
            routed_cancel = router.route_cancel_order(
                context=context,
                broker_id="alpaca_live",
                order_id=order_id,
                lane="live",
            )
            if routed_cancel.canceled:
                canceled += 1
                print(f"CANCELED {symbol}: {order_id}")
            else:
                print(f"ERROR {symbol}: cancel {routed_cancel.error or routed_cancel.status}")
        if canceled:
            time.sleep(1.0)
            raw_account, account_summary, raw_positions, raw_orders = _sync_live_state(
                context=context,
                live_adapter=live_adapter,
                started_at=started_at,
            )

    positions_by_symbol = {
        str(position.get("symbol", "")).strip().upper(): position
        for position in raw_positions
        if str(position.get("symbol", "")).strip()
    }
    selected_positions = {
        symbol: positions_by_symbol[symbol]
        for symbol in symbols
        if symbol in positions_by_symbol
    }
    missing = [symbol for symbol in symbols if symbol not in selected_positions]
    if missing:
        print(f"Skipping missing live positions: {', '.join(missing)}")
    if not selected_positions:
        print("No requested live positions are currently open.")
        return 0

    market_data = get_market_data_adapter(context, "alpaca")
    bars = market_data.get_latest_equity_bars(
        context,
        symbols=list(selected_positions.keys()),
    )
    context.state["market_data_latest_bars"] = {
        "mode": "manual_live_flatten_latest_bars",
        "raw": bars,
    }

    router = ExecutionRouter()
    execution_adapter = get_execution_adapter(context, "alpaca_live")
    submitted_orders: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    limit_buffer_bps = (
        float(args.limit_buffer_bps)
        if args.limit_buffer_bps is not None
        else _live_limit_buffer_bps(config, "equity")
    )

    for symbol, position in selected_positions.items():
        qty = str(position.get("qty") or "").strip()
        latest_bar = bars.get(symbol)
        reference_price = _to_float(
            (latest_bar or {}).get("c")
            if isinstance(latest_bar, dict)
            else None
        ) or _to_float(position.get("current_price"))
        if not qty or reference_price is None or reference_price <= 0:
            errors.append({"symbol": symbol, "error": "invalid_qty_or_reference_price"})
            continue

        order_request = execution_adapter.build_exit_order_request(
            context=context,
            symbol=symbol,
            asset_class="equity",
            qty=qty,
            reference_price=reference_price,
            client_order_id=_build_client_order_id(
                tick_id=tick_id,
                symbol=symbol,
                strategy_id="manualunmanagedflatten",
                lane="live",
            ),
            limit_buffer_bps=limit_buffer_bps,
            entry_order={
                "broker_id": "alpaca_live",
                "symbol": symbol,
                "asset_class": "equity",
                "strategy_id": "unmanaged_position",
                "source": "manual_live_flatten",
            },
            latest_bar=latest_bar,
        )
        routed = router.route_order_request(
            context=context,
            broker_id="alpaca_live",
            order_request=order_request,
            lane="live",
            action="flatten",
            strategy_id="unmanaged_position",
        )
        if routed.submitted and routed.order is not None:
            submitted_orders.append(
                {
                    **routed.order,
                    "broker_id": "alpaca_live",
                    "proposal_id": "",
                    "strategy_id": "unmanaged_position",
                    "strategy_family": "risk",
                    "profile_id": "manual_live_flatten",
                    "source": "manual_live_flatten",
                    "asset_class": "equity",
                    "exit_reason": "human_requested_unmanaged_live_flatten",
                    "unmanaged_flatten": True,
                    "manual_symbols": list(symbols),
                }
            )
            print(f"SUBMITTED {symbol}: {routed.order.get('status', 'submitted')}")
        else:
            errors.append({"symbol": symbol, "error": routed.error or routed.status})
            print(f"ERROR {symbol}: {routed.error or routed.status}")

    if submitted_orders:
        saved = usage_ledger.record_paper_trade_orders(
            tick_id=tick_id,
            captured_at=started_at,
            orders=submitted_orders,
            broker_id="alpaca_live",
        )
        print(f"Saved {saved} submitted live flatten order(s) to the ledger.")

    if errors:
        print("Errors:")
        for item in errors:
            print(f"- {item['symbol']}: {item['error']}")
        return 1
    return 0


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _sync_live_state(
    *,
    context: TickContext,
    live_adapter: Any,
    started_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_account = {**live_adapter.get_account(context), "broker_id": "alpaca_live"}
    account_summary = live_adapter.summarize_account(raw_account)
    raw_positions = [
        {**position, "broker_id": "alpaca_live"}
        for position in live_adapter.get_positions(context)
    ]
    raw_orders = [
        {**order, "broker_id": "alpaca_live"}
        for order in live_adapter.get_orders(
            context,
            status="all",
            after=started_at - timedelta(days=7),
            limit=100,
            nested=True,
        )
    ]
    context.state["alpaca_live_account"] = {
        "broker_id": "alpaca_live",
        "summary": account_summary,
        "raw": raw_account,
    }
    context.state["alpaca_live_positions"] = {
        "broker_id": "alpaca_live",
        "summary": live_adapter.summarize_positions(raw_positions),
        "raw": raw_positions,
    }
    context.state["alpaca_live_orders"] = {
        "broker_id": "alpaca_live",
        "summary": live_adapter.summarize_orders(raw_orders),
        "raw": raw_orders,
    }
    return raw_account, account_summary, raw_positions, raw_orders


def _order_status_is_open(status: Any) -> bool:
    return str(status or "").strip().lower() in {
        "new",
        "accepted",
        "pending_new",
        "accepted_for_bidding",
        "partially_filled",
        "pending_replace",
        "pending_cancel",
    }


if __name__ == "__main__":
    raise SystemExit(main())
