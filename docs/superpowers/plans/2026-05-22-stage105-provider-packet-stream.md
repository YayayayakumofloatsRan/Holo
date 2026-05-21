# Stage105 Provider Packet Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable Stage105 controller that turns Holo's theory of finite provider packets into a concrete loop: build packet, send or skip, distill output, decide whether to continue, stop, reply, or route to tools.

**Architecture:** Stage105 is a deterministic planning layer above provider APIs. It does not train a base model; it computes a packet stream plan from an existing mind packet, Stage104 attractors, action state, uncertainty, tool affordances, token budget, and timing pressure.

**Tech Stack:** Python, existing `holo_host` CLI, `MemoryBridge`, pytest, JSON artifacts.

---

### Task 1: Stage105 Behavior Contract

**Files:**
- Create: `tests/test_stage105_provider_packet_stream.py`
- Create: `holo_host/stage105_provider_packet_stream.py`

- [ ] **Step 1: Write failing tests**

Test cases:

```python
def test_stage105_broad_recall_uses_multi_packet_stream():
    packet = {"stage104": {"context_learning_visible": True}, "semantic_attractor_lines": ["A", "B"], "uncertainty_level": 0.72, "selected_action": {"action_type": "reply_once"}}
    plan = stage105_packet_stream_plan(packet, query="回忆任何事情？", max_packets=4)
    assert plan["packet_count"] == 3
    assert [step["packet_role"] for step in plan["packets"]] == ["context_seed", "deliberation_delta", "reply_commit"]
```

```python
def test_stage105_stops_when_confident_and_no_tool_needed():
    packet = {"uncertainty_level": 0.12, "selected_action": {"action_type": "reply_once"}, "semantic_attractor_lines": ["A"]}
    plan = stage105_packet_stream_plan(packet, query="继续", max_packets=4)
    assert plan["packet_count"] == 1
    assert plan["stop_reason"] == "sufficient_context"
```

```python
def test_stage105_tool_affordance_preempts_more_provider_packets():
    packet = {"uncertainty_level": 0.82, "selected_action": {"action_type": "external_lookup", "why_now": "needs current facts"}, "lookup_reason": "needs current facts"}
    plan = stage105_packet_stream_plan(packet, query="查一下最新状态", max_packets=4)
    assert plan["next_action"] == "tool_request"
    assert plan["tool_requests"][0]["name"] == "external_lookup"
```

- [ ] **Step 2: Verify red**

Run:

```powershell
pytest -q tests\test_stage105_provider_packet_stream.py --basetemp .holo_runtime\pytest-stage105-red
```

Expected: import failure for `holo_host.stage105_provider_packet_stream`.

- [ ] **Step 3: Implement minimal module**

Create `stage105_packet_stream_plan(packet, query, max_packets=4, packet_budget_tokens=2400, deadline_ms=None)`.

Required output keys:

- `schema`
- `stage`
- `query`
- `packet_count`
- `packets`
- `next_action`
- `stop_reason`
- `tool_requests`
- `policy`

- [ ] **Step 4: Verify green**

Run:

```powershell
pytest -q tests\test_stage105_provider_packet_stream.py --basetemp .holo_runtime\pytest-stage105
```

Expected: all tests pass.

### Task 2: Runtime Surfaces

**Files:**
- Modify: `holo_host/memory_bridge.py`
- Modify: `holo_host/cli.py`
- Modify: `tests/test_stage105_provider_packet_stream.py`

- [ ] **Step 1: Extend tests for inspect and CLI**

Add tests that assert:

- `inject_stage105_packet_stream(packet, plan)` adds `packet["stage105"]`.
- CLI `stage105-packet-stream --query ...` returns JSON with `stage=105`.

- [ ] **Step 2: Add inspect integration**

In `MemoryBridge._finalize_stage2_packet()`, compute Stage105 plan after Stage104 injection and store it at:

- `packet["stage105"]`
- `packet["state"]["stage105"]`

Expose it in `inspect_mind`.

- [ ] **Step 3: Add CLI**

Add command:

```powershell
python -m holo_host stage105-packet-stream --query "回忆任何事情？" --thread-key holo_cli:main --chat-name HoloCLI --channel holo_cli
```

### Task 3: Theory and Visualization Artifact

**Files:**
- Create: `docs/STAGE105_PROVIDER_PACKET_STREAM.md`
- Create: `docs/PROGRESS_2026-05-22_STAGE105_PROVIDER_PACKET_STREAM.md`

- [ ] **Step 1: Write theory-to-practice contract**

Document the mapping:

- Theory: consciousness as finite-context packet stream.
- Practice: provider packet count, stop policy, tool policy, compression policy.
- Visualization: packet nodes, attractor edges, tool-request branches, stop condition.

- [ ] **Step 2: Record live or local evidence**

Record outputs for:

```powershell
python -m holo_host stage105-packet-stream --query "回忆任何事情？"
python -m holo_host inspect-mind --query "回忆任何事情？" --thread-key holo_cli:main --chat-name HoloCLI --channel holo_cli
```

### Task 4: Verification and Commit

**Files:**
- All Stage105 files.

- [ ] **Step 1: Run focused tests**

```powershell
pytest -q tests\test_stage105_provider_packet_stream.py tests\test_stage104_context_learning.py tests\test_cli_chat.py tests\test_cli_live_api.py --basetemp .holo_runtime\pytest-stage105-focused
```

- [ ] **Step 2: Run hygiene**

```powershell
git diff --check
python scripts\check_public_release_hygiene.py
```

- [ ] **Step 3: Commit**

```powershell
git add docs\STAGE105_PROVIDER_PACKET_STREAM.md docs\PROGRESS_2026-05-22_STAGE105_PROVIDER_PACKET_STREAM.md docs\superpowers\plans\2026-05-22-stage105-provider-packet-stream.md holo_host\stage105_provider_packet_stream.py holo_host\memory_bridge.py holo_host\cli.py tests\test_stage105_provider_packet_stream.py
git commit -m "Add Stage105 provider packet stream planner"
```
