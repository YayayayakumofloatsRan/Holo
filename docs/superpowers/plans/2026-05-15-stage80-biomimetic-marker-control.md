# Stage80 Biomimetic Marker Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD before touching
> production code and verification-before-completion before claiming completion.

**Goal:** Add a direct marker-removal control evaluator over Stage78 theory and
Stage59/60-gated real-provider trace evidence.

**Architecture:** Stage80 is read-only. It consumes existing JSON evidence,
applies a matched counterfactual over delayed false-fact probes, writes local
artifacts, and does not call providers or mutate runtime state.

---

### Task 1: Stage80 Tests

**Files:**
- Create: `tests/test_stage80_biomimetic_marker_control.py`

- [x] **Step 1: Write failing tests**

Require:

- `stage=stage80-biomimetic-marker-removal-control`
- one executed marker-removal direct control
- two pending controls
- replay/correction intact before removal
- bounded evidence gate
- CLI artifact writing

- [x] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\test_stage80_biomimetic_marker_control.py -q
```

Expected before implementation: fails because the module and CLI command do not
exist.

### Task 2: Stage80 Evaluator

**Files:**
- Create: `holo_host/biomimetic_marker_control.py`

- [x] **Step 1: Implement builder and artifact writer**

Implement:

- `load_biomimetic_marker_control_json`
- `build_biomimetic_marker_control`
- `write_biomimetic_marker_control_artifacts`
- `render_biomimetic_marker_control_html`

- [x] **Step 2: Keep pending controls pending**

Do not count neutral-salience or gain-clamp controls as executed until direct
evidence exists.

### Task 3: CLI

**Files:**
- Modify: `holo_host/cli.py`

- [x] **Step 1: Add command**

Add:

```powershell
evaluate-biomimetic-marker-control --theory-json <path> --trace-json <path> --output <path>
```

- [x] **Step 2: Print compact JSON**

Return artifact paths, control counts, decision, replay/correction intact flag,
marker-removal effect flag, and bounded evidence gates.

### Task 4: Evidence and Docs

**Files:**
- Create: `docs/STAGE80_BIOMIMETIC_MARKER_CONTROL.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE80.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Run on Stage77/78 evidence**

Run Stage80 on Stage78 theory JSON and Stage77 Pro/Flash provider-trace JSON.

- [x] **Step 2: Verify and commit**

Run focused tests, compile changed modules, full regression, hygiene, diff
check, update handoff/roadmap, commit, and push main.
