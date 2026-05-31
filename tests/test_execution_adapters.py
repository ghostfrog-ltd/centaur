from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

import app.adapters.execution.broker_bridge as broker_bridge
from app.adapters.execution import (
    UnsupportedExecutionAdapterError,
    get_execution_adapter,
)
from app.adapters.execution.broker_bridge import BrokerExecutionAdapter
from centaur.models import TickContext


class ExecutionAdapterTests(unittest.TestCase):
    def _context(self) -> TickContext:
        return TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(),
            usage_ledger=SimpleNamespace(),
        )

    def test_get_execution_adapter_caches_by_broker_id(self) -> None:
        context = self._context()

        first = get_execution_adapter(context, "alpaca_paper")
        second = get_execution_adapter(context, "alpaca_paper")

        self.assertIs(first, second)
        self.assertIsInstance(first, BrokerExecutionAdapter)
        self.assertEqual(first.broker_id, "alpaca_paper")

    def test_get_execution_adapter_rejects_unimplemented_provider(self) -> None:
        with self.assertRaises(UnsupportedExecutionAdapterError):
            get_execution_adapter(self._context(), "binance")

    def test_get_execution_adapter_rejects_scaffold_only_broker(self) -> None:
        with self.assertRaises(UnsupportedExecutionAdapterError):
            get_execution_adapter(self._context(), "ig_spreadbet")

    def test_broker_bridge_delegates_submit_and_cancel(self) -> None:
        calls = []

        class FakeBrokerAdapter:
            def validate_entry_constraints(
                self,
                *,
                context,
                proposal,
                notional_usd,
                usd_to_gbp=None,
            ):
                calls.append(("validate", context.tick_id, proposal["symbol"], notional_usd))
                return None

            def build_entry_order_request(
                self,
                *,
                proposal,
                client_order_id,
                notional_usd,
                limit_buffer_bps,
                usd_to_gbp=None,
            ):
                calls.append(("build_entry", proposal["symbol"], client_order_id))
                return {"symbol": proposal["symbol"], "client_order_id": client_order_id}

            def build_exit_order_request(
                self,
                *,
                symbol,
                asset_class,
                qty,
                reference_price,
                client_order_id,
                limit_buffer_bps,
                entry_order=None,
                latest_bar=None,
                usd_to_gbp=None,
            ):
                calls.append(("build_exit", symbol, client_order_id))
                return {"symbol": symbol, "client_order_id": client_order_id}

            def submit_order(self, context, *, order_request):
                calls.append(("submit", context.tick_id, order_request))
                return {"id": "order-1", "symbol": order_request["symbol"]}

            def cancel_order(self, context, *, order_id):
                calls.append(("cancel", context.tick_id, order_id))

        original = broker_bridge.get_broker_adapter
        broker_bridge.get_broker_adapter = lambda _context, _broker_id: FakeBrokerAdapter()
        try:
            context = self._context()
            adapter = BrokerExecutionAdapter(broker_id="alpaca_paper")
            self.assertIsNone(
                adapter.validate_entry_constraints(
                    context=context,
                    proposal={"symbol": "AAPL"},
                    notional_usd=10.0,
                )
            )
            entry_request = adapter.build_entry_order_request(
                context=context,
                proposal={"symbol": "AAPL"},
                client_order_id="entry-1",
                notional_usd=10.0,
                limit_buffer_bps=5.0,
            )
            exit_request = adapter.build_exit_order_request(
                context=context,
                symbol="AAPL",
                asset_class="equity",
                qty="1",
                reference_price=100.0,
                client_order_id="exit-1",
                limit_buffer_bps=5.0,
            )
            order = adapter.submit_order(context, order_request={"symbol": "AAPL"})
            adapter.cancel_order(context, order_id="order-1")
        finally:
            broker_bridge.get_broker_adapter = original

        self.assertEqual(entry_request["client_order_id"], "entry-1")
        self.assertEqual(exit_request["client_order_id"], "exit-1")
        self.assertEqual(order["id"], "order-1")
        self.assertEqual(
            calls,
            [
                ("validate", "test", "AAPL", 10.0),
                ("build_entry", "AAPL", "entry-1"),
                ("build_exit", "AAPL", "exit-1"),
                ("submit", "test", {"symbol": "AAPL"}),
                ("cancel", "test", "order-1"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
