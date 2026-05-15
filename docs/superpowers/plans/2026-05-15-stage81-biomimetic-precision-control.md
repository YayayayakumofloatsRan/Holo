# Stage81 Biomimetic Precision Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use TDD before touching
> production code and verification-before-completion before claiming completion.

**Goal:** Add a direct neutral-salience precision-control evaluator over
Stage78 theory, Stage80 marker-control evidence, and Stage59/60-gated
real-provider traces.

**Architecture:** Stage81 is read-only. It consumes existing JSON evidence,
applies a matched counterfactual over delayed false-fact probes, writes local
artifacts, and does not call providers or mutate runtime state.

---

### Task 1: Stage81 Tests

**Files:**
- Create: `tests/test_stage81_biomimetic_precision_control.py`

- [x] **Step 1: Write failing tests**

Require:

- `stage=stage81-biomimetic-neutral-salience-control`
- one executed neutral-salience direct control
- one pending gain control
- Stage80 marker-control precondition supported
- replay/correction intact before precision neutralization
- prompt-cost and reactivation-phase deltas remain zero
- bounded evidence gate
- CLI artifact writing

- [x] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\test_stage81_biomimetic_precision_control.py -q
```

Expected before implementation: fails because the module and CLI command do not
exist.

### Task 2: Stage81 Evaluator

**Files:**
- Create: `holo_host/biomimetic_precision_control.py`

- [x] **Step 1: Implement builder and artifact writer**

Implement:

- `load_biomimetic_precision_control_json`
- `build_biomimetic_precision_control`
- `write_biomimetic_precision_control_artifacts`
- `render_biomimetic_precision_control_html`

- [x] **Step 2: Keep gain control pending**

Do not count gain-clamp or random-gain controls as executed until direct
evidence exists.

### Task 3: CLI

**Files:**
- Modify: `holo_host/cli.py`

- [x] **Step 1: Add command**

Add:

```powershell
evaluate-biomimetic-precision-control --theory-json <path> --marker-control-json <path> --trace-json <path> --output <path>
```

- [x] **Step 2: Print compact JSON**

Return artifact paths, control counts, decision, marker precondition flag,
neutral-salience effect flag, phase/cost deltas, and bounded evidence gates.

### Task 4: Evidence and Docs

**Files:**
- Create: `docs/STAGE81_BIOMIMETIC_PRECISION_CONTROL.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE81.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`

- [x] **Step 1: Run on Stage77/78/80 evidence**

Run Stage81 on Stage78 theory JSON, Stage80 marker JSON, and Stage77 Pro/Flash
provider-trace JSON.

- [x] **Step 2: Verify and commit**

Run focused tests, compile changed modules, full regression, hygiene, diff
check, update handoff/roadmap, commit, and push main.
