# Stage77 Ignition-to-Reply Coupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit bounded global-workspace ignition-to-reply coupling mechanism to the Stage52 dynamic prompt path, then make the Stage70/71 evidence chain consume that mechanism when present.

**Architecture:** Stage77 keeps all authority boundaries intact and changes only the prompt-shaping and observational path. `bionic_consciousness_flow` will derive a structured ignition/coupling state from existing scheduler and lifecycle signals, `fuse_bionic_dynamic_prompt` will carry the coupling line into the `Bionic Dynamic Frame`, and the Stage70/71 observatories will prefer the explicit Stage77 mechanism fields when they exist while preserving legacy fallback behavior.

**Tech Stack:** Python, pytest, existing Holo Stage52/70/71 modules, Markdown docs.

---

### Task 1: Lock the Stage77 mechanism contract in tests

**Files:**
- Modify: `tests/test_bionic_consciousness_flow.py`
- Modify: `tests/test_context_scheduler.py`
- Modify: `tests/test_stage70_biomimetic_consciousness_observatory.py`

- [x] **Step 1: Write a failing flow test for explicit ignition/coupling state**

Add a correction-pressure scenario that asserts:
- `global_workspace_ignition.score` is present and greater than baseline
- `ignition_to_reply_coupling.reply_target` becomes `memory_reactivation_first`
- `phase_lines` include both `global_workspace_ignition=` and `ignition_to_reply_coupling=`

- [x] **Step 2: Run the focused flow test and confirm it fails for the expected missing fields**

Run: `python -m pytest tests\test_bionic_consciousness_flow.py -q`

- [x] **Step 3: Write a failing prompt-render test for the fused dynamic frame**

Extend the existing fused prompt test to assert the rendered prompt includes the Stage77 coupling line inside `Bionic Dynamic Frame:`.

- [x] **Step 4: Run the prompt-render test and confirm it fails before code changes**

Run: `python -m pytest tests\test_context_scheduler.py -q`

- [x] **Step 5: Write a failing Stage70 observatory test for explicit ignition preference**

Add a unit-level scenario where `processor_debug.bionic_consciousness_flow` includes explicit Stage77 ignition/coupling fields and verify the turn observation prefers those values over the older reconstructed-only ignition.

- [x] **Step 6: Run the Stage70 test and confirm it fails before implementation**

Run: `python -m pytest tests\test_stage70_biomimetic_consciousness_observatory.py -q`

### Task 2: Implement the Stage77 mechanism with minimal blast radius

**Files:**
- Modify: `holo_host/bionic_consciousness_flow.py`
- Modify: `holo_host/bionic_memory_scheduler.py`
- Modify: `holo_host/biomimetic_consciousness_observatory.py`
- Modify: `holo_host/biomimetic_causal_ablation.py`

- [x] **Step 1: Add structured ignition and reply-coupling fields to the flow builder**

Compute ignition from existing bounded inputs only:
- scheduler salience
- lifecycle consolidation priority
- correction marker pressure
- selected action
- uncertainty

Expose both structured dictionaries and compact `phase_lines`.

- [x] **Step 2: Carry the Stage77 coupling line through Stage52 fusion**

Update fusion supplement rendering so the provider-facing `Bionic Dynamic Frame` includes the Stage77 coupling line without creating a new prompt section.

- [x] **Step 3: Make Stage70 prefer explicit Stage77 ignition/coupling values when present**

Keep fallback behavior for pre-Stage77 traces unchanged.

- [x] **Step 4: Let Stage71 flow-coupling proxy consume explicit coupling strength when available**

Keep the existing correlation-based proxy as fallback so old artifacts and tests remain valid.

### Task 3: Verify, document, and checkpoint

**Files:**
- Modify: `docs/superpowers/specs/2026-05-15-stage77-ignition-reply-coupling-design.md`
- Modify: `docs/superpowers/plans/2026-05-15-stage77-ignition-reply-coupling.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Create: `docs/STAGE77_IGNITION_REPLY_COUPLING.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE77.md`

- [x] **Step 1: Run focused regression**

Run:

```powershell
python -m pytest tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage71_biomimetic_causal_ablation.py -q
```

- [x] **Step 2: Run compile and broader verification**

Run:

```powershell
python -m py_compile holo_host\bionic_consciousness_flow.py holo_host\bionic_memory_scheduler.py holo_host\biomimetic_consciousness_observatory.py holo_host\biomimetic_causal_ablation.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

- [ ] **Step 3: Update Stage77 docs with actual implementation and verification evidence**

Record exact tests run, exact commit target, and the publication-bounded interpretation: Stage77 adds mechanism structure, but real-provider flow stabilization still requires the next evidence pass.

- [ ] **Step 4: Commit the Stage77 checkpoint**

Commit with:

```powershell
git commit -m "feat: add stage77 ignition reply coupling"
```
