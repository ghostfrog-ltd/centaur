"""Risk-gate pipeline facade."""

from app.framework.engine.pipelines import (
    daily_protection,
    live_risk_cfo_gate,
    risk_cfo_gate,
    trailing_drawdown_observer,
)

__all__ = [
    "daily_protection",
    "live_risk_cfo_gate",
    "risk_cfo_gate",
    "trailing_drawdown_observer",
]
