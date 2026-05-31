"""Alpaca Live execution adapter facade."""

from .broker_bridge import BrokerExecutionAdapter


class AlpacaLiveExecutionAdapter(BrokerExecutionAdapter):
    def __init__(self) -> None:
        super().__init__(broker_id="alpaca_live")


__all__ = ["AlpacaLiveExecutionAdapter"]
