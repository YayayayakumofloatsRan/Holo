# Stage78 Biomimetic Theory Correspondence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a falsifiable neuroscience theory-correspondence evaluator over Stage77 evidence.

**Architecture:** Stage78 is a read-only observatory. It consumes Stage77's model-family stability report, maps evidence to four theory families, emits bounded publication claims and falsification controls, and writes HTML/JSON/PNG artifacts through the existing CLI pattern.

**Tech Stack:** Python, argparse CLI in `holo_host/cli.py`, pytest, Markdown docs.

---

### Task 1: Stage78 Tests

**Files:**
- Create: `tests/test_stage78_biomimetic_theory_correspondence.py`

- [x] **Step 1: Write failing tests**

Add tests that require:

- `stage=stage78-biomimetic-theory-correspondence`
- four falsifiable theory rows
- supported hippocampal/CLS and predictive-processing rows
- partial GNW row
- neuromodulatory gain row marked as needing targeted control
- bounded evidence gate
- CLI artifact writing

- [x] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\test_stage78_biomimetic_theory_correspondence.py -q
```

Expected before implementation: fails because the module and CLI command do not
exist.

### Task 2: Stage78 Evaluator

**Files:**
- Create: `holo_host/biomimetic_theory_correspondence.py`

- [x] **Step 1: Implement builder and artifact writer**

Implement:

- `load_biomimetic_theory_correspondence_json`
- `build_biomimetic_theory_correspondence`
- `write_biomimetic_theory_correspondence_artifacts`
- `render_biomimetic_theory_correspondence_html`

- [x] **Step 2: Keep authority boundaries hard**

The module must not call providers, write memory, mutate policy, or add runtime
authority. It consumes JSON and writes local artifacts only.

### Task 3: CLI

**Files:**
- Modify: `holo_host/cli.py`

- [x] **Step 1: Add command**

Add:

```powershell
evaluate-biomimetic-theory-correspondence --model-family-json <path> --output <path>
```

- [x] **Step 2: Print compact JSON**

Return `ok`, artifact paths, theory counts, publication readiness, and bounded
evidence flags.

### Task 4: Evidence and Docs

**Files:**
- Create: `docs/STAGE78_BIOMIMETIC_THEORY_CORRESPONDENCE.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE78.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Run on Stage77 evidence**

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-theory-correspondence --model-family-json artifacts\stage77\stage77_ignition_reply_20260515\stage77_model_family_stability.json --output artifacts\stage78\stage78_theory_correspondence.html
```

Expected: `publication_readiness=bounded_preprint_candidate`.

- [x] **Step 2: Verify and commit**

Run focused tests, compile changed modules, run relevant regression tests, update
handoff/roadmap, then commit.
