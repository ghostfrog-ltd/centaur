from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_RUNTIME_MODES = frozenset({"shadow", "paper", "live_dry", "live"})
VALID_ENVIRONMENTS = frozenset({"paper", "live"})


def normalize_runtime_mode(value: Any) -> str:
    normalized = str(value or "paper").strip().lower()
    if normalized in VALID_RUNTIME_MODES:
        return normalized
    return "paper"


def normalize_runtime_environment(value: Any, *, mode: str = "paper") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_ENVIRONMENTS:
        return normalized
    if normalize_runtime_mode(mode) in {"live", "live_dry"}:
        return "live"
    return "paper"


@dataclass(frozen=True, slots=True)
class ModeContext:
    mode: str
    environment: str

    @classmethod
    def from_config(cls, config: Any) -> "ModeContext":
        mode = normalize_runtime_mode(getattr(config, "centaur_mode", "paper"))
        environment = normalize_runtime_environment(
            getattr(config, "centaur_environment", ""),
            mode=mode,
        )
        return cls(mode=mode, environment=environment)

    @property
    def is_shadow(self) -> bool:
        return self.mode == "shadow"

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    @property
    def is_live_dry(self) -> bool:
        return self.mode == "live_dry"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def can_read_live_broker(self) -> bool:
        return self.mode in {"live", "live_dry"} and self.environment == "live"

    @property
    def can_mutate_live_broker(self) -> bool:
        return self.mode == "live" and self.environment == "live"

    @property
    def records_shadow_only(self) -> bool:
        return self.mode == "shadow"


def mode_context_from_config(config: Any) -> ModeContext:
    return ModeContext.from_config(config)
