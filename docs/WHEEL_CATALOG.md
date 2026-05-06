# Wheel Catalog

This is the practical wheel-by-wheel catalog for new threads.

For each wheel:
- what it does
- who calls it
- how to inspect it
- what not to break

## 1. WeChat Watcher

Purpose:
- observe WeChat UI
- package turns and artifacts
- call the host
- send already-decided replies

Called by:
- `windows_helper/start_holo_wechat.ps1`

Inspect with:
- `scripts/holo-status.sh`
- `.holo_runtime/wechat-helper/transport_state.live.json`
- `.holo_runtime/wechat-helper/receipts/pyweixin_watcher.log`

Do not:
- hand-edit runtime config for normal work
- change transport mode casually
- let watcher invent reply text or second-guess host decisions

High-risk files:
- `windows_helper/wechat_helper.live.json`
- `windows_helper/start_holo_wechat.ps1`
- `windows_helper/wechat_helper.py`

## 2. Event Bus

Purpose:
- hold incoming events before subject deliberation

Called by:
- `reply_api`
- artifact ingest
- image ingest

Inspect with:
- runtime SQLite store
- `trace-deliberation-ledger`

Do not:
- short-circuit event ingestion straight to reply generation

High-risk files:
- `holo_host/reply_api.py`
- `holo_host/store.py`

## 3. Consciousness Ledger

Purpose:
- record event, state delta, selected action, rationale, and outcome

Called by:
- subject kernel
- outcome appraisal
- world/goal/autobiographical calibration paths

Inspect with:
- `python3 -m holo_host trace-deliberation-ledger --thread-key <thread>`

Do not:
- treat it as optional debug
- write fake reasons that do not match actual action selection

High-risk files:
- `holo_host/memory_bridge.py`
- `holo_host/store.py`

## 4. Memory Fabric

Purpose:
- archive, graph, vector, activation

Called by:
- reply path
- recall path
- world calibration
- autobiographical consolidation

Inspect with:
- `python3 -m holo_host trace-hybrid-recall ...`
- `python3 -m holo_host show-activation-state ...`
- `python3 -m holo_host vector-health`

Do not:
- make archive the only continuity source
- bypass graph/vector writeback on new memory paths

High-risk files:
- `holo_host/memory_bridge.py`
- `holo_host/mind_graph.py`
- `holo_memory_library/`

## 5. World / Autobiographical / Goal State

Purpose:
- encode social predictions
- encode self-history
- encode long-horizon goals

Called by:
- subject kernel
- counterfactual simulation
- outcome appraisal
- background loops

Inspect with:
- `show-world-state`
- `show-autobiographical-state`
- `show-goal-state`
- `trace-self-continuity`
- `trace-goal-arbitration`

Do not:
- downgrade them to display-only metadata
- reset them per turn

High-risk files:
- `holo_host/memory_bridge.py`
- `holo_host/mind_graph.py`
- `holo_host/daemon.py`

## 6. Subject Kernel / Action Market

Purpose:
- turn state into intent and action selection

Called by:
- reply path
- proactive path
- resistance path
- lookup / recall / operator decision paths

Inspect with:
- `show-intent-state`
- `show-action-market`
- `trace-action-selection`

Do not:
- add direct reply paths that bypass selected action
- let expression budget be overridden by a generic splitter

High-risk files:
- `holo_host/memory_bridge.py`
- `holo_host/processors.py`

## 7. Operator Bus

Purpose:
- bounded self-fix / shadow execution

Called by:
- background operator loops
- explicit operator probe/cycle

Inspect with:
- `operator-probe`
- `run-operator-cycle`
- `show-brain-status`

Do not:
- allow live repo hot edits
- bypass shadow workspace review

High-risk files:
- `holo_host/operator_bus.py`
- `holo_host/brain_ops.py`

## 8. Provider Abstraction

Purpose:
- standardize model invocation across Codex CLI, Responses, and OpenAI-compatible HTTP

Called by:
- all processor tasks through `CodexRunner`

Inspect with:
- `show-processor-routing`
- `show-provider-status`
- `show-processor-mesh`

Do not:
- add new direct CLI/HTTP model calls outside the provider abstraction
- silently change task semantics during fallback

High-risk files:
- `holo_host/codex_runner.py`
- `holo_host/config.py`
- `holo_host/processors.py`

## 9. Token Usage Ledger

Purpose:
- persist usage/timing per processor task

Called by:
- `CodexRunner`

Inspect with:
- `show-usage-ledger --limit 50`
- `accept-processor-fabric`

Do not:
- rely on guesswork when the ledger can answer the question
- drop usage writes on fallback/error paths

High-risk files:
- `holo_host/store.py`
- `holo_host/codex_runner.py`

## 10. Typical Safe Workflow

1. Read `HOLO_HANDOFF.md`.
2. Read watcher contract.
3. Read this file.
4. Check status and provider routing.
5. Make one focused change.
6. Run targeted tests.
7. Re-run acceptance and update docs.
