"""Alpaca Paper execution adapter facade."""

from .broker_bridge import BrokerExecutionAdapter


class AlpacaPaperExecutionAdapter(BrokerExecutionAdapter):
    def __init__(self) -> None:
        super().__init__(broker_id="alpaca_paper")


__all__ = ["AlpacaPaperExecutionAdapter"]
