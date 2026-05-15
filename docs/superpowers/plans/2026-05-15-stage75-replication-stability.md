# Stage75 Replication Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether Stage74's real-provider residual headroom compression is stable across an independent longer DeepSeek provider cell, then formalize the replicated evidence.

**Architecture:** Stage75 first produces independent Stage59 provider evidence, then reuses Stage71 and Stage73. If the second cell replicates compression, add a small read-only replication-stability observatory over multiple Stage73 provider-progress reports.

**Tech Stack:** Python CLI, existing Holo Stage59/71/73 analysis modules, pytest, Markdown docs.

---

### Task 1: Independent Provider Cell

**Files:**
- Artifact output only: `artifacts/stage75/*` is ignored and not committed.

- [x] **Step 1: Confirm clean baseline**

Run: `git status --short --branch`
Expected: clean branch at Stage74.

- [x] **Step 2: Run independent DeepSeek trace**

Run:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --resume --runs 3 --turns 14 --max-total-tokens 260000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage75\stage75_deepseek_reactivation_replication_trace.html
```

Expected: `status=complete`, `collected_turn_count=42`, `real_provider_trace=true`, and `stopped_reason=completed`.

### Task 2: Stage71/73 Evaluation

**Files:**
- Artifact output only: `artifacts/stage75/*` is ignored and not committed.

- [x] **Step 1: Run Stage71 causal ablation**

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage75\stage75_deepseek_reactivation_replication_trace.json --output artifacts\stage75\stage75_deepseek_reactivation_replication_causal_ablation.html
```

Expected: `surrogate_only=false`, `causal_language_bounded=true`, and `boundary_violation_delta=0.0`.

- [x] **Step 2: Run Stage73 comparison against Stage72**

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage75\stage75_deepseek_reactivation_replication_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage75\stage75_deepseek_reactivation_replication_trace.json --output artifacts\stage75\stage75_provider_progress_vs_stage72.html
```

Expected: report shows whether residual `hippocampal_reactivation_headroom_change` and `correction_survival_headroom_change` are negative.

### Task 3: Replication-Stability Observatory

**Files:**
- Create: `tests/test_stage75_biomimetic_replication_stability.py`
- Create: `holo_host/biomimetic_replication_stability.py`
- Modify: `holo_host/cli.py`

- [x] **Step 1: Write failing tests**

Test the desired API: multiple Stage73 reports in, replication decision out. The test must fail because `holo_host.biomimetic_replication_stability` does not exist.

- [x] **Step 2: Implement minimal report builder and artifact writer**

Create a read-only module with `stage75-biomimetic-replication-stability`, `cell_results`, `replication_summary`, `hypothesis_decision`, and `evidence_gate`.

- [x] **Step 3: Add CLI**

Add `evaluate-biomimetic-replication-stability --progress-json <path>` repeated, plus `--output`.

### Task 4: Docs, Verification, Commit

**Files:**
- Create: `docs/STAGE75_REPLICATION_STABILITY.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE75.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Modify: this plan file

- [x] **Step 1: Document actual results**

Record Stage75 provider trace, Stage71, Stage73, and Stage75 replication-stability outputs with exact numbers.

- [x] **Step 2: Verify**

Run:

```powershell
python -m pytest tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_replication_stability.py holo_host\biomimetic_provider_progress.py holo_host\cli.py
python scripts\check_public_release_hygiene.py
git diff --check
```

Expected: all tests pass, compile passes, hygiene passes, no whitespace errors.

- [x] **Step 3: Commit**

Run:

```powershell
git add HOLO_HANDOFF.md docs\ROADMAP_REGISTRY.md docs\STAGE75_REPLICATION_STABILITY.md docs\ENGINEERING_HANDOFF_STAGE75.md docs\superpowers\plans\2026-05-15-stage75-replication-stability.md holo_host\biomimetic_replication_stability.py holo_host\cli.py tests\test_stage75_biomimetic_replication_stability.py
git commit -m "feat: add stage75 replication stability"
```
