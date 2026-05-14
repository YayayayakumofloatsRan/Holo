# Engineering Handoff Stage71

Stage71 implements a biomimetic causal ablation lab over Stage61/69 traces.

## Scope

- New module: `holo_host/biomimetic_causal_ablation.py`.
- New CLI command: `evaluate-biomimetic-causal-ablation`.
- New regression tests: `tests/test_stage71_biomimetic_causal_ablation.py`.
- New operator docs: `docs/STAGE71_BIOMIMETIC_CAUSAL_ABLATION.md`.
- Stage71 reads Stage61/69-style lab JSON and emits HTML/JSON/PNG artifacts.

## Boundary

Stage71 is paired counterfactual analysis only:

- no self-memory writes
- no policy writes
- no transport writes
- no watcher authority
- no downstream MCP exposure
- no runtime decision authority
- no unbounded loop

The report must keep:

```text
surrogate_only = true
causal_language_bounded = true
do_not_claim_real_consciousness = true
```

## Runtime Surfaces

- `build_biomimetic_causal_ablation_lab(lab)`
  - consumes an in-memory Stage61/69 lab payload
  - computes a Stage70 baseline
  - builds paired counterfactual conditions
  - returns causal effects, publication claims, evidence gate, and boundary flags
- `write_biomimetic_causal_ablation_artifacts(report, output_path)`
  - writes HTML, JSON, and PNG
- `evaluate-biomimetic-causal-ablation`
  - loads `--lab-json` when provided
  - otherwise builds a bounded Stage61 simulation lab from the current seed-store path

## Output Contract

The report includes:

- `baseline_stage70`
- `paired_conditions.condition_index`
- `causal_effects.effect_index`
- `hypothesis_decision`
- `publication_claims`
- `run_invalidators`
- `evidence_gate.causal_language_bounded = true`
- `evidence_gate.do_not_claim_real_consciousness = true`

Core effect keys:

- `hippocampal_reactivation_delta`
- `correction_survival_proxy_delta`
- `flow_to_reply_coupling_delta`
- `prompt_cost_delta`
- `boundary_violation_delta`

## Stage69 Full-Lab Evidence

Completed on 2026-05-14:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage69\stage69_dialogue_validation_lab.json --output artifacts\stage71\stage71_biomimetic_causal_ablation.html
```

Results:

- `decision=support_surrogate`
- `hippocampal_reactivation_delta=0.125139`
- `correction_survival_proxy_delta=0.37267`
- `flow_to_reply_coupling_delta=-0.200394`
- `prompt_cost_delta=0.02371`
- `boundary_violation_delta=0.0`

Artifacts:

- `artifacts\stage71\stage71_biomimetic_causal_ablation.html`
- `artifacts\stage71\stage71_biomimetic_causal_ablation.json`
- `artifacts\stage71\stage71_biomimetic_causal_ablation_biomimetic_causality.png`

## DeepSeek Provider Replication

Completed on 2026-05-14:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --resume --runs 3 --turns 10 --max-total-tokens 180000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage71\stage71_deepseek_reactivation_trace.html
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage71\stage71_deepseek_reactivation_trace.json --output artifacts\stage71\stage71_deepseek_reactivation_causal_ablation.html
```

Provider trace result:

- `status=complete`
- `collected_turn_count=30`
- `real_provider_trace=true`
- `observed_total_tokens=132572`
- `stopped_reason=completed`
- `do_not_claim_real_manifold=true`

Stage71 provider result:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.011206`
- `correction_survival_proxy_delta=0.048457`
- `flow_to_reply_coupling_delta=-0.438947`
- `prompt_cost_delta=0.033334`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`

This is not a full H2 replication: correction survival and ignition coupling are
supported, but provider-trace hippocampal reactivation remains below threshold.

## Verification

Completed on 2026-05-14:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py
```

Result:

- Stage71 focused tests passed with `4` tests.

Required before final merge:

```powershell
python -m pytest -q tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage68_bionic_memory_robustness.py tests\test_stage61_bionic_simulation_lab.py
python -m py_compile holo_host\biomimetic_causal_ablation.py holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py
python scripts\check_public_release_hygiene.py
git diff --check
python -m pytest -q
```

## Next Gate

Run a matched real-provider DeepSeek replication through the existing Stage59/60
operator-gated trace path. The provider run should compare correction probes
with topic-shift interference and an ignition-ablation control, then re-run
Stage71 on the generated Stage61/69-compatible artifact.
