"""Compatibility wrapper for execution routing.

Implementation ownership has moved to `app.runtime.execution_router`.
"""

from app.runtime.execution_router import ExecutionAdapterFactory, ExecutionRouter, RoutedOrder

__all__ = ["ExecutionAdapterFactory", "ExecutionRouter", "RoutedOrder"]

