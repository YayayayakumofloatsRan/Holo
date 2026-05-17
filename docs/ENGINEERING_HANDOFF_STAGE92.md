# Engineering Handoff Stage92

Stage92 adds medium-term attractor stabilization over the existing Stage42
free-dialogue harness, with a matched `attractor_null` control.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `STAGE92_NAME` and `STAGE92_CONTROL_NAME`.
  - Adds `enable_attractor_stabilization` to `_IsolatedNoviceMemory` and
    `BionicUserSimulationHarness.run()`.
  - Emits `stage92` trajectory packets with target attractors, perturbation
    labels, stabilization signals, input vectors, and stabilized vectors.
  - Applies Stage92 only when Stage90 policy update is enabled, preserving the
    Stage91 update-null control.
  - Adds `attractor_stabilization_score`.
  - Adds `evaluate_stage92_attractor_ablation()`.
- `holo_host/bionic_kernel_parts/pipeline.py`
  - Exposes Stage92 as `capsule.working_field.attractor_stabilization`.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds the provider prompt line `Stage92 medium-term attractor stabilization`.
  - Adds a no-grounding visual phrase guard for summary turns that say
    `visible to me` or `attached image`.
- `holo_host/cli.py`
  - Adds `run-bionic-user-sim --disable-attractor-stabilization`.
- `holo_host/cli_parts/user_sim.py`
  - Passes the Stage92 control flag into the harness.
- `holo_host/reply_api.py`
  - Allows API callers to pass `disable_attractor_stabilization`.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage92 red/green tests for attractor-on packets, attractor-null
    packets, harness metadata, provider prompt injection, evaluator behavior,
    structural prompt-cost matching, and the visual summary guard.
- `docs/STAGE92_MULTI_TIMESCALE_ATTRACTOR_STABILIZATION.md`
  - Documents the mechanism, controls, evidence, interpretation, and next gate.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_kernel_parts\pipeline.py holo_host\bionic_kernel_parts\generation.py holo_host\cli.py holo_host\cli_parts\user_sim.py holo_host\reply_api.py
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
python scripts\check_public_release_hygiene.py
git diff --check
python -m pytest -q
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage92OfflineOn-20260517 --chat-name Stage92OfflineOn-20260517 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage92OfflineNull-20260517 --chat-name Stage92OfflineNull-20260517 --channel cli --scenario free_dialogue --turns 20 --offline --disable-attractor-stabilization
```

Additional provider evidence was collected through `BionicUserSimulationHarness`
inside the local process to avoid dumping full transcript JSON to the terminal:

```text
Stage92ProviderOnA-20260517 / Stage92ProviderNullA-20260517
Stage92ProviderOnB-20260517 / Stage92ProviderNullB-20260517
Stage92ProviderOnC-20260517 / Stage92ProviderNullC-20260517
```

## Key Results

- Stage42 focused file now has `37 passed`.
- Cross-stage Stage32/39/42 regression has `56 passed`.
- Full suite has `554 passed, 5 subtests passed`.
- Public release hygiene passed.
- `git diff --check` reported no whitespace errors; Git printed only LF/CRLF
  conversion warnings for text files.
- Offline matched 20-turn free dialogue was intentionally inconclusive:
  attractor-on and attractor-null both returned `overall_score=0.8981`,
  `interaction_usefulness_score=0.793`, `continuity_score=0.8667`, and
  `issue_count=0`.
- Provider pair A was diagnostic, not acceptance evidence:
  attractor-on improved continuity but failed a visual-overclaim flag caused by
  the provider phrase `visible to me` without visual grounding.
- The visual summary guard was repaired with a failing regression test first.
- Provider pair B supported Stage92:
  - `decision=stage92_attractor_supported_under_matched_ablation`
  - attractor-on: `overall_score=0.9567`,
    `interaction_usefulness_score=0.9425`, `continuity_score=0.8667`,
    `issue_count=0`
  - attractor-null: `overall_score=0.9121`,
    `interaction_usefulness_score=0.955`, `continuity_score=0.5333`,
    `issue_count=1`
  - deltas: `overall_score_delta=0.0446`,
    `continuity_score_delta=0.3334`, `issue_count_delta=-1`
- Provider pair C replicated direction:
  - `decision=stage92_attractor_supported_under_matched_ablation`
  - attractor-on: `overall_score=0.9576`,
    `interaction_usefulness_score=0.9425`, `continuity_score=0.8667`,
    `issue_count=0`
  - attractor-null: `overall_score=0.9121`,
    `interaction_usefulness_score=0.955`, `continuity_score=0.5333`,
    `issue_count=1`
  - deltas: `overall_score_delta=0.0455`,
    `continuity_score_delta=0.3334`, `issue_count_delta=-1`

## Notes

- Stage92 does not add live transport, watcher authority, runtime decision
  authority, self-memory writes, durable policy writes, a second brain, or an
  unbounded loop.
- The supported provider pairs used structural prompt matching because one or
  both sides did not expose token usage metadata. The evaluator reports this as
  `token_metadata_complete=false` and `structural_prompt_match=true`.
- The result supports medium-term current-thread trajectory stabilization. It
  does not support durable policy sedimentation or persistent self-learning.

## Next

Stage93 should test long-horizon subject policy sedimentation under direct
controls. Keep any durable surface shadow-only, bounded, reversible, observable,
and separate from self-memory unless a later explicit plan approves more.
