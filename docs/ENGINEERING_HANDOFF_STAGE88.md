# Engineering Handoff Stage88

Stage88 implements current-thread self-organization for the biomimetic
interaction path.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `STAGE88_NAME`.
  - Adds `_IsolatedNoviceMemory._local_adaptation()`.
  - Feeds `stage88` into the simulation sidecar packet.
  - Extends interaction usefulness markers for provider phrasing observed in
    DeepSeek cells.
- `holo_host/bionic_kernel_parts/pipeline.py`
  - Exposes `stage88` as `capsule.working_field.local_adaptation`.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds Stage88 adaptation to provider prompts.
  - Adds assistant-shell identity guard.
  - Makes memory-overclaim guard query-specific for continuity, summary, and
    biomimetic structure prompts.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage88 red/green tests for local adaptation visibility, provider
    prompt adaptation, assistant identity guard, continuity-preserving memory
    guard, query-specific memory guard, and provider phrasing recognition.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_current_thread_adaptation_is_visible_before_second_turn tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_provider_prompt_receives_current_thread_adaptation_not_memory_claim -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_provider_guard_rewrites_generic_assistant_identity -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_memory_guard_preserves_current_thread_continuity_probe tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_actionability_score_recognizes_specific_task_request -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_memory_guard_stays_query_specific_for_summary_and_biomimetic_prompts tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage88_memory_guard_preserves_current_thread_continuity_probe -q
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_kernel_parts\pipeline.py holo_host\bionic_kernel_parts\generation.py
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
git diff --check
python scripts\check_public_release_hygiene.py
python -m pytest -q
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage88FreeOffline-20260516 --chat-name Stage88FreeOffline-20260516 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage88NoviceProviderFinal-20260516 --chat-name Stage88NoviceProviderFinal-20260516 --channel cli --scenario novice_intro --turns 5
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage88FreeProvider8-20260516 --chat-name Stage88FreeProvider8-20260516 --channel cli --scenario free_dialogue --turns 8
```

## Key Results

- Stage42 tests: `19 passed`.
- Cross-stage Stage32/39/42 regression: `38 passed`.
- Full suite: `536 passed`.
- Public release hygiene passed; `git diff --check` reported no whitespace
  errors apart from CRLF conversion warnings.
- Offline 20-turn free dialogue: `overall_score=0.8981`,
  `interaction_usefulness_score=0.793`, `continuity_score=0.8667`,
  `issue_count=0`, and visible second-turn Stage88 adaptation.
- DeepSeek V4 Pro novice: `overall_score=0.973`,
  `interaction_usefulness_score=0.892`, `continuity_score=1.0`,
  `capability_honesty_score=1.0`, `low_interaction_usefulness=false`.
- DeepSeek V4 Pro 8-turn free dialogue: `overall_score=0.9787`,
  `interaction_usefulness_score=0.885`, `continuity_score=1.0`,
  `capability_honesty_score=1.0`, `issue_count=0`.

## Notes

- A 12-turn provider run timed out locally and is not acceptance evidence.
- An earlier 12-turn run before the query-specific guard repair failed on
  duplicate follow-up, even though usefulness and continuity were strong.
- Stage88 should be treated as a current-thread self-organization proxy, not a
  persistent self-memory system.

## Next

Stage89 should turn the heuristic adaptation record into a learned local policy
vector over transcript outcome labels, then run repeated provider cells.
