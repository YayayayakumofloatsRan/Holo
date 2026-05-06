# Stage28 Multimodal Homeostatic Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Stage28 vertical slice for bounded multimodal situational grounding, visual-state fusion, and non-template inquiry shaping.

**Architecture:** Stage28 is a derived kernel layer over existing Mind Graph and MemoryBridge surfaces. It adds no new loop family and no second store; it exposes `situational_field`, `visual_field`, and inspectable action-market deltas through existing sidecar, prompt, service, CLI, docs, and acceptance paths.

**Tech Stack:** Python, SQLite-backed Mind Graph, `MemoryBridge`, `HoloReplyService`, CLI/HTTP route helpers, pytest/unittest.

---

### Task 1: Lock Stage28 Behavior With Tests

**Files:**
- Create: `tests/test_stage28_multimodal_homeostatic_kernel.py`

- [x] Add tests for situational-field fusion, prompt ordering, visual extended metadata, action-market annotation, and explicit recall preservation.
- [x] Run `pytest -q tests/test_stage28_multimodal_homeostatic_kernel.py` and confirm the tests fail because Stage28 surfaces do not exist yet.

### Task 2: Add Derived Situational And Visual Fields

**Files:**
- Modify: `holo_host/memory_bridge.py`

- [x] Extend `visual_memory_state()` payloads with metadata-backed spatial refs, uncertainty markers, revisit state, and density.
- [x] Add deterministic helpers to derive `visual_field`, `situational_field`, and `stage28`.
- [x] Add `stage28`, `situational_field`, and `visual_field` to every finalized mind packet.
- [x] Keep active-thread fast path bounded and history-light.

### Task 3: Add Action-Market Stage28 Overlay

**Files:**
- Modify: `holo_host/policy_runtime/action_market.py`
- Modify: `holo_host/memory_bridge.py`

- [x] Add `apply_situational_field_overlay(...)`.
- [x] Annotate candidates with `stage28_delta`, `stage28_rationale`, and `stage28_grounding_order`.
- [x] Keep delta capped and bypassed under explicit memory/factual/search/visual hard gates.

### Task 4: Clean Prompt Expression Surface

**Files:**
- Modify: `holo_host/processors.py`

- [x] Add `Situational Field` prompt lines before the recent thread window.
- [x] Replace touched mojibake prompt strings with UTF-8 Chinese.
- [x] Add an explicit anti-template instruction for grounded inquiry.

### Task 5: Diagnostics And Acceptance

**Files:**
- Modify: `holo_host/reply_api.py`
- Modify: `holo_host/reply_service_parts/acceptance.py`
- Modify: `holo_host/reply_service_parts/endpoints.py`
- Modify: `holo_host/cli.py`

- [x] Add service methods and HTTP/CLI mirrors for `show-situational-field`, `trace-visual-field`, and `trace-inquiry-shaping`.
- [x] Add `accept_stage28()` and CLI `accept-stage28`.
- [x] Ensure diagnostics can run local-process fallback while Holo remains stopped.

### Task 6: Docs, Verification, Review, Commit

**Files:**
- Create: `docs/STAGE28_MULTIMODAL_HOMEOSTATIC_KERNEL.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE28.md`
- Modify: `.agent/PLANS.md`
- Modify: `.agent/STAGE23_27_PROGRAM.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Modify: `AGENTS.md`

- [x] Document Stage28 as implemented and Stage29+ as not yet planned.
- [x] Run targeted tests, full `pytest -q`, `accept-stage27`, and `accept-stage28`.
- [x] Review `git diff` for runtime safety, no watcher startup, no hot-edit loop, and no direct provider calls.
- [ ] Commit all changes with a focused Stage28 message.
