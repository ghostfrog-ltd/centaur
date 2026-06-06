from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StorageLane:
    name: str
    purpose: str
    postgres_schema: str
    log_dir: str
    evidence_dir: str
    execution_mutations_allowed: bool


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """Core/paper/live storage contract for the adapter-first runtime.

    The shared core lane is where reviewed strategy evidence can remain available
    to both paper and live. Paper/live lanes are the execution and account-audit
    boundaries, so real-money rows never need to masquerade as paper training
    history.
    """

    core: StorageLane
    paper: StorageLane
    live: StorageLane

    def ensure_directories(self) -> None:
        """Create lane directories only when an operator workflow needs files."""
        for lane in (self.core, self.paper, self.live):
            Path(lane.log_dir).mkdir(parents=True, exist_ok=True)
            Path(lane.evidence_dir).mkdir(parents=True, exist_ok=True)
            Path(lane.evidence_dir).parent.joinpath("exports").mkdir(
                parents=True,
                exist_ok=True,
            )

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "core": _lane_as_dict(self.core),
            "paper": _lane_as_dict(self.paper),
            "live": _lane_as_dict(self.live),
        }


def storage_layout_from_config(config: Any) -> StorageLayout:
    active_schema = str(getattr(config, "postgres_schema", "") or "").strip()
    core_schema = str(getattr(config, "postgres_core_schema", "") or "").strip() or "core"
    paper_schema = str(getattr(config, "postgres_paper_schema", "") or "").strip() or "paper"
    live_schema = str(getattr(config, "postgres_live_schema", "") or "").strip() or "live"
    runtime_environment = str(
        getattr(config, "centaur_environment", "") or ""
    ).strip().lower()

    if active_schema:
        if runtime_environment == "paper":
            paper_schema = active_schema
        elif runtime_environment == "live":
            live_schema = active_schema

    return StorageLayout(
        core=StorageLane(
            name="core",
            purpose="shared reviewed evidence, strategy fitness, instruments, and reports",
            postgres_schema=core_schema,
            log_dir="storage/core/logs",
            evidence_dir="storage/core/evidence",
            execution_mutations_allowed=False,
        ),
        paper=StorageLane(
            name="paper",
            purpose="paper broker orders, paper account snapshots, paper execution evidence",
            postgres_schema=paper_schema,
            log_dir="storage/paper/logs",
            evidence_dir="storage/paper/evidence",
            execution_mutations_allowed=True,
        ),
        live=StorageLane(
            name="live",
            purpose="Alpaca Live orders, live account snapshots, live execution evidence",
            postgres_schema=live_schema,
            log_dir="storage/live/logs",
            evidence_dir="storage/live/evidence",
            execution_mutations_allowed=True,
        ),
    )


def _lane_as_dict(lane: StorageLane) -> dict[str, Any]:
    return {
        "name": lane.name,
        "purpose": lane.purpose,
        "postgres_schema": lane.postgres_schema,
        "log_dir": lane.log_dir,
        "evidence_dir": lane.evidence_dir,
        "execution_mutations_allowed": lane.execution_mutations_allowed,
    }
