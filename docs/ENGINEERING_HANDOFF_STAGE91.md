# Engineering Handoff Stage91

Stage91 adds a paired update-on/update-null ablation for Stage90 current-thread
policy updates.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `STAGE91_NAME`.
  - Adds `enable_policy_update` to `_IsolatedNoviceMemory` and
    `BionicUserSimulationHarness.run()`.
  - Adds an `update_null` Stage90 control that preserves packet shape and
    prompt structure while forcing `update_delta` to zero.
  - Adds `evaluate_stage91_adaptation_ablation()`.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds `control_condition` and `update_enabled` to the Stage90 provider
    prompt line.
- `holo_host/cli.py`
  - Adds `run-bionic-user-sim --disable-policy-update`.
- `holo_host/cli_parts/user_sim.py`
  - Passes the policy-update control flag into the harness.
- `holo_host/reply_api.py`
  - Allows API callers to pass `disable_policy_update`.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage91 red/green tests for update-null, harness metadata, and paired
    ablation evaluation.
- `docs/STAGE91_ADAPTATION_ABLATION.md`
  - Documents the mechanism, evidence, and bounded interpretation.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage91_update_null_preserves_shape_without_applying_delta tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage91_harness_records_update_null_condition tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage91_adaptation_ablation_evaluator_compares_matched_runs -q
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_kernel_parts\pipeline.py holo_host\bionic_kernel_parts\generation.py holo_host\cli.py holo_host\cli_parts\user_sim.py holo_host\reply_api.py
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91OfflineOn-20260517 --chat-name Stage91OfflineOn-20260517 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91OfflineNull-20260517 --chat-name Stage91OfflineNull-20260517 --channel cli --scenario free_dialogue --turns 20 --offline --disable-policy-update
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91ProviderOn-20260517 --chat-name Stage91ProviderOn-20260517 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91ProviderNull-20260517 --chat-name Stage91ProviderNull-20260517 --channel cli --scenario free_dialogue --turns 8 --disable-policy-update
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91ProviderOnB-20260517 --chat-name Stage91ProviderOnB-20260517 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage91ProviderNullB-20260517 --chat-name Stage91ProviderNullB-20260517 --channel cli --scenario free_dialogue --turns 8 --disable-policy-update
```

## Key Results

- Stage91 red tests first failed for absent evaluator/update-null support, then
  passed.
- Stage42 test file: `30 passed`.
- Offline matched 20-turn ablation:
  `decision=stage90_update_effect_inconclusive_under_matched_ablation`,
  both update-on and update-null returned `overall_score=0.8981`,
  `interaction_usefulness_score=0.793`, and `issue_count=0`.
- DeepSeek V4 Pro provider matched cell A:
  - `decision=stage90_update_supported_under_matched_ablation`
  - `token_relative_delta=0.033`
  - update-on: `overall_score=0.9525`,
    `interaction_usefulness_score=0.94`, `issue_count=0`,
    `total_tokens=5726`
  - update-null: `overall_score=0.9225`,
    `interaction_usefulness_score=0.9175`, `issue_count=2`,
    `total_tokens=5537`
- DeepSeek V4 Pro provider matched cell B:
  - `decision=stage90_update_supported_under_matched_ablation`
  - update-on: `overall_score=0.957`,
    `interaction_usefulness_score=0.94`, `issue_count=0`
  - update-null: `overall_score=0.9268`,
    `interaction_usefulness_score=0.9175`, `issue_count=2`
- In both provider cells, `update_on_delta_visible=true` and
  `update_null_delta_suppressed=true`.

## Notes

- Stage91 does not add a new runtime authority path. It only controls whether
  the simulation-local Stage90 delta is applied.
- `--disable-policy-update` is an experiment flag, not a product mode.
- The second provider pair did not expose token usage metadata, so measured
  prompt-cost comparison is available for cell A and structural matching is
  available for cell B.
- The result supports a current-thread adaptive-gain loop. It does not support
  persistent autobiographical memory, durable self-learning, model-weight
  learning, or human consciousness claims.

## Next

Treat Stage91 as the close of the Stage87-91 interaction self-organization
line. The next publishable extension should test multi-timescale organization:
short-term adaptive gain, medium-term attractor stabilization, and long-horizon
subject policy sedimentation under direct controls.
