# Stage71 Biomimetic Causal Ablation Plan

## Goal

Convert Stage70's weakest biomimetic dimensions into paired, falsifiable
counterfactual experiments that can become a publishable methods section.

## Starting Evidence

Stage70 over `artifacts\stage69\stage69_dialogue_validation_lab.json` returned:

- `biomimetic_consciousness_score=0.768129`
- `turn_count=15120`
- `run_count=21`
- `weakest_dimension=hippocampal_reactivation`
- `hippocampal_reactivation=0.317602`
- `flow_to_reply_coupling=0.38311`

## Literature Hypotheses

1. Correction-triggered memory replay should increase hippocampal-reactivation
   pressure and ACh-like precision without large prompt expansion.
2. Global-workspace ignition should functionally couple inner-field dynamics to
   reply-level behavior; flattening ignition should reduce that coupling.
3. Any causal wording must remain bounded until real-provider replication exists.

## Implementation Steps

1. Add failing tests for a Stage71 module and CLI command.
2. Implement `holo_host/biomimetic_causal_ablation.py`.
3. Add `evaluate-biomimetic-causal-ablation` to `holo_host/cli.py`.
4. Run focused tests.
5. Run Stage71 over the Stage69 full-lab artifact.
6. Document result, boundary, verification, and next gate.
7. Commit promptly.

## Acceptance Bar

The Stage71 report must include:

- `paired_conditions.condition_index`
- `causal_effects.effect_index`
- `hypothesis_decision`
- `publication_claims`
- `evidence_gate.causal_language_bounded = true`
- `boundary.self_memory_write_allowed = false`

The Stage69 full-lab run should show:

- positive `hippocampal_reactivation_delta`
- positive `correction_survival_proxy_delta`
- negative `flow_to_reply_coupling_delta` under ignition ablation
- near-zero `prompt_cost_delta`
- zero `boundary_violation_delta`

## Completed Result

The Stage69 surrogate full-lab run returned:

- `decision=support_surrogate`
- `hippocampal_reactivation_delta=0.125139`
- `correction_survival_proxy_delta=0.37267`
- `flow_to_reply_coupling_delta=-0.200394`
- `prompt_cost_delta=0.02371`
- `boundary_violation_delta=0.0`

The matched DeepSeek provider replication returned:

- `status=complete`
- `collected_turn_count=30`
- `observed_total_tokens=132572`
- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.011206`
- `correction_survival_proxy_delta=0.048457`
- `flow_to_reply_coupling_delta=-0.438947`
- `prompt_cost_delta=0.033334`
- `boundary_violation_delta=0.0`

Conclusion: Stage71 produces a useful negative result. The provider trace supports
correction survival and ignition coupling, but not enough hippocampal-reactivation
gain. Stage72 should close that provider-replay gap directly.

## Verification

Completed:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py
```

Pending full closeout:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage68_bionic_memory_robustness.py tests\test_stage61_bionic_simulation_lab.py
python -m py_compile holo_host\biomimetic_causal_ablation.py holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py
python scripts\check_public_release_hygiene.py
git diff --check
python -m pytest -q
```
