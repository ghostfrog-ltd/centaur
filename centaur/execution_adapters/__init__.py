"""Compatibility wrapper for execution adapters.

Implementation ownership has moved to `app.adapters.execution`.
"""

from app.adapters.execution import (
    BrokerExecutionAdapter,
    ExecutionAdapter,
    ExecutionAdapterError,
    SUPPORTED_EXECUTION_BROKERS,
    UnsupportedExecutionAdapterError,
    get_execution_adapter,
)

__all__ = [
    "BrokerExecutionAdapter",
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "SUPPORTED_EXECUTION_BROKERS",
    "UnsupportedExecutionAdapterError",
    "get_execution_adapter",
]

