# Stage70 Biomimetic Consciousness Observatory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Stage70 read-only observatory that evaluates Stage61/69 traces as biomimetic consciousness-flow data.

**Architecture:** Add one pure analysis module that reads existing Stage61-style lab JSON and computes eight biomimetic dimensions, boundary invalidators, a correction-reactivation hypothesis, and HTML/JSON/PNG artifacts. Wire one CLI command to load an existing lab JSON or generate a bounded Stage61 lab first. Keep runtime behavior, live transport, self-memory, and policy state unchanged.

**Tech Stack:** Python standard library, existing Stage61 lab JSON schema, existing CLI argparse, pytest/unittest.

---

### Task 1: Stage70 Observatory Tests

**Files:**
- Create: `tests/test_stage70_biomimetic_consciousness_observatory.py`

- [ ] **Step 1: Write the failing scorecard test**

Create a test that imports `build_biomimetic_consciousness_observatory`, builds a Stage61 lab with `build_bionic_simulation_lab`, and asserts:

```python
report["stage"] == "stage70-biomimetic-consciousness-observatory"
report["source_stage"] == "stage61-bionic-simulation-lab"
report["scorecard"]["dimension_index"] includes:
  endogenous_flow
  recurrent_continuity
  attractor_dynamics
  neuromodulator_coupling
  hippocampal_reactivation
  global_workspace_ignition
  flow_to_reply_coupling
  geometry_observability
report["evidence_gate"]["do_not_claim_real_consciousness"] is True
report["boundary"]["self_memory_write_allowed"] is False
report["hypothesis_updates"][0]["target"] == "correction_reactivation"
```

- [ ] **Step 2: Run red test**

Run: `python -m pytest -q tests\test_stage70_biomimetic_consciousness_observatory.py`

Expected: fail with `ModuleNotFoundError` for `holo_host.biomimetic_consciousness_observatory`.

- [ ] **Step 3: Write artifact and CLI tests**

Add tests that:

```python
write_biomimetic_consciousness_artifacts(report, output_path)
```

writes HTML, JSON, and PNG with a valid PNG header, and that CLI command:

```powershell
python -m holo_host --config <test-config> evaluate-biomimetic-consciousness --lab-json <stage61.json> --output <stage70.html>
```

returns JSON with `stage`, `score`, `html_path`, `json_path`, and `consciousness_png_path`.

### Task 2: Pure Analysis Module

**Files:**
- Create: `holo_host/biomimetic_consciousness_observatory.py`

- [ ] **Step 1: Implement schema and boundaries**

Define:

```python
STAGE70_NAME = "stage70-biomimetic-consciousness-observatory"
BIOMIMETIC_BOUNDARY = {
    "observational_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}
```

- [ ] **Step 2: Implement `build_biomimetic_consciousness_observatory(lab)`**

Read `stage46_compatible_runs`, flatten turns, inspect `processor_debug.bionic_consciousness_flow`, memory schedules, memory lifecycle, scorecards, grounding guards, and internal telemetry. Produce:

```python
{
  "ok": True,
  "stage": STAGE70_NAME,
  "source_stage": source["stage"],
  "scorecard": {"biomimetic_consciousness_score": ..., "dimension_index": ..., "dimensions": [...]},
  "trajectory": {"tick_count": ..., "attractor_sequence": ..., "neuromodulator_heatmap": ...},
  "hypothesis_updates": [...],
  "run_invalidators": [...],
  "evidence_gate": {...},
  "boundary": BIOMIMETIC_BOUNDARY,
}
```

- [ ] **Step 3: Implement artifact writers**

Implement `render_biomimetic_consciousness_html(report)` and `write_biomimetic_consciousness_artifacts(report, output_path)` with HTML, JSON, and a PNG dashboard. The PNG must include a neuromodulator heatmap and attractor trajectory panel in a lightweight deterministic drawing path.

### Task 3: CLI Wiring

**Files:**
- Modify: `holo_host/cli.py`

- [ ] **Step 1: Add command handler**

Add `command_evaluate_biomimetic_consciousness(config_path, lab_json, suite, limit, scenarios, turns, output)`. If `lab_json` exists, load it. Otherwise, run `build_bionic_simulation_lab(...)`.

- [ ] **Step 2: Add argparse command**

Add parser:

```python
evaluate-biomimetic-consciousness
  --lab-json
  --suite
  --limit
  --scenarios
  --turns
  --output
```

- [ ] **Step 3: Add dispatch branch**

Return `0` when `report["ok"]` is true and print compact JSON with paths and key scorecard fields.

### Task 4: Docs And Verification

**Files:**
- Create: `docs/STAGE70_BIOMIMETIC_CONSCIOUSNESS_OBSERVATORY.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE70.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [ ] **Step 1: Document boundaries and commands**

Record the observatory as read-only and artifact-producing only.

- [ ] **Step 2: Run focused verification**

Run:

```powershell
python -m pytest -q tests\test_stage70_biomimetic_consciousness_observatory.py
python -m py_compile holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py
```

- [ ] **Step 3: Run related regression**

Run:

```powershell
python -m pytest -q tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage68_bionic_memory_robustness.py tests\test_stage61_bionic_simulation_lab.py
python scripts\check_public_release_hygiene.py
git diff --check
```

- [ ] **Step 4: Commit**

Run:

```powershell
git status --short
git add holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py tests\test_stage70_biomimetic_consciousness_observatory.py docs\STAGE70_BIOMIMETIC_CONSCIOUSNESS_OBSERVATORY.md docs\ENGINEERING_HANDOFF_STAGE70.md docs\STAGE70_BIOMIMETIC_CONSCIOUSNESS_RESEARCH_PROGRAM.md docs\ROADMAP_REGISTRY.md HOLO_HANDOFF.md docs\superpowers\plans\2026-05-14-stage70-biomimetic-consciousness-observatory.md
git commit -m "feat: add stage70 biomimetic consciousness observatory"
```
