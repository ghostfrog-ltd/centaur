"""Order intent/result facades."""

from typing import Any

from app.runtime.execution_router import RoutedOrder

OrderIntent = dict[str, Any]

__all__ = ["OrderIntent", "RoutedOrder"]
