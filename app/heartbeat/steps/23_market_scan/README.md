# 23 market.scan

This folder is its own heartbeat pipeline for `market.scan`.

- `pipeline.py` is the step pipeline entry imported by the master heartbeat pipeline.
- `node/` contains the LangGraph node runner.
- `contract/` contains the typed node contract and audit metadata.
- `implementation/` contains the current behaviour-preserving implementation adapter.
