# 24 slow.enrichment_queue

This folder is its own heartbeat pipeline for `slow.enrichment_queue`.

- `pipeline.py` is the step pipeline entry imported by the master heartbeat pipeline.
- `contract/` contains the typed node contract and audit metadata.
- `implementation/` contains the advisory queue enqueue/start implementation.
