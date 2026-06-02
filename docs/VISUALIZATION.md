# Centaur Visualization Index

Centaur's scheduled heartbeat is a LangGraph/Pydantic orchestration graph
owned by `app.heartbeat.graph`. It preserves the existing runtime
order and safety-gate names while making each heartbeat step folder the visible
node ownership surface.

## Current Visuals

- `docs/visuals/current_pipeline.mmd`
  - Generated from `app.framework.engine.pipelines.build_default_pipeline()`, which now
    delegates to `app.heartbeat.pipeline`.
  - Shows every control tick step in the actual runtime order.
  - Groups nodes by runtime ownership lane and labels each node with its
    heartbeat step-pipeline reference, such as
    `app/heartbeat/steps/23_market_scan/pipeline.py::run`.

- `docs/visuals/current_langgraph_bridge.mmd`
  - Generated from
    `app.heartbeat.graph.build_heartbeat_cron_graph_mermaid()`.
  - Shows the current success path for the typed heartbeat LangGraph.

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

Use this after changing `app/heartbeat/pipeline.py`,
`app/heartbeat/graph.py`, any heartbeat step folder, or
`build_default_pipeline()` so visual orchestration docs do not drift from code.
Use the check mode in CI or before commits:

```bash
.venv-mac/bin/python scripts/update_mermaid_visuals.py --check
```

Generated orchestration visuals are not just pictures of labels. They must stay
married to implementation ownership: every runtime node should identify the
source module/function or typed graph owner that backs it. For the scheduled
heartbeat, the first source reference is the step pipeline under
`app/heartbeat/steps/`, and the typed graph owner is
`app/heartbeat/graph.py`.

## LangGraph/Pydantic Migration Status

Done:

```text
LangGraph StateGraph definitions
Pydantic state, node input, and node output models
graph rendering/export from the runtime graph
ControlPipelineRunner execution through the heartbeat LangGraph
tests that compare graph order to the heartbeat pipeline order
```

Still pending:

```text
migrate shared TickContext dict fields into narrower Pydantic state models
split large step bodies into typed domain nodes where it reduces risk
```
