from __future__ import annotations

from .base import ExecutionAdapter, ExecutionAdapterError, UnsupportedExecutionAdapterError
from .broker_bridge import BrokerExecutionAdapter

SUPPORTED_EXECUTION_BROKERS = frozenset({"alpaca_paper", "alpaca_live"})


def get_execution_adapter(context, broker_id: str) -> ExecutionAdapter:
    normalized = str(broker_id or "").strip().lower()
    if not normalized:
        raise ExecutionAdapterError("missing_broker_id")
    if normalized not in SUPPORTED_EXECUTION_BROKERS:
        raise UnsupportedExecutionAdapterError(
            f"Unsupported execution provider: {normalized}"
        )

    cache = context.metadata.setdefault("execution_adapters", {})
    cached = cache.get(normalized)
    if cached is not None:
        return cached

    adapter = BrokerExecutionAdapter(broker_id=normalized)
    cache[normalized] = adapter
    return adapter


__all__ = [
    "BrokerExecutionAdapter",
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "SUPPORTED_EXECUTION_BROKERS",
    "UnsupportedExecutionAdapterError",
    "get_execution_adapter",
]
