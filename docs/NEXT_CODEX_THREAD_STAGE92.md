# Next Codex Thread Handoff Stage92

Use this file as the first compact entrypoint for the next Codex thread.

## Workspace

- Repository root: `D:\Holo\_worktrees\holo-main-biomimetic-research`
- Branch: `main`
- Stage91 mechanism commit: `e48ff61`
- Current milestone: `stage91-adaptation-ablation`

Start with:

```powershell
cd D:\Holo\_worktrees\holo-main-biomimetic-research
git status --short --branch
git log -1 --oneline
```

The expected branch state is clean and aligned with `origin/main`:

```text
## main...origin/main
```

The latest commit may be a handoff-only commit after `e48ff61`; continue from
the latest pushed state shown by `git log -1 --oneline`.

## Required Reading

Read these first, in this order:

1. `HOLO_HANDOFF.md`
2. `docs/NEXT_CODEX_THREAD_STAGE92.md`
3. `docs/STAGE91_ADAPTATION_ABLATION.md`
4. `docs/ENGINEERING_HANDOFF_STAGE91.md`
5. `docs/ROADMAP_REGISTRY.md`
6. `docs/STAGE90_POLICY_UPDATE_DELTA.md`
7. `docs/ENGINEERING_HANDOFF_STAGE90.md`
8. `docs/STAGE84_CONSCIOUSNESS_STREAM_LITERATURE_PLAN.md`
9. `docs/STAGE78_BIOMIMETIC_THEORY_CORRESPONDENCE.md`

Do not start from older Stage65/70 prompt-churn notes unless a later handoff
explicitly points back to them.

## Current Research State

The Stage87-91 interaction self-organization line is now closed at a bounded
publishable mechanism level:

- Stage87 added interaction-usefulness pressure.
- Stage88 added current-thread local adaptation.
- Stage89 added a current-thread policy vector.
- Stage90 added score-delta policy updates from recent interaction failures.
- Stage91 added a matched update-on/update-null ablation.

The strongest current result is Stage91:

```text
DeepSeek V4 Pro pair A:
update_on   overall_score=0.9525, interaction_usefulness_score=0.94, issue_count=0
update_null overall_score=0.9225, interaction_usefulness_score=0.9175, issue_count=2
token_relative_delta=0.033

DeepSeek V4 Pro pair B:
update_on   overall_score=0.957, interaction_usefulness_score=0.94, issue_count=0
update_null overall_score=0.9268, interaction_usefulness_score=0.9175, issue_count=2
```

Interpretation:

- Supported: current-thread adaptive gain improves real-provider free-dialogue
  behavior under a matched null control.
- Not supported: persistent self-learning, model-weight learning, durable
  policy sedimentation, or human consciousness.

## Next Research Gate

Prioritize Stage92 as multi-timescale biomimetic organization.

The first-principles decomposition should be:

```text
short-term adaptive gain
-> medium-term attractor stabilization
-> long-horizon subject policy sedimentation
```

Concrete Stage92 target:

- Build a direct control for medium-term attractor stabilization over
  interaction trajectories.
- Use existing Stage42/87-91 free-dialogue harnesses before broad new provider
  campaigns.
- Compare stabilized-attractor versus attractor-null conditions under matched
  scenario and prompt cost.
- Keep the biological mapping bounded to operational proxies:
  - working memory / active inference: current attention and missing input
  - predictive processing: error/headroom and salience-gated correction
  - hippocampal/CLS: bounded replay and reactivation markers
  - neuromodulatory gain: policy/update gain control
  - attractor dynamics: trajectory stability under perturbation

Acceptance for Stage92:

- A mechanism change, not only another observational repeat.
- At least one direct null control.
- Real-provider evidence if the offline path is deterministic or inconclusive.
- Stage91 update-on benefits must not regress.
- Docs, verification, commit, and push.

## Hard Architecture Boundaries

These are architecture boundaries, not paper claims:

- WSL/kernel remains the authority boundary.
- Do not add watcher/runtime decision authority.
- Do not start live WeChat transport.
- Do not add self-memory or policy writes for this research line.
- Do not add a second brain layer or unbounded loop.
- Keep provider calls inside existing Stage42/59/60-style controlled paths.

## Verification Baseline

Stage91 verification that should remain green:

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
python scripts\check_public_release_hygiene.py
git diff --check
python -m pytest -q
```

Latest Stage91 full-suite result:

```text
547 passed
```

## Suggested First Move

Do not start with broad DeepSeek repeats.

Start by locating the Stage91 control surfaces:

```powershell
rg -n "STAGE91_NAME|evaluate_stage91_adaptation_ablation|enable_policy_update|disable-policy-update" holo_host tests docs
```

Then design Stage92 around a new falsifiable mechanism:

```text
Does an explicit attractor-stabilization signal improve continuity and repair
behavior under perturbation, compared with a matched attractor-null control?
```
