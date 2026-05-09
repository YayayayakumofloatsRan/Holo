# Stage29 Bionic Kernel Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Stage29 bionic subject kernel into focused pipeline modules while preserving the existing public API and acceptance behavior.

**Architecture:** Keep `holo_host.bionic_agent` as the public facade exposing `BionicKernel`, `BionicAgent`, and `BionicTurnRequest`. Move bounded payload handling, contracts, generation, metrics, normalization, and pipeline orchestration into `holo_host/bionic_kernel_parts/` so the kernel can evolve without turning the facade into a second monolith.

**Tech Stack:** Python stdlib dataclasses, existing `HostConfig`, existing processor fabric, existing `QueueStore`, pytest.

---

### Task 1: Architecture Boundary Test

**Files:**
- Modify: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing architecture test**

Add a test that imports `BionicPipeline` from `holo_host.bionic_kernel_parts.pipeline`, asserts `BionicKernel` owns a `_pipeline`, and verifies the public facade still exports `BionicTurnRequest`.

- [x] **Step 2: Run focused test**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`

Expected before implementation: fail because `holo_host.bionic_kernel_parts` does not exist.

### Task 2: Create Focused Pipeline Modules

**Files:**
- Create: `holo_host/bionic_kernel_parts/__init__.py`
- Create: `holo_host/bionic_kernel_parts/contracts.py`
- Create: `holo_host/bionic_kernel_parts/bounded_payload.py`
- Create: `holo_host/bionic_kernel_parts/normalization.py`
- Create: `holo_host/bionic_kernel_parts/generation.py`
- Create: `holo_host/bionic_kernel_parts/metrics.py`
- Create: `holo_host/bionic_kernel_parts/pipeline.py`
- Modify: `holo_host/bionic_agent.py`

- [x] **Step 1: Move contracts and helpers**

Move `BionicTurnRequest`, `BionicPhase`, `BionicCapsule`, bounded payload helpers, canonical thread normalization, generation, and metrics into focused modules.

- [x] **Step 2: Keep facade compatible**

`holo_host.bionic_agent` must still export `BionicKernel`, `BionicAgent`, `BionicTurnRequest`, `KERNEL_NAME`, and `STAGE29_NAME`.

### Task 3: Verification

**Files:**
- All modified Stage29 files

- [x] **Step 1: Run targeted tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py tests/test_stage28_multimodal_homeostatic_kernel.py`

Expected: pass.

- [x] **Step 2: Run acceptance**

Run: `python -m holo_host --config .holo_host.example.toml accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`

Expected: `ok: true`.

- [x] **Step 3: Run full verification**

Run: `pytest -q`, `python scripts/check_public_release_hygiene.py`, and `git diff --check`.

Expected: tests and hygiene pass; `git diff --check` has no whitespace errors.
