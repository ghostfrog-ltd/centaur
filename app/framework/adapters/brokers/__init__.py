from __future__ import annotations

from .alpaca import AlpacaBrokerAdapter, AlpacaLiveBrokerAdapter
from .base import BrokerAdapter, BrokerAdapterError, UnsupportedBrokerError
from .ig import IgBrokerAdapter
from .trading212 import Trading212LiveBrokerAdapter, Trading212PaperBrokerAdapter


def get_broker_adapter(context, broker_id: str) -> BrokerAdapter:
    normalized = str(broker_id or "").strip().lower()
    if not normalized:
        raise UnsupportedBrokerError("Broker id is required.")

    cache = context.metadata.setdefault("broker_adapters", {})
    cached = cache.get(normalized)
    if cached is not None:
        return cached

    if normalized == AlpacaBrokerAdapter.broker_id:
        adapter: BrokerAdapter = AlpacaBrokerAdapter()
    elif normalized == AlpacaLiveBrokerAdapter.broker_id:
        adapter = AlpacaLiveBrokerAdapter()
    elif normalized == IgBrokerAdapter.broker_id:
        adapter = IgBrokerAdapter.from_config(context.config)
    elif normalized == Trading212PaperBrokerAdapter.broker_id:
        adapter = Trading212PaperBrokerAdapter.from_config(context.config)
    elif normalized == Trading212LiveBrokerAdapter.broker_id:
        adapter = Trading212LiveBrokerAdapter.from_config(context.config)
    else:
        raise UnsupportedBrokerError(f"Unsupported broker id: {normalized}")

    cache[normalized] = adapter
    return adapter


__all__ = [
    "AlpacaBrokerAdapter",
    "AlpacaLiveBrokerAdapter",
    "BrokerAdapter",
    "BrokerAdapterError",
    "IgBrokerAdapter",
    "Trading212LiveBrokerAdapter",
    "Trading212PaperBrokerAdapter",
    "UnsupportedBrokerError",
    "get_broker_adapter",
]
