# Stage29 Unified Bionic Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe Stage29 from a CLI-specific agent substrate into a unified, transport-agnostic bionic subject kernel with CLI as the first adapter.

**Architecture:** Add `BionicKernel` and `BionicTurnRequest` as the primary runtime contract in `holo_host/bionic_agent.py`. Keep `BionicAgent` as a backward-compatible wrapper so existing CLI/tests continue to work while new tests verify that CLI and synthetic WeChat inputs use the same kernel without giving transport decision authority to adapters.

**Tech Stack:** Python dataclasses, existing `QueueStore`, existing processor fabric, pytest/unittest, existing Holo CLI.

---

### Task 1: Add Kernel-First Contract Tests

**Files:**
- Modify: `tests/test_stage29_bionic_cli_agent.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `BionicKernel` and `BionicTurnRequest`, run one CLI request and one synthetic WeChat request through the same kernel, and assert:

```python
self.assertEqual(cli_capsule["kernel"], "bionic_subject_kernel")
self.assertEqual(wechat_capsule["kernel"], "bionic_subject_kernel")
self.assertEqual(cli_capsule["adapter"], "cli")
self.assertEqual(wechat_capsule["adapter"], "wechat")
self.assertFalse(wechat_capsule["interface_contract"]["transport_decision_authority"])
self.assertTrue(wechat_capsule["interface_contract"]["transport_is_interface"])
```

- [ ] **Step 2: Verify red**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`

Expected: fail because `BionicKernel` and `BionicTurnRequest` do not exist yet.

### Task 2: Implement Kernel And Request Types

**Files:**
- Modify: `holo_host/bionic_agent.py`

- [ ] **Step 1: Add the minimal public types**

Add `BionicTurnRequest` and rename the implementation class to `BionicKernel`, while keeping:

```python
class BionicAgent(BionicKernel):
    pass
```

- [ ] **Step 2: Add adapter metadata**

Capsules must include:

```python
"kernel": "bionic_subject_kernel"
"adapter": request.adapter
"interface_contract": {
    "transport_is_interface": True,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
}
```

- [ ] **Step 3: Verify green**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`

Expected: pass.

### Task 3: Persist Adapter Provenance

**Files:**
- Modify: `holo_host/store.py`
- Modify: `tests/test_stage29_bionic_cli_agent.py`

- [ ] **Step 1: Add failing store assertion**

Assert persisted bionic trace rows include `adapter = "cli"` for CLI adapter traces.

- [ ] **Step 2: Implement schema-compatible adapter column**

Add `adapter TEXT NOT NULL DEFAULT ''` to `bionic_agent_traces`, ensure the column on existing databases, and pass adapter from capsule/request.

- [ ] **Step 3: Verify green**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`

Expected: pass.

### Task 4: Update Acceptance And Docs

**Files:**
- Modify: `holo_host/cli.py`
- Modify: `.agent/PLANS.md`
- Modify: `.agent/STAGE23_27_PROGRAM.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Move: `docs/STAGE29_BIONIC_CLI_AGENT_SUBSTRATE.md` to `docs/STAGE29_BIONIC_SUBJECT_KERNEL.md`
- Modify: `docs/ENGINEERING_HANDOFF_STAGE29.md`

- [ ] **Step 1: Extend `accept-stage29` checks**

Acceptance must assert the capsule is kernel-first, adapter-visible, transport-interface-only, and synthetic WeChat does not require real WeChat.

- [ ] **Step 2: Update docs**

Replace Stage29 user-facing framing from “bionic CLI agent substrate” to “unified bionic subject kernel with CLI adapter.” Preserve current constraints: no WeChat start, no self-memory mutation, no transport decision logic.

- [ ] **Step 3: Verify acceptance**

Run: `python -m holo_host --config .holo_host.example.toml accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`

Expected: JSON `ok: true`.

### Task 5: Full Verification And Commit

**Files:**
- All modified files

- [ ] **Step 1: Run targeted tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py tests/test_stage28_multimodal_homeostatic_kernel.py`

Expected: pass.

- [ ] **Step 2: Run full suite and hygiene**

Run: `pytest -q`

Expected: pass.

Run: `python scripts/check_public_release_hygiene.py`

Expected: pass.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 3: Commit**

Run:

```powershell
git add -A
git commit -m "feat: unify stage29 bionic kernel"
```
