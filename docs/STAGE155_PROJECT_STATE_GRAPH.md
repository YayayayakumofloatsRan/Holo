# Stage155 Project State Graph

Date: 2026-05-27

## Purpose

Stage155 adds a project state graph so Holo can carry project continuity as reusable state, separate from raw chat transcript recall. The graph records goals, tasks, decisions, artifacts, sources, assumptions, risks, results, open questions, and next actions as typed nodes with evidence.

This is the foundation for long-running engineering, research, math, physics, market research, and ProjectH-style work where "what are we trying to do, what did we decide, what blocks us, and what should happen next" must survive beyond the latest conversation window.

## Schema

```text
holo.stage155.project_state_graph.v1
```

## Node Types

```text
Project
Goal
Task
Subtask
Decision
OpenQuestion
Artifact
Source
Assumption
Risk
Result
NextAction
```

## Edge Types

```text
depends_on
blocks
supports
contradicts
completed_by
requires_tool
verified_by
reopened_by
derived_from
```

## Storage

`holo_host/project_state_graph.py` stores project state in local SQLite tables:

```text
project_state_nodes
project_state_edges
```

Each node keeps:

```text
project
node_id
node_type
title
summary
status
evidence
metadata
created_at
updated_at
```

Each edge keeps:

```text
project
edge_id
source_node_id
target_node_id
edge_type
evidence
metadata
created_at
updated_at
```

The graph is local and deterministic. It does not call providers, execute tools, start WeChat, or widen transport authority.

## Runtime Integration

Stage155 loads the current project graph before provider generation and adds it to the Stage150 context memory fabric:

```text
active_project
active_tasks
open_questions
latest_decisions
next_actions
blocked_items
```

After a reply is formed, explicit project-state statements in the current turn are detected deterministically. Examples:

```text
Task: build project state graph.
Decision: keep it local and deterministic.
Open question: how should visual replay consume it?
Risk: noisy chat should not become project truth.
Next action: run Stage155 tests.
```

Detected updates are applied to the project graph and propagated into:

```text
project_state_graph
project_state_update
```

These fields appear in reply JSON, outgoing metadata, archive/observe metadata, and `ReplyPlan.debug` when available.

## CLI

Stage155 adds read-only inspection commands:

```powershell
python -m holo_host project-state --project Holo --summary
python -m holo_host project-state --project Holo --open-loops
python -m holo_host project-state --project Holo --next-actions
```

Add `--json` to print the raw report.

## Stage135 Topology

Stage135 can now render a `project_state_graph` node with counters:

```text
project_state_graph_node_count
project_state_graph_project
project_state_graph_open_loop_count
project_state_graph_next_action_count
```

The node connects structured project continuity to the context memory fabric and provider packet framing.

## Boundaries

Stage155 does not:

- start WeChat
- widen transport authority
- add provider calls
- execute tools
- add self-memory writes
- mutate model weights or durable policy
- treat generic chat as project truth without explicit project-state cues

Project state is a reusable local state graph, not a replacement for memory, archive, or tool evidence ledgers.
