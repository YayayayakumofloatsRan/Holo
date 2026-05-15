# Stage82 Biomimetic Gain Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the final direct falsification control for neuromodulatory adaptive gain.

**Architecture:** Add a read-only Stage82 evaluator that mirrors Stage80/81 artifact patterns. It consumes Stage78, Stage81, and real-provider trace JSON files, emits paired gain-clamp evidence, and writes HTML/JSON/PNG artifacts.

**Tech Stack:** Python standard library, existing `holo_host` biomimetic observatory helpers, pytest, existing CLI parser.

---

### Task 1: Failing Tests

**Files:**
- Create: `tests/test_stage82_biomimetic_gain_control.py`

- [x] **Step 1: Write tests for Stage82 behavior**

Cover direct gain clamp, surrogate rejection, Stage81 precondition rejection,
and CLI artifact writing.

- [x] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests\test_stage82_biomimetic_gain_control.py -q
```

Expected: fail because `holo_host.biomimetic_gain_control` and
`evaluate-biomimetic-gain-control` do not exist.

### Task 2: Evaluator And CLI

**Files:**
- Create: `holo_host/biomimetic_gain_control.py`
- Modify: `holo_host/cli.py`

- [x] **Step 1: Implement the Stage82 evaluator**

Add `build_biomimetic_gain_control`, artifact writing, HTML rendering, PNG
rendering, and Stage81 precondition checks.

- [x] **Step 2: Wire the CLI**

Add `evaluate-biomimetic-gain-control` with `--theory-json`,
`--precision-control-json`, repeated `--trace-json`, and `--output`.

- [x] **Step 3: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests\test_stage82_biomimetic_gain_control.py -q
```

Expected: `4 passed`.

### Task 3: Real Evidence And Documentation

**Files:**
- Create: `docs/STAGE82_BIOMIMETIC_GAIN_CONTROL.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE82.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Generate real Stage82 artifacts**

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-gain-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --precision-control-json artifacts\stage81\stage81_biomimetic_precision_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage82\stage82_biomimetic_gain_control.html
```

Expected: `ok=true`, `pending_control_count=0`, and
`mean_gain_clamp_neuromodulator_coupling_delta=-0.321447`.

- [x] **Step 2: Document the result**

Record the exact command, decision, per-cell evidence, interpretation,
boundaries, and next Stage83 gate.

### Task 4: Verification And Release

**Files:**
- Modify: verification sections after final test run if counts change

- [x] **Step 1: Run focused biomimetic regression**

Run Stage82 plus Stage70/71/73/75/76/78/79/80/81 focused tests.

- [x] **Step 2: Compile changed modules**

Run `py_compile` over Stage82 and affected biomimetic/CLI modules.

- [x] **Step 3: Run full test suite and release hygiene**

Run full `pytest -q`, public release hygiene, and `git diff --check`.

- [ ] **Step 4: Commit and push**

Commit with `feat: add stage82 biomimetic gain control` and push `main`.
