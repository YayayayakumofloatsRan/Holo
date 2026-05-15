# Engineering Handoff Stage87

Stage87 implements a performance-first biomimetic interaction repair.

## Changed Files

- `holo_host/bionic_user_sim.py`
  - Adds `interaction_usefulness_score`.
  - Adds low-usefulness failure detection.
  - Adds explicit scoring support for biomimetic explanation prompts.
- `holo_host/bionic_kernel_parts/response_shaping.py`
  - Replaces low-information first-contact and fallback wording.
  - Converts bionic state into current evidence, missing input, and next step.
- `holo_host/bionic_kernel_parts/generation.py`
  - Adds provider prompt instructions for active-inference style interaction.
  - Guards unverified cross-conversation memory claims.
- `tests/test_stage42_bionic_user_sim.py`
  - Adds Stage87 red/green tests for useful interaction and memory-claim guard.
- `tests/test_stage39_bionic_turing_benchmark.py`
  - Updates the old "answer directly" assertion to the new concrete-next-step
    behavior.

## Commands Run

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage87_usefulness_penalizes_safe_but_empty_visible_context_replies tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage87_offline_reply_turns_bionic_state_into_actionable_next_step -q
python -m pytest tests\test_stage42_bionic_user_sim.py::Stage42BionicUserSimulationTests::test_stage87_provider_guard_rewrites_unverified_cross_conversation_memory_claim -q
python -m pytest tests\test_stage42_bionic_user_sim.py -q
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage87NoviceOffline-20260516 --chat-name Stage87NoviceOffline-20260516 --channel cli --scenario novice_intro --turns 5 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage87FreeOffline-20260516 --chat-name Stage87FreeOffline-20260516 --channel cli --scenario free_dialogue --turns 20 --offline
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage87NoviceProviderGuarded-20260516 --chat-name Stage87NoviceProviderGuarded-20260516 --channel cli --scenario novice_intro --turns 5
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage87FreeProviderRerun-20260516 --chat-name Stage87FreeProviderRerun-20260516 --channel cli --scenario free_dialogue --turns 12
python -m pytest tests\test_stage32_response_shaping.py tests\test_stage39_bionic_turing_benchmark.py tests\test_stage42_bionic_user_sim.py -q
python -m py_compile holo_host\bionic_kernel_parts\generation.py holo_host\bionic_kernel_parts\response_shaping.py holo_host\bionic_user_sim.py
```

## Key Results

- Stage42 tests: `13 passed`.
- Adjacent regression: `32 passed`.
- Offline novice: `overall_score=0.9709`, `interaction_usefulness_score=0.818`.
- Offline 20-turn free dialogue: `overall_score=0.895`, `interaction_usefulness_score=0.774`, `issue_count=0`.
- DeepSeek V4 Pro novice: `overall_score=0.8596`, `interaction_usefulness_score=0.74`, `passed=true`.
- DeepSeek V4 Pro 12-turn free dialogue: `overall_score=0.9677`, `interaction_usefulness_score=0.9183`, `issue_count=0`.

## Next

Proceed to Stage88: within-thread self-organization and self-learning proxy.
Implement a local adaptation signal over current transcript outcomes, then test
whether provider novice continuity improves without claiming persistent memory.
