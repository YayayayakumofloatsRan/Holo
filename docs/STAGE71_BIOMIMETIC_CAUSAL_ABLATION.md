# Stage71 Biomimetic Causal Ablation Lab

## What Stage71 Adds

Stage71 turns Stage70's weakest biomimetic evidence into paired, falsifiable
counterfactual experiments.

The new CLI command is:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage69\stage69_dialogue_validation_lab.json --output artifacts\stage71\stage71_biomimetic_causal_ablation.html
```

The command reads Stage61/69-style lab JSON, builds the Stage70 baseline, then
compares three matched conditions:

| condition | meaning |
| --- | --- |
| `baseline_observed` | unchanged Stage61/69 trace |
| `correction_reactivation_boost` | false-fact and memory-pressure turns raise memory-reactivation phase, recall budget, consolidation priority, and ACh-like precision |
| `global_workspace_ignition_ablation` | global-workspace ignition is flattened before reply-coupling estimation |

This is a counterfactual estimator over trace telemetry. It is not a live runtime
change and not proof of biological consciousness.

## Literature Link

Stage71 operationalizes three literature claims:

- The AI-consciousness indicator-property program recommends assessing AI systems
  against computational properties derived from recurrent processing, global
  workspace, higher-order, predictive-processing, and attention-schema theories:
  <https://arxiv.org/abs/2308.08708>.
- The GNW review defines conscious access around nonlinear ignition, recurrent
  processing, amplification, sustained availability, and broadcast to local
  processors: <https://www.unicog.org/publications/1-s2.0-S0896627320300520-main>.
- Human and animal memory literature treats hippocampal replay/reactivation as a
  functional mechanism for consolidation and delayed memory availability; TMR is
  the experimental analogue: <https://pmc.ncbi.nlm.nih.gov/articles/PMC10754334/>.
- Precision/uncertainty models link cholinergic neuromodulation to perceptual
  inference and learning under uncertainty: <https://pmc.ncbi.nlm.nih.gov/articles/PMC4235126/>.

Holo translation:

- `hippocampal_reactivation_delta` tests whether correction-triggered replay
  raises Stage70's weakest dimension.
- `correction_survival_proxy_delta` tests whether a delayed false-fact correction
  remains available after interference.
- `flow_to_reply_coupling_delta` tests whether flattening global-workspace
  ignition removes reply-level coupling.
- `prompt_cost_delta` prevents the mechanism from cheating by simply expanding
  prompt budget.
- `boundary_violation_delta` keeps the result invalid if it introduces self-memory,
  policy, transport, or runtime authority changes.

## Output Contract

`evaluate-biomimetic-causal-ablation` writes:

- HTML report
- JSON report
- PNG dashboard

The report includes:

- `baseline_stage70`
- `paired_conditions.condition_index`
- `causal_effects.effect_index`
- `hypothesis_decision`
- `publication_claims`
- `evidence_gate.causal_language_bounded = true`
- `evidence_gate.do_not_claim_real_consciousness = true`
- `boundary.self_memory_write_allowed = false`
- `boundary.runtime_decision_authority = false`

## Stage69 Full-Lab Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage69\stage69_dialogue_validation_lab.json --output artifacts\stage71\stage71_biomimetic_causal_ablation.html
```

Result:

- `decision=support_surrogate`
- `hippocampal_reactivation_delta=0.125139`
- `correction_survival_proxy_delta=0.37267`
- `flow_to_reply_coupling_delta=-0.200394`
- `prompt_cost_delta=0.02371`
- `boundary_violation_delta=0.0`
- `surrogate_only=true`
- `causal_language_bounded=true`
- `do_not_claim_real_consciousness=true`

Interpretation:

The surrogate evidence supports the correction-reactivation hypothesis and the
global-workspace functional-coupling hypothesis. It does not yet authorize a real
biological or consciousness claim. The next publishable step is a matched
DeepSeek Stage59/60 provider replication with correction probes, topic-shift
interference, and ignition-ablation controls.

## Boundary

Stage71 is observational/counterfactual only:

- no provider call unless a future Stage59/60 replication is explicitly executed
- no runtime decision authority
- no transport decision authority
- no WeChat transport use
- no self-memory write
- no policy mutation
- no unbounded loop

## Verification

Focused verification:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py
python -m py_compile holo_host\biomimetic_causal_ablation.py holo_host\cli.py
```

Related regression should include:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage68_bionic_memory_robustness.py tests\test_stage61_bionic_simulation_lab.py
python scripts\check_public_release_hygiene.py
git diff --check
```
