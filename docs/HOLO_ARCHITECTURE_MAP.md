# Holo Architecture Map

This document is the compact map of the current live architecture.

Read this after `HOLO_HANDOFF.md` and before touching runtime code.

## 1. Topology

- WSL repo is the authoritative kernel.
- Windows is only the transport shell.
- The WeChat live transport on this machine is `pyweixin_dialog`.
- The current architecture is:
  - Perception Bus
  - Memory Fabric
  - Self / Affect / Goal / World state
  - Subject Kernel
  - Action Market
  - Execution Adapters
  - Consciousness Ledger
  - Processor Fabric

## 2. Runtime Layers

### Perception Bus

Purpose:
- accept inbound events
- normalize turns
- enqueue artifacts
- never decide replies on its own

Key files:
- `holo_host/reply_api.py`
- `windows_helper/wechat_helper.py`
- `windows_helper/start_holo_wechat.ps1`

### Memory Fabric

Purpose:
- durable archive
- graph/state materialization
- vector recall
- activation cache

Key files:
- `holo_memory_library/`
- `holo_host/memory_bridge.py`
- `holo_host/mind_graph.py`

Storage:
- JSONL archive and stores
- SQLite mind graph
- Milvus-backed vector store
- SQLite-backed activation/runtime state

### Subject State

Purpose:
- keep the persistent internal state that makes Holo more than one request/response pair

State families:
- `self_model`
- `autobiographical_state`
- `goal_state`
- `world_state`
- `affect_state`
- `drive_state`
- `value_state`
- `conflict_state`
- `game_state`

Key files:
- `holo_host/memory_bridge.py`
- `holo_host/mind_graph.py`
- `holo_host/models.py`

### Subject Kernel + Action Market

Purpose:
- turn state into intent
- rerank actions
- choose `silence`, `defer`, `reply`, `lookup`, `history_refresh`, `operator`, and proactive actions

Key files:
- `holo_host/memory_bridge.py`
- `holo_host/processors.py`
- `holo_host/brain_ops.py`
- `holo_host/operator_bus.py`

### Execution Adapters

Purpose:
- execute the action that the subject kernel already chose

Examples:
- send reply bubbles
- run external lookup
- run history refresh
- ingest image
- dispatch initiative

Key files:
- `holo_host/reply_api.py`
- `windows_helper/`
- `holo_host/capabilities.py`

### Consciousness Ledger

Purpose:
- persistent causal trace of what happened, what state changed, what action was chosen, and why

Key files:
- `holo_host/memory_bridge.py`
- `holo_host/store.py`

### Processor Fabric

Purpose:
- route each cognition task to the right lane and provider
- record usage and timing

Key files:
- `holo_host/codex_runner.py`
- `holo_host/config.py`
- `holo_host/store.py`

## 3. Processor Fabric

### Lanes

- `kernel_xhigh`
  - highest-value deliberation
  - default model: `gpt-5.4`
  - default reasoning: `xhigh`
- `subject_main`
  - normal subject work
  - default model: `gpt-5.4`
  - default reasoning: `medium`
- `micro_fast`
  - low-density helper cognition
  - default model: `gpt-5.4-mini`
  - default reasoning: `low`

### Providers

- `CodexCliProvider`
  - primary path
- `ResponsesProvider`
  - first fallback
- `OpenAICompatibleProvider`
  - second fallback

### Usage Ledger

Every processor call should land in `processor_usage_ledger` with:
- task type
- lane
- provider
- model
- reasoning effort
- timing
- token usage or estimated usage

## 4. Live Decision Flow

1. WeChat watcher observes an event.
2. `reply_api` ingests the event.
3. Memory/state layers update.
4. Subject kernel assembles intent/action state.
5. Action market chooses the winner.
6. Only then does execution happen.
7. Outcome appraises back into the ledger and state.

Important:
- reply generation is now downstream of action selection
- watcher is not allowed to become a second decision-maker

## 5. High-Risk Contracts

- watcher path and runtime config generation
- `/reply` and `/ingest-artifact` semantics
- path normalization between Windows and WSL
- processor provider abstraction
- processor usage ledger schema
- state layers that participate in subject deliberation

## 6. Primary Observability

- `python3 -m holo_host show-brain-status`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host show-usage-ledger --limit 50`
- `python3 -m holo_host show-world-state --thread-key <thread>`
- `python3 -m holo_host show-autobiographical-state`
- `python3 -m holo_host show-goal-state`

## 7. Do Not Misread

- the watcher is not the brain
- the provider is not the self
- the archive is not the only memory
- the ledger is not only a debug log; it is part of subject continuity
