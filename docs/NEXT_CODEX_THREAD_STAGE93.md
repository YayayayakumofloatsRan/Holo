# Next Codex Thread Handoff Stage93

Use this file as the first compact entrypoint for the next Codex thread.

## Workspace

- Repository root: `D:\Holo\_worktrees\holo-main-biomimetic-research`
- Branch: `main`
- Stage92 mechanism: medium-term attractor stabilization over Stage42
  free-dialogue trajectories
- Current milestone: `stage92-attractor-stabilization`

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

## Required Reading

Read these first, in this order:

1. `HOLO_HANDOFF.md`
2. `docs/NEXT_CODEX_THREAD_STAGE93.md`
3. `docs/STAGE92_MULTI_TIMESCALE_ATTRACTOR_STABILIZATION.md`
4. `docs/ENGINEERING_HANDOFF_STAGE92.md`
5. `docs/STAGE91_ADAPTATION_ABLATION.md`
6. `docs/ENGINEERING_HANDOFF_STAGE91.md`
7. `docs/ROADMAP_REGISTRY.md`
8. `docs/STAGE90_POLICY_UPDATE_DELTA.md`
9. `docs/STAGE84_CONSCIOUSNESS_STREAM_LITERATURE_PLAN.md`
10. `docs/STAGE78_BIOMIMETIC_THEORY_CORRESPONDENCE.md`

## Current Research State

Stage87-92 now covers two timescales:

```text
short-term adaptive gain -> medium-term attractor stabilization
```

Stage91 supported short-term adaptive gain under update-on/update-null provider
controls. Stage92 added a direct attractor-on/attractor-null mechanism over the
same free-dialogue harness.

Strongest Stage92 evidence:

```text
Provider pair B:
attractor_on   overall_score=0.9567, continuity_score=0.8667, issue_count=0
attractor_null overall_score=0.9121, continuity_score=0.5333, issue_count=1

Provider pair C:
attractor_on   overall_score=0.9576, continuity_score=0.8667, issue_count=0
attractor_null overall_score=0.9121, continuity_score=0.5333, issue_count=1
```

Both supported pairs used structural prompt-cost matching because usage metadata
was incomplete. Do not overstate measured token-cost equality.

## Next Research Gate

Prioritize Stage93 as long-horizon subject policy sedimentation.

First-principles decomposition:

```text
short-term adaptive gain
-> medium-term attractor stabilization
-> long-horizon subject policy sedimentation
```

Concrete Stage93 target:

- Build a direct control for long-horizon policy sedimentation over current
  Stage42/87-92 interaction trajectories.
- Keep it shadow-only unless a later gate proves any durable surface is
  bounded, reversible, observable, and separated from self-memory.
- Compare sedimented-policy versus sedimentation-null under matched scenario,
  prompt structure, and provider budget.
- Preserve Stage91 update-on and Stage92 attractor-on benefits.

Acceptance for Stage93:

- A mechanism change, not only another observational repeat.
- At least one direct null control.
- Offline path may establish deterministic wiring only; provider evidence is
  required if offline is inconclusive.
- No self-memory writes, durable unreviewed policy writes, watcher authority,
  runtime decision authority, live WeChat transport, second brain, or unbounded
  loop.
- Docs, verification, commit, and push.

## Suggested First Move

Do not start with broad provider repeats.

Locate Stage92 surfaces first:

```powershell
rg -n "STAGE92_NAME|evaluate_stage92_attractor_ablation|enable_attractor_stabilization|disable-attractor-stabilization|attractor_stabilization" holo_host tests docs
```

Then design Stage93 around a falsifiable mechanism:

```text
Does a bounded shadow policy-sedimentation signal improve later trajectory
repair without writing self-memory or mutating live policy authority?
```
