"""Compatibility wrapper for execution adapter base types."""

from app.adapters.execution.base import (
    ExecutionAdapter,
    ExecutionAdapterError,
    UnsupportedExecutionAdapterError,
)

__all__ = [
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "UnsupportedExecutionAdapterError",
]

