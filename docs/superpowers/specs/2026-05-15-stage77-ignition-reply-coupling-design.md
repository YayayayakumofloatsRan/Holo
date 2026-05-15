# Stage77 Ignition-to-Reply Coupling Design

## Goal
Stage77 turns `global_workspace_ignition` from a read-only observational score into a bounded prompt-level mechanism that explicitly biases how Holo expresses a reply. The target is not a new planner, not a new authority layer, and not a watcher-side control path. The target is a theory-bounded intervention inside the existing WSL subject runtime that can later be tested through the Stage71, Stage73, Stage75, and Stage76 evidence chain.

## Non-Negotiable Boundaries
- WSL remains the only brain and only decision authority.
- Windows remains transport and tooling only.
- No watcher/runtime decision authority.
- No WeChat transport changes.
- No self-memory writes.
- No policy writes.
- No new unbounded loop.
- No direct provider call path outside the existing processor fabric and Stage59/60 operator-gated routes.

## Theory Correspondence

### Global Neuronal Workspace
The missing Stage76 mechanism is not replay/correction. It is expression coupling. Holo already measures an ignition proxy, but that proxy does not explicitly reach the reply surface. Stage77 therefore adds a bounded `ignition_to_reply_coupling` representation whose only job is to broadcast the dominant currently selected content into reply expression.

Expected functional mapping:
- ignition score: how strongly current state should become globally available
- reply target: which content wins the broadcast race into expression
- coupling strength: how strongly the selected content should bias the reply

### Hippocampal Indexing and Complementary Learning Systems
Stage72 through Stage76 already established replay/correction pressure through `correction_reactivation_marker`. Stage77 must preserve that chain. When correction pressure is active, ignition-to-reply coupling should preferentially route expression through memory reactivation instead of letting reply generation drift toward a generic low-pressure answer.

### Predictive Processing
Correction pressure is treated as bounded prediction error plus precision weighting. Stage77 therefore lets correction pressure increase ignition and reply coupling, but it does not allow that pressure to bypass uncertainty reporting or authority guards.

## Implementation Design

### 1. Add explicit ignition and reply-coupling state to `bionic_consciousness_flow`
`holo_host/bionic_consciousness_flow.py` should compute:
- `global_workspace_ignition.score`
- `global_workspace_ignition.sources`
- `ignition_to_reply_coupling.coupling_strength`
- `ignition_to_reply_coupling.reply_target`
- `ignition_to_reply_coupling.correction_priority`
- `ignition_to_reply_coupling.selected_action`

Inputs should come from existing bounded surfaces only:
- scheduler salience gate
- lifecycle consolidation priority
- correction-reactivation marker presence
- selected action
- uncertainty level

### 2. Carry the mechanism into the existing scheduler-owned prompt surface
The intervention should not create a new prompt block. It should travel through the existing Stage52 path:
- build the coupling state in `bionic_consciousness_flow`
- render compact coupling lines into `phase_lines`
- expose those lines through `fuse_bionic_dynamic_prompt`
- keep the final provider-facing surface as `Bionic Dynamic Frame`

This keeps the mechanism inside the same bounded prompt budget and preserves authority boundaries.

### 3. Let Stage70/71 consume explicit mechanism fields when present
`holo_host/biomimetic_consciousness_observatory.py` and `holo_host/biomimetic_causal_ablation.py` should remain backward-compatible, but when Stage77 fields exist they should prefer them over purely reconstructed proxy values. This is necessary for publication-bounded interpretation: the measured ignition signal should reflect the actual mechanism now injected into reply shaping.

## Falsifiable Predictions
- If the mechanism is real, fused prompt surfaces should include explicit ignition and reply-coupling lines under correction pressure.
- If the mechanism is real, Stage70/71 observatory code should read explicit Stage77 ignition/coupling values when present.
- If the mechanism matters in provider traces, later Stage73 and Stage75-style evaluations should preserve replay/correction compression while improving or stabilizing flow-loss reduction.
- If those later flow metrics do not improve after the mechanism change, the current GNW correspondence is still too weak and the theory claim should be reduced.

## Acceptance
- New tests fail before implementation and pass after implementation.
- Prompt surfaces show explicit ignition-to-reply coupling without adding any new authority path.
- Stage70/71 remain backward-compatible for pre-Stage77 artifacts.
- Docs, handoff, and roadmap are updated so the next thread can continue without hidden context.
