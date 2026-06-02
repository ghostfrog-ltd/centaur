"""Execution planning and routing facade."""

from app.framework.adapters.execution import get_execution_adapter
from app.framework.runtime.execution_router import ExecutionRouter, RoutedOrder

__all__ = ["ExecutionRouter", "RoutedOrder", "get_execution_adapter"]
