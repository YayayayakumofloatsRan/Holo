# Stage137 Latency Trace Gate

Date: 2026-05-24

## Problem

Stage136 simulated dialogue showed high wall-clock latency. The timing split showed two different contributors:

1. The simulation method cold-started `python -m holo_host chat --once` for every turn, adding process and service startup overhead.
2. The live reply processor ran `recall_reconstruct` too often. The previous gate triggered reconstruction whenever a recall-tier packet carried activation trace ids or episodic recall lines, even when the user asked for current I-state topology or packet flow rather than a memory-origin answer.

This made ordinary self-state/topology turns pay for a deep memory reconstruction packet. It also made the system harder to inspect, because Stage135 topology was present in processor debug data but was not exposed by the reply API result.

## Fix

- Added an explicit recall reconstruction gate in `holo_host/processors.py`.
  - It now requires a real memory reconstruction signal: `recall_reason`, `query_focus`, `local_memory_requested`, `recall_reconstruct_requested`, or direct memory/origin query text.
  - Existing activation trace ids and episodic lines remain useful inputs after that request gate passes.
  - Explicit memory-origin queries still run `recall_reconstruct`.
- Exposed Stage135 I-state topology through `holo_host/reply_api.py`.
  - Reply JSON now includes `stage135_i_state_prompt_frame`.
  - Reply JSON now includes `stage135_i_state_topology`.
  - Outbound metadata and archived memory metadata carry the same trace.
- Added `/topology` and `/topo` to interactive CLI.
  - The command summarizes the latest reply topology as node count, edge count, Stage132 round count, continuation decision, and channel counts.
  - With `/json on`, it prints the raw Stage132 and Stage135 trace sections.

## Expected Runtime Effect

Topology and current internal-flow questions can still use fast/deep provider packets when the Stage124/Stage132 policy asks for them, while avoiding a separate memory reconstruction packet unless the turn actually asks Holo to recover memory, origin, archive, or remembered facts.

This keeps useful internal calls and removes a broad accidental trigger. It should reduce latency for many self-state and visualization turns, and it gives the operator a live CLI view into whether the reply carried a topology trace.

## Verification

Fresh targeted verification:

```powershell
python -m pytest tests/test_stage135_i_state_topology.py -q --basetemp .holo_runtime\pytest-tmp-stage135
python -m pytest tests/test_cli_chat.py -q --basetemp .holo_runtime\pytest-tmp-cli-all
python -m pytest tests/test_stage132_progressive_conscious_stream.py tests/test_stage131_thought_flow_trace.py -q --basetemp .holo_runtime\pytest-tmp-flow
python -m pytest tests/test_holo_host.py::ReplyServiceTests::test_reply_probe_compares_graph_led_and_legacy_drafts tests/test_holo_host.py::ReplyServiceTests::test_reply_service_exposes_stage135_i_state_topology_trace -q --basetemp .holo_runtime\pytest-tmp-reply
python -m pytest tests/test_stage124_fast_deep_thought_loop.py tests/test_stage17_realtime_runtime.py tests/test_stage18_dual_speed_reflex.py -q --basetemp .holo_runtime\pytest-tmp-fast-deep
python -m pytest tests/test_stage20_temporal_commitments.py tests/test_stage24_scene_state.py tests/test_stage28_multimodal_homeostatic_kernel.py -q --basetemp .holo_runtime\pytest-tmp-memory-routes
```

Observed results:

- Stage135 topology and recall gate tests: `6 passed`
- CLI chat tests: `9 passed`
- Stage131/132 flow tests: `15 passed`
- Reply service targeted tests: `2 passed`
- Stage124/17/18 routing tests: `17 passed`
- Stage20/24/28 memory-route tests: `15 passed`

## Manual Use

Inside interactive CLI:

```text
holo> your message
holo> /topology
```

Expected compact output:

```text
[last_reply] stage135 nodes=<n> edges=<n> rounds=<n> continue=<decision> channels=<channel counts>
```
