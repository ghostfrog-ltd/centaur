# 15 risk.trading212_paper_daily_protection

This folder is its own heartbeat pipeline for `risk.trading212_paper_daily_protection`.

- `pipeline.py` is the step pipeline entry imported by the master heartbeat pipeline.
- `node/` contains the LangGraph node runner.
- `contract/` contains the typed node contract and audit metadata.
- `implementation/` contains the current behaviour-preserving implementation adapter.
