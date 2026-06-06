# Project Centaur Current State
Last compacted: 2026-06-05

## Runtime
- Modes: `shadow`, `paper`, `live_dry`, `live`.
- `paper` skips live broker mutation; `live_dry` records intended live actions only.
- Live is an independent lane controlled by `LIVE_*` dials, not a blind copy of paper.

## Trading Boundary
- Shadow/learning stays broad and has no trade authority.
- Paper/live use fitness-only admission on the fast execution path.
- `ExecutionRouter` and `LiveRiskGuard` remain the final mutation safety boundaries.

## Candidate Flow
- `market.scan` ranks the universe.
- Top `DISCOVERY_TARGET_COUNT` candidates go through fast enrichment, strategy evaluation, fitness, and paper/live gates.
- Leftovers go to `slow.enrichment_queue` for advisory evidence only with `trade_authority=none`.
- Adaptive threshold advice is async; the hot tick uses cached threshold state only.

## Storage / Config
- PostgreSQL is the active operations store.
- Storage model is shared `core` evidence plus separate `paper` / `live` execution lanes.
- Runtime config is `.env` only; `PAPER_*` governs paper, `LIVE_*` governs live.

## Active Packages
- `app/` is the only active runtime package.
- Heartbeat orchestration lives in `app/heartbeat/`.
- Compatibility facade: `app/framework/engine/control_graph.py`.

## Ops
- `launchd` runs `main.py --heartbeat-service --interval-seconds 10` via `.venv-mac`.
- Ticks are sequential and reload `.env` / runtime storage each loop.
- Dashboard refresh is separate from the normal control tick.

## Useful Commands
- `.venv-mac/bin/python main.py --status`
- `.venv-mac/bin/python main.py --evidence-report`
- `.venv-mac/bin/python main.py --strategy-health --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --paper-exit-review --strategy-id <strategy>`
- `.venv-mac/bin/python main.py --holding-window-advice`
- `.venv-mac/bin/python main.py --storage-separation-report`
