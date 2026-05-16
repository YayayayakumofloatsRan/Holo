# Engineering Handoff Stage90

Stage90 adds current-thread policy update deltas from observed score failures.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `STAGE90_NAME`.
  - Stores per-turn `interaction_usefulness_score`, `score_delta`, and
    `failure_labels` in the simulation-local memory.
  - Adds `_IsolatedNoviceMemory._local_policy_update()`.
  - Feeds `stage90` into sidecar packets.
  - Applies Stage90 `updated_vector` back into the Stage89 `effective_vector`.
  - Adds `policy_update_delta_score` to Stage42 scorecards.
- `holo_host/bionic_kernel_parts/pipeline.py`
  - Exposes `stage90` as `capsule.working_field.local_policy_update`.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds `Stage90 outcome-score update` to provider prompts.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage90 red/green tests for update delta creation, working-field
    exposure, and provider prompt injection.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage90_score_failure_delta_updates_policy_vector tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage90_working_field_exposes_score_delta_update tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage90_provider_prompt_receives_score_delta_update -q
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_kernel_parts\pipeline.py holo_host\bionic_kernel_parts\generation.py
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
git diff --check
python scripts\check_public_release_hygiene.py
python -m pytest -q
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage90FreeOffline-20260516 --chat-name Stage90FreeOffline-20260516 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage90FreeProviderA-20260516 --chat-name Stage90FreeProviderA-20260516 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage90FreeProviderB-20260516 --chat-name Stage90FreeProviderB-20260516 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage90NoviceProvider-20260516 --chat-name Stage90NoviceProvider-20260516 --channel cli --scenario novice_intro --turns 5
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage90FreeProvider12-20260516 --chat-name Stage90FreeProvider12-20260516 --channel cli --scenario free_dialogue --turns 12
```

## Key Results

- Stage90 red tests first failed for absent `stage90`, absent
  `local_policy_update`, and absent provider prompt update line; then passed.
- Stage42 tests: `27 passed`.
- Cross-stage Stage32/39/42 regression: `46 passed`.
- Full suite: `544 passed`.
- Public release hygiene passed; `git diff --check` reported no whitespace
  errors apart from CRLF conversion warnings.
- Offline 20-turn free dialogue: `overall_score=0.8981`,
  `interaction_usefulness_score=0.793`,
  `self_organization_policy_score=1.0`,
  `policy_update_delta_score=1.0`, `continuity_score=0.8667`,
  `issue_count=0`.
- DeepSeek V4 Pro 8-turn free-dialogue repeated cells:
  - `Stage90FreeProviderA-20260516`: `overall_score=0.9525`,
    `interaction_usefulness_score=0.96`, `policy_update_delta_score=1.0`,
    `continuity_score=0.8667`, `issue_count=0`.
  - `Stage90FreeProviderB-20260516`: `overall_score=0.9572`,
    `interaction_usefulness_score=0.96`, `policy_update_delta_score=1.0`,
    `continuity_score=0.8667`, `issue_count=0`.
- DeepSeek V4 Pro 12-turn free dialogue:
  `overall_score=0.9569`, `interaction_usefulness_score=0.9467`,
  `policy_update_delta_score=1.0`, `continuity_score=0.8667`,
  `issue_count=0`.
- DeepSeek V4 Pro novice:
  `overall_score=0.9645`, `interaction_usefulness_score=0.936`,
  `policy_update_delta_score=1.0`, `continuity_score=0.8667`,
  `low_interaction_usefulness=false`.

## Notes

- Stage90 remains current-thread only. It does not persist learned policy or
  mutate model weights.
- `policy_update_delta_score` measures whether the update structure is visible
  and bounded, not whether there was a nonzero update in every turn.

## Next

Stage91 should run a paired adaptation ablation: Stage90 update-on versus
update-null provider cells with matched prompt cost and scenario mix.
