# Stage48 Bionic Memory Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a biomimetic memory scheduler that separates working memory, hippocampal indices, cortical schemas, salience gates, and consolidation targets before prompt/context scheduling.

**Architecture:** The scheduler is a prompt/context layer over existing Holo memory stores. It reads the current `mind_packet`, produces a bounded `bionic_memory_schedule`, renders stable cortical schema into the provider-cache prefix, renders volatile working/hippocampal content into dynamic prompt context, and exposes context-budget metadata without changing live memory storage or transport authority.

**Tech Stack:** Python, existing `MemoryBridge`, `render_chat_prompt()`, `plan_processor_context()`, pytest, Stage46 stress harness.

---

### Task 1: Scheduler Contract

**Files:**
- Create: `holo_host/bionic_memory_scheduler.py`
- Test: `tests/test_bionic_memory_scheduler.py`

- [x] **Step 1: Write the failing tests**

Expected tests:

```python
def test_scheduler_separates_cortical_schema_from_working_memory():
    packet = {
        "identity_core": {"lines": ["identity=yes"]},
        "reply_constraints": {"lines": ["never overclaim vision"]},
        "active_thread_state": {"summary": "current thread is hot"},
        "stage25": {"used": True, "reentry_hint": "return to symbol"},
        "activation_state": {"heat": 0.7, "motifs": ["symbol"]},
    }
    schedule = build_bionic_memory_schedule(packet, query="continue the symbol")
    assert schedule["cortical_schema"]["stable_prefix_lines"]
    assert schedule["working_memory"]["dynamic_lines"]
    assert schedule["hippocampal_index"]["dynamic_lines"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests\test_bionic_memory_scheduler.py -q`

Expected: import failure for missing `holo_host.bionic_memory_scheduler`.

- [ ] **Step 3: Implement minimal scheduler**

Create `build_bionic_memory_schedule(packet, query)` with deterministic bounded outputs:

- `working_memory.dynamic_lines`
- `hippocampal_index.dynamic_lines`
- `cortical_schema.stable_prefix_lines`
- `salience_gate`
- `consolidation_targets`
- `provider_prefix_lines`
- `dynamic_context_lines`

- [ ] **Step 4: Run scheduler tests**

Run: `python -m pytest tests\test_bionic_memory_scheduler.py -q`

Expected: all tests pass.

### Task 2: Packet and Prompt Integration

**Files:**
- Modify: `holo_host/memory_bridge.py`
- Modify: `holo_host/processors.py`
- Test: `tests/test_memory_fabric.py`
- Test: `tests/test_context_scheduler.py`

- [ ] **Step 1: Add failing packet/prompt tests**

Expected behavior:

- `MemoryBridge.sidecar_packet()` exposes `bionic_memory_schedule`.
- `render_chat_prompt()` includes stable `Cortical Memory Schema` before dynamic chat fields.
- `render_chat_prompt()` includes dynamic `Working Memory` and `Hippocampal Index` after current dynamic fields.
- Stable provider prefix digest remains equal across different user turns.

- [ ] **Step 2: Run tests to verify failures**

Run:

```powershell
python -m pytest tests\test_memory_fabric.py::MemoryFabricTests::test_sidecar_packet_v11_exposes_autobiography_and_goal_layers tests\test_context_scheduler.py -q
```

- [ ] **Step 3: Wire scheduler into packet finalization and prompt rendering**

Implementation:

- Import `build_bionic_memory_schedule` in `memory_bridge.py`.
- Build schedule near the end of `_finalize_stage2_packet()` after goal/action/intention fields are present.
- Import prompt line helpers in `processors.py`.
- Render cortical schema before `Current User Turn`.
- Render working memory and hippocampal index after dynamic fields.

- [ ] **Step 4: Run integration tests**

Run:

```powershell
python -m pytest tests\test_bionic_memory_scheduler.py tests\test_memory_fabric.py tests\test_context_scheduler.py -q
```

### Task 3: Context Schedule Metadata

**Files:**
- Modify: `holo_host/context_scheduler.py`
- Modify: `holo_host/processors.py`
- Test: `tests/test_context_scheduler.py`

- [ ] **Step 1: Add failing context metadata test**

Expected behavior:

- `plan_processor_context(..., memory_schedule=schedule)` reports `memory_schedule_mode`.
- It reports stable and dynamic scheduler token counts.
- It sets `memory_dynamic_pressure` from dynamic scheduled lines.

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests\test_context_scheduler.py -q`

- [ ] **Step 3: Add optional scheduler metadata**

Implementation:

- Extend `plan_processor_context()` with optional `memory_schedule`.
- Keep backward compatibility when omitted.
- Pass `context.mind_packet["bionic_memory_schedule"]` from `CodexCliProcessor.generate()`.

- [ ] **Step 4: Run context tests**

Run: `python -m pytest tests\test_context_scheduler.py -q`

### Task 4: Docs, Verification, Commit

**Files:**
- Modify: `docs/ROADMAP_REGISTRY.md`
- Modify: `docs/DEEPSEEK_MODEL_BIONIC_STRESS_2026-05-12.md`
- Modify: `docs/ENGINEERING_HANDOFF_STAGE47.md`
- Modify: `HOLO_HANDOFF.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE48.md`

- [ ] **Step 1: Update docs with Stage48 contract**

Document:

- WSL remains authoritative.
- Scheduler does not write self-memory.
- Windows/Watcher remain transport only.
- Stable cortical schema is provider-prefix material.
- Working memory and hippocampal index are dynamic.
- Consolidation targets are diagnostic intents, not direct writes.

- [ ] **Step 2: Run verification**

Run:

```powershell
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_memory_fabric.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py
python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\memory_bridge.py holo_host\processors.py holo_host\context_scheduler.py
python scripts\check_public_release_hygiene.py
git diff --check
```

- [ ] **Step 3: Commit**

Run:

```powershell
git add holo_host\bionic_memory_scheduler.py holo_host\memory_bridge.py holo_host\processors.py holo_host\context_scheduler.py tests\test_bionic_memory_scheduler.py tests\test_memory_fabric.py tests\test_context_scheduler.py docs\ENGINEERING_HANDOFF_STAGE48.md docs\ROADMAP_REGISTRY.md docs\DEEPSEEK_MODEL_BIONIC_STRESS_2026-05-12.md docs\ENGINEERING_HANDOFF_STAGE47.md HOLO_HANDOFF.md docs\superpowers\plans\2026-05-12-stage48-bionic-memory-scheduler.md
git commit -m "feat: add bionic memory scheduler"
```
