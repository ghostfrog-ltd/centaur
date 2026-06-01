# Centaur Visualization Index

Centaur's production tick runner is currently an ordered Python pipeline. The
first LangGraph migration bridge now exists in `app.engine.control_graph`: it
wraps each current pipeline step as a typed Pydantic-backed LangGraph node while
preserving the existing runtime order and safety-gate names.

## Current Visuals

- `docs/visuals/current_pipeline.mmd`
  - Generated from `app.engine.pipelines.build_default_pipeline()`.
  - Shows every control tick step in the actual runtime order.
  - Groups nodes by runtime ownership lane and labels each node with its source
    runner reference, such as `app/engine/pipelines.py::market_scan`.

- `docs/visuals/current_langgraph_bridge.mmd`
  - Generated from `app.engine.control_graph.build_control_graph_mermaid()`.
  - Shows the current success path for the typed LangGraph bridge.

- `docs/visuals/entry_decision_funnel.mmd`
  - Hand-authored conceptual graph.
  - Shows the entry path from configured symbols to candidates, signals,
    fitness allocation, CFO approval, paper execution, and the same-as-paper
    live follower gate.

- `TICK_DECISION_FLOW.md`
  - Plain-English guide with inline Mermaid diagrams and code references.

## Update Mermaid Visuals

Run:

```bash
.venv-mac/bin/python scripts/update_mermaid_visuals.py
```

That rewrites generated Mermaid files such as:

```text
docs/visuals/current_pipeline.mmd
docs/visuals/current_langgraph_bridge.mmd
```

Use this after changing `build_default_pipeline()` or the control graph bridge
so visual orchestration docs do not drift from code. Use the check mode in CI or
before commits:

```bash
.venv-mac/bin/python scripts/update_mermaid_visuals.py --check
```

Generated orchestration visuals are not just pictures of labels. They must stay
married to implementation ownership: every runtime node should identify the
source module/function or typed graph owner that backs it, and the visual
grouping should reflect the relevant `app/` folder/domain boundary where
practical.

## LangGraph/Pydantic Migration Status

Done:

```text
LangGraph StateGraph definitions
Pydantic state, node input, and node output models
graph rendering/export from the runtime graph
tests that compare graph order to the old pipeline order during migration
```

Still pending:

```text
promote ControlPipelineRunner to execute the graph bridge by default
migrate shared TickContext dict fields into narrower Pydantic state models
split large legacy step bodies into typed domain nodes where it reduces risk
```
