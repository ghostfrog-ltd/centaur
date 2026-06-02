from __future__ import annotations

from datetime import datetime
import unittest

from app.framework.engine.pipelines import _find_most_protective_managed_entry_order


class ManagedExitEntrySelectionTests(unittest.TestCase):
    def test_aggregated_position_uses_highest_still_open_stop(self) -> None:
        orders = [
            self._buy(
                order_id="newer",
                submitted_at="2026-06-01T03:43:27+01:00",
                stop=8.8933577,
            ),
            self._buy(
                order_id="older",
                submitted_at="2026-06-01T00:04:21+01:00",
                stop=8.92726405,
            ),
        ]

        selected = _find_most_protective_managed_entry_order(
            symbol="LINK/USD",
            orders=orders,
            broker_id="alpaca_paper",
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["order_id"], "older")
        self.assertEqual(selected["raw_json"]["managed_entry_selection"], "most_protective_open_lot")
        self.assertEqual(selected["raw_json"]["managed_open_lots_considered"], 2)

    def test_closed_older_lot_is_not_selected(self) -> None:
        orders = [
            self._buy(
                order_id="older",
                submitted_at="2026-06-01T00:04:21+01:00",
                stop=8.92726405,
            ),
            self._sell(
                order_id="close-older",
                submitted_at="2026-06-01T01:00:00+01:00",
            ),
            self._buy(
                order_id="newer",
                submitted_at="2026-06-01T03:43:27+01:00",
                stop=8.8933577,
            ),
        ]

        selected = _find_most_protective_managed_entry_order(
            symbol="LINK/USD",
            orders=orders,
            broker_id="alpaca_paper",
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["order_id"], "newer")
        self.assertNotIn("managed_entry_selection", selected["raw_json"])

    def test_unmanaged_open_position_has_no_managed_plan(self) -> None:
        selected = _find_most_protective_managed_entry_order(
            symbol="AMZN",
            orders=[
                {
                    "order_id": "manual",
                    "broker_id": "alpaca_paper",
                    "symbol": "AMZN",
                    "side": "buy",
                    "filled_qty": 0.036,
                    "submitted_at": datetime.fromisoformat("2026-05-29T15:00:24+01:00"),
                    "raw_json": {},
                }
            ],
            broker_id="alpaca_paper",
        )

        self.assertIsNone(selected)

    def _buy(self, *, order_id: str, submitted_at: str, stop: float) -> dict:
        return {
            "order_id": order_id,
            "broker_id": "alpaca_paper",
            "symbol": "LINK/USD",
            "side": "buy",
            "filled_qty": 1.0,
            "submitted_at": datetime.fromisoformat(submitted_at),
            "stop_loss_price": stop,
            "raw_json": {"planned_stop_loss_price": stop},
        }

    def _sell(self, *, order_id: str, submitted_at: str) -> dict:
        return {
            "order_id": order_id,
            "broker_id": "alpaca_paper",
            "symbol": "LINK/USD",
            "side": "sell",
            "filled_qty": 1.0,
            "submitted_at": datetime.fromisoformat(submitted_at),
            "raw_json": {},
        }


if __name__ == "__main__":
    unittest.main()
