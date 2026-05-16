# Engineering Handoff Stage89

Stage89 adds a current-thread local policy vector on top of Stage88 adaptation.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `STAGE89_NAME`.
  - Adds `_IsolatedNoviceMemory._local_policy_vector()`.
  - Adds `stage89` to the simulation sidecar packet.
  - Adds `self_organization_policy_score` to Stage42 scorecards.
  - Extends interaction-usefulness markers to count natural provider phrasing
    observed in DeepSeek cells.
- `holo_host/bionic_kernel_parts/pipeline.py`
  - Exposes `stage89` as `capsule.working_field.local_policy_vector`.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds `Stage89 current-thread policy vector` to provider prompts.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage89 red/green tests for working-field visibility, provider prompt
    injection, query-conditioned dominant policy, natural task phrasing, and
    visual-resume next-input phrasing.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage89_policy_vector_is_visible_and_outcome_conditioned tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage89_provider_prompt_receives_local_policy_vector tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage89_policy_vector_changes_with_current_query_class -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage89_usefulness_score_accepts_natural_provider_task_phrasing -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage89_usefulness_score_accepts_visual_resume_next_input -q
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_kernel_parts\pipeline.py holo_host\bionic_kernel_parts\generation.py
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
git diff --check
python scripts\check_public_release_hygiene.py
python -m pytest -q
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage89FreeOffline-20260516 --chat-name Stage89FreeOffline-20260516 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage89FreeProviderA2-20260516 --chat-name Stage89FreeProviderA2-20260516 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage89FreeProviderB-20260516 --chat-name Stage89FreeProviderB-20260516 --channel cli --scenario free_dialogue --turns 8
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage89NoviceProviderRerun-20260516 --chat-name Stage89NoviceProviderRerun-20260516 --channel cli --scenario novice_intro --turns 5
```

## Key Results

- Stage89 red tests failed first for absent `stage89`, absent prompt injection,
  and absent query-conditioned `dominant_policy`; then passed.
- Stage42 tests: `24 passed`.
- Cross-stage Stage32/39/42 regression: `43 passed`.
- Full suite: `541 passed`.
- Public release hygiene passed; `git diff --check` reported no whitespace
  errors apart from CRLF conversion warnings.
- Offline 20-turn free dialogue: `overall_score=0.8981`,
  `interaction_usefulness_score=0.793`,
  `self_organization_policy_score=1.0`, `continuity_score=0.8667`,
  `issue_count=0`.
- DeepSeek V4 Pro free-dialogue repeated cells:
  `Stage89FreeProviderA2-20260516` and `Stage89FreeProviderB-20260516` both
  returned `overall_score=0.9581`, `interaction_usefulness_score=0.9275`,
  `self_organization_policy_score=1.0`, `continuity_score=0.8667`, and
  `issue_count=0`.
- DeepSeek V4 Pro novice rerun returned `overall_score=0.9612`,
  `interaction_usefulness_score=0.92`,
  `self_organization_policy_score=1.0`, `continuity_score=0.8667`, and
  `low_interaction_usefulness=false`.

## Notes

- `Stage89FreeProviderA-20260516` initially failed
  `low_interaction_usefulness` despite `overall_score=0.9265`; this exposed a
  measurement gap for natural useful provider phrasing.
- Stage89 is current-thread local policy, not durable policy sedimentation or
  cross-thread self-memory.

## Next

Stage90 should estimate local policy update deltas from outcome labels and
per-turn score failures, then verify on longer repeated provider cells.
