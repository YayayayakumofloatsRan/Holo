# Stage76 Model-Family Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether Stage74/75 replay-correction residual headroom compression survives DeepSeek model-family variation, and determine whether flow-coupling instability is model-specific or mechanism-level.

**Architecture:** Stage76 uses Stage60 only for real provider collection, with isolated shadow runtime cells for `deepseek-v4-pro` and `deepseek-v4-flash`. It then reuses Stage71 causal ablation, Stage73 provider-progress comparison against Stage72, and Stage75-style repeated-cell stability. If Stage75's aggregate report cannot express model-family interpretation clearly, add a read-only Stage76 model-family observatory over Stage73 progress reports.

**Tech Stack:** Python CLI, existing Holo Stage60/71/73/75 analysis modules, pytest, Markdown docs.

---

### Task 1: Cross-Model Provider Campaign

**Files:**
- Artifact output only: `artifacts/stage76/*` is ignored and not committed.

- [x] **Step 1: Confirm clean baseline**

Run: `git status --short --branch`
Expected: clean branch at Stage75.

- [x] **Step 2: Run repeated DeepSeek model-family campaign**

Run:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage76_model_family_20260515 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 3 --turns 14 --max-total-tokens-per-cell 260000 --provider-hint deepseek --lane auto --max-output-tokens 180 --output-root artifacts\stage76\stage76_model_family_20260515
```

Expected: `status=complete`, `real_provider_cell_count=2`, `collected_turn_count=84`, no provider fallback, and `do_not_claim_major_breakthrough=true`.

### Task 2: Per-Model Stage71/73 Evaluation

**Files:**
- Artifact output only: `artifacts/stage76/*` is ignored and not committed.

- [x] **Step 1: Locate per-cell provider traces**

Inspect `artifacts\stage76\stage76_model_family_20260515\campaign_manifest.json` and the `cells` directory to map model names to trace JSON paths.

- [x] **Step 2: Run Stage71 causal ablation for Pro and Flash**

Run one `evaluate-biomimetic-causal-ablation` command per cell.

Expected per model: `surrogate_only=false`, `causal_language_bounded=true`, `boundary_violation_delta=0.0`.

- [x] **Step 3: Run Stage73 comparison against Stage72 for Pro and Flash**

Run one `evaluate-biomimetic-provider-progress` command per cell using Stage72 as the before report/trace.

Expected per model: report distinguishes absolute baseline improvement from residual replay/correction headroom and flow-coupling loss reduction.

### Task 3: Model-Family Interpretation

**Files if a new observatory is needed:**
- Create: `tests/test_stage76_biomimetic_model_family_stability.py`
- Create: `holo_host/biomimetic_model_family_stability.py`
- Modify: `holo_host/cli.py`

- [x] **Step 1: Evaluate Stage75-style stability with Stage74/75/76 cells**

Run `evaluate-biomimetic-replication-stability` over Stage74, Stage75, and both Stage76 model progress JSONs.

Expected: replay/correction compression survives only if every real-provider cell has negative hippocampal and correction residual headroom changes.

- [x] **Step 2: Add Stage76 model-family observatory if Stage75 report is not expressive enough**

If needed, write failing tests first. The Stage76 observatory should consume model-labeled Stage73 reports, report per-model compression flags, and classify flow instability as `model_family_stable`, `model_specific`, or `mechanism_level_unstable`.

- [x] **Step 3: Run the model-family observatory**

Expected: a report that explicitly states whether replay/correction compression survives Pro/Flash variation and whether flow instability is model-specific or mechanism-level.

### Task 4: Docs, Verification, Commit

**Files:**
- Create: `docs/STAGE76_MODEL_FAMILY_STABILITY.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE76.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Modify: this plan file
- Include Stage76 code/test files only if Task 3 adds an observatory.

- [x] **Step 1: Document actual results**

Record campaign, Stage71, Stage73, Stage75-style, and Stage76 model-family outputs with exact numbers.

- [x] **Step 2: Verify**

Run the focused Stage76/75/73/71/70 tests, compile any changed modules, full pytest when practical, public release hygiene, and `git diff --check`.

- [x] **Step 3: Commit**

Commit promptly with either:

```powershell
git commit -m "feat: add stage76 model family stability"
```

or, if no code was required:

```powershell
git commit -m "docs: record stage76 model family stability"
```
