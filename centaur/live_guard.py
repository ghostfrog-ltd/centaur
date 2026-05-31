"""Compatibility wrapper for live execution guard.

Implementation ownership has moved to `app.runtime.live_guard`.
"""

from app.runtime.live_guard import LiveRiskGuard, LiveRiskGuardError

__all__ = ["LiveRiskGuard", "LiveRiskGuardError"]

