# Stage30 Unified Subject Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, bounded, inspectable subject-loop contract to the bionic kernel so Holo exposes perception, attention, inhibition, action selection, generation, outcome appraisal, and state-update discipline as one coherent loop.

**Architecture:** Keep Stage29 capsule phases unchanged for compatibility, and add a new `subject_loop` payload assembled by `holo_host/subject_loop/`. The loop is observational and contract-enforcing: it records invariants and allowed writes, but it does not start WeChat, mutate self-memory, add a second brain, or introduce an always-on loop.

**Tech Stack:** Python dataclasses, existing Stage29 bionic pipeline, existing CLI argparse, pytest.

---

### Task 1: Subject-Loop Contract Tests

**Files:**
- Create: `tests/test_stage30_subject_loop.py`
- Modify: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing tests**

Add tests that run `BionicKernel` and assert:
- `capsule["subject_loop"]["stage"] == "stage30-unified-subject-loop"`
- `phase_order` is `perception -> working_field -> attention -> inhibition -> action_market -> generation -> outcome_appraisal -> state_update`
- all hard invariants are true
- `state_update` forbids self-memory, policy, and Mind Graph writes
- `accept-stage30` is available from CLI

- [x] **Step 2: Verify red**

Run: `pytest -q tests/test_stage30_subject_loop.py`

Expected: fail because `subject_loop` and `accept-stage30` do not exist yet.

### Task 2: Subject Loop Modules

**Files:**
- Create: `holo_host/subject_loop/__init__.py`
- Create: `holo_host/subject_loop/contracts.py`
- Create: `holo_host/subject_loop/assembly.py`
- Modify: `holo_host/bionic_kernel_parts/contracts.py`
- Modify: `holo_host/bionic_kernel_parts/pipeline.py`

- [x] **Step 1: Implement loop contract**

Add constants and a trace dataclass for the Stage30 loop. The contract must expose loop name, phase order, invariants, outcome appraisal, and state update.

- [x] **Step 2: Assemble loop from existing bionic pipeline**

Build `subject_loop` after generation and before capsule serialization. Use existing bionic data only; do not add new model calls or state writes.

### Task 3: Acceptance And Docs

**Files:**
- Modify: `holo_host/cli.py`
- Add: `docs/STAGE30_UNIFIED_SUBJECT_LOOP.md`
- Add: `docs/ENGINEERING_HANDOFF_STAGE30.md`
- Modify: `.agent/PLANS.md`
- Modify: `.agent/STAGE23_27_PROGRAM.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Add `accept-stage30`**

Acceptance calls the Stage29 gate, then asserts the subject-loop payload exists, invariants pass, phase order is complete, synthetic WeChat remains adapter-only, and no self-memory or policy write is authorized.

- [x] **Step 2: Document Stage30**

Document the loop as an explicit subject-kernel contract, not a new autonomy path.

### Task 4: Verification And Commit

**Files:**
- All modified Stage30 files

- [x] **Step 1: Run targeted verification**

Run: `pytest -q tests/test_stage30_subject_loop.py tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py`

- [x] **Step 2: Run acceptance**

Run: `python -m holo_host --config .holo_host.example.toml accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`

- [x] **Step 3: Run full verification**

Run: `pytest -q`, `python scripts/check_public_release_hygiene.py`, and `git diff --check`.

- [x] **Step 4: Commit**

Commit message: `feat: add stage30 unified subject loop`
