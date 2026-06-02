# Heartbeat Pipeline

This folder is the human-readable start point for the scheduled control tick.
It mirrors the generated Mermaid flow:

- `pipeline.py` is the master heartbeat pipeline.
- `graph.py` owns the LangGraph/Pydantic `StateGraph`, node input model, node
  output model, graph state, and halt-on-error routing.
- `steps/` contains one folder per step in runtime order.
- Each step folder is its own pipeline. It has a `pipeline.py` entry plus
  `contract/` and `implementation/` subfolders.

The scheduled runner executes this heartbeat graph. Step implementation bodies
live in their owning step folders; shared cross-step helpers live in
`app/heartbeat/support.py`. Orchestration ownership stays here and must preserve
capital gates, broker routing, and execution behaviour.
