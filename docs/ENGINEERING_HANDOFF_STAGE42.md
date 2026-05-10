# Engineering Handoff Stage42

## Status
Stage42 adds an isolated bionic user-simulation performance test. It lets Holo run repeated "first-time user" dialogue probes and persist a scorecard without starting WeChat or writing self-memory.

## New Files
- `holo_host/bionic_user_sim.py`
- `holo_host/cli_parts/user_sim.py`
- `tests/test_stage42_bionic_user_sim.py`
- `docs/STAGE42_BIONIC_USER_SIM_PERFORMANCE.md`
- `docs/ENGINEERING_HANDOFF_STAGE42.md`

## Main Surfaces
- `python -m holo_host run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host show-bionic-user-sim-scorecard --suite novice_intro`
- `python -m holo_host accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`

## Review Notes
- The simulation memory is local to the run and exists only to preserve continuity across the probe turns.
- The kernel is called with `record=False` and no store, so regular `bionic_agent_traces` are not polluted.
- Only `agent_eval_runs` receives the scorecard and run payload.
- The scorecard is intentionally operational. It should not be treated as a real external Turing-test pass.

## Follow-Up Constraints
- Expand scenarios only as isolated performance suites.
- Keep future visual tests honest: unsupported raw image input must be a boundary, not a guessed perception.
- Do not turn this benchmark into runtime decision authority.
- Do not restart WeChat as part of Stage42 validation.
