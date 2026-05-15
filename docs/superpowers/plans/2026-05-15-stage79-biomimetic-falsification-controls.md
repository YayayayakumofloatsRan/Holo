# Stage79 Biomimetic Falsification Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD before touching
> production code and verification-before-completion before claiming completion.

**Goal:** Add a targeted falsification-control evaluator over Stage78 and
Stage71 evidence.

**Architecture:** Stage79 is read-only. It consumes existing JSON evidence,
separates executed controls from planned controls, writes local artifacts, and
does not call providers or mutate runtime state.

---

### Task 1: Stage79 Tests

**Files:**
- Create: `tests/test_stage79_biomimetic_falsification_controls.py`

- [x] **Step 1: Write failing tests**

Require:

- `stage=stage79-biomimetic-falsification-controls`
- one executed GNW ignition-null direct control
- three pending controls
- replay/correction intact
- bounded evidence gate
- CLI artifact writing

- [x] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\test_stage79_biomimetic_falsification_controls.py -q
```

Expected before implementation: fails because the module and CLI command do not
exist.

### Task 2: Stage79 Evaluator

**Files:**
- Create: `holo_host/biomimetic_falsification_controls.py`

- [x] **Step 1: Implement builder and artifact writer**

Implement:

- `load_biomimetic_falsification_controls_json`
- `build_biomimetic_falsification_controls`
- `write_biomimetic_falsification_controls_artifacts`
- `render_biomimetic_falsification_controls_html`

- [x] **Step 2: Keep pending controls pending**

Do not count marker-removal, neutral-salience, or gain-clamp controls as
executed until direct evidence exists.

### Task 3: CLI

**Files:**
- Modify: `holo_host/cli.py`

- [x] **Step 1: Add command**

Add:

```powershell
evaluate-biomimetic-falsification-controls --theory-json <path> --causal-json <path> --output <path>
```

- [x] **Step 2: Print compact JSON**

Return artifact paths, control counts, decision, replay/correction intact flag,
GNW control flag, and bounded evidence gates.

### Task 4: Evidence and Docs

**Files:**
- Create: `docs/STAGE79_BIOMIMETIC_FALSIFICATION_CONTROLS.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE79.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Run on Stage77/78 evidence**

Run Stage79 on Stage78 theory JSON and Stage77 Pro/Flash causal-ablation JSON.

- [x] **Step 2: Verify and commit**

Run focused tests, compile changed modules, full regression, hygiene, diff
check, update handoff/roadmap, commit, and push main.
