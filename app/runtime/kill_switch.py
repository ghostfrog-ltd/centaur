"""Kill-switch path helpers for the live lane."""

from pathlib import Path

LIVE_KILL_SWITCH_PATH = Path("storage/live/KILL_LIVE_TRADING")


def live_kill_switch_active(path: Path = LIVE_KILL_SWITCH_PATH) -> bool:
    return path.exists()


__all__ = ["LIVE_KILL_SWITCH_PATH", "live_kill_switch_active"]

