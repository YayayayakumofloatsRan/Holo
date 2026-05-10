# Engineering Handoff Stage42

## Status
Stage42 adds an isolated bionic user-simulation performance test. It lets Holo run repeated "first-time user" dialogue probes and persist a scorecard without starting WeChat or writing self-memory. The bionic kernel capsule also exposes an observational top-level `bionic_state` surface so bionic structure can be inspected before language output without changing the core phase contract.

## New Files
- `holo_host/bionic_user_sim.py`
- `holo_host/cli_parts/user_sim.py`
- `tests/test_stage42_bionic_user_sim.py`
- `docs/STAGE42_BIONIC_USER_SIM_PERFORMANCE.md`
- `docs/ENGINEERING_HANDOFF_STAGE42.md`

## Main Surfaces
- `python -m holo_host run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 12 --offline`
- `python -m holo_host show-bionic-user-sim-scorecard --suite novice_intro`
- `python -m holo_host show-bionic-user-sim-scorecard --suite free_dialogue`
- `python -m holo_host accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`

## Review Notes
- The simulation memory is local to the run and exists only to preserve continuity across the probe turns.
- The kernel is called with `record=False` and no store, so regular `bionic_agent_traces` are not polluted.
- Only `agent_eval_runs` receives the scorecard and run payload.
- The scorecard is intentionally operational. It should not be treated as a real external Turing-test pass.
- Manual Chinese free-dialogue review caught and fixed mechanical fallback phrasing: action-market reason leakage, `We were at We...` continuity duplication, broad visual-boundary triggers, and English fallback on Chinese continuation turns.
- The high-intensity `free_dialogue` branch now probes bionic identity, same-subject continuity, pressure handling, brain-like structure, and boundary reentry. These prompts intentionally test whether Holo behaves as a bionic subject rather than an assistant shell.
- `bionic_state` is observational only. It exposes positioning, consciousness-field summary, somatic proxy, active intent, uncertainty, continuity pressure, and hard boundaries, while preserving action-market authority, the Stage29/30 phase order, and self-memory isolation.
- A provider-backed eight-turn manual probe timed out at 180 seconds during this pass. Keep long provider-dialogue probes single-turn or explicitly timeout-bounded until provider latency/cache behavior is hardened.

## Follow-Up Constraints
- Expand scenarios only as isolated performance suites.
- Keep future visual tests honest: unsupported raw image input must be a boundary, not a guessed perception.
- Do not turn this benchmark into runtime decision authority.
- Do not restart WeChat as part of Stage42 validation.
