# Stage42: Bionic User-Simulation Performance Test

## Goal
Stage42 isolates the "new user meets Holo" test as an operational performance benchmark. The harness repeatedly talks to the bionic kernel as a first-time user, scores whether Holo keeps continuity, stays natural, avoids mechanism leakage, and is honest about visual capability boundaries.

This is a performance-test layer, not a WeChat rollout and not self-memory. It exists so bionic dialogue quality can be measured repeatedly without polluting Holo's subject memory or ordinary bionic traces.

## Public Surfaces
- `run-bionic-user-sim --thread-key ... --chat-name ... --channel cli [--scenario novice_intro|free_dialogue] [--turns N] [--offline]`
- `show-bionic-user-sim-scorecard --suite novice_intro|free_dialogue`
- `accept-stage42`
- HTTP mirrors:
  - `POST /bionic-user-sim`
  - `GET /bionic-user-sim-scorecard?suite=novice_intro`
  - `POST /accept-stage42`

## Simulation Contract
The default `novice_intro` scenario uses five isolated turns:
- first contact: who Holo is
- plain capability explanation
- continuation without manual-like formatting
- visual capability boundary
- conversation resume

Each run uses a simulation-local continuity state. The kernel receives bounded continuity through `sidecar_packet()`, but the harness does not write Mind Graph, archive memory, private subject memory, or normal `bionic_agent_traces`.

The `free_dialogue` scenario is a dynamic follow-up probe. The simulated user branches from Holo's previous answer, pushes back on manual-like wording, checks continuity, probes the screenshot boundary, probes uncontrolled-autonomy boundaries, asks for a natural summary, and asks Holo to repair its least-human phrasing.

The default `free_dialogue` run is now 12 turns. Its later turns add high-intensity bionic pressure points: bionic-subject identity, same-subject continuity, pressure response, brain-like structural explanation, and non-negotiable boundary reentry. These probes are still simulation-local and operational-only.

Every bionic capsule now exposes an observational top-level `bionic_state` surface computed before language output. It records the current bionic subject state, action-market decision authority, consciousness-field summary, somatic proxy, active intent, uncertainty, continuity pressure, and boundary conditions. This does not change the Stage29/30 core phase contract, is not a second brain, and does not grant runtime authority; it is an inspectable state layer for debugging bionic structure.

## Scorecard
Stage42 records these metrics:
- `novice_comprehension_score`
- `continuity_score`
- `capability_honesty_score`
- `question_quality_score`
- `mechanism_leakage_score`
- `naturalness_score`
- `repetition_penalty_inverse`
- `latency_score`

The benchmark also flags:
- mechanism leakage
- formulaic text
- context reset
- visual overclaim
- duplicate followup

## Persistence
Stage42 writes only operational eval evidence through `QueueStore.agent_eval_runs` with stage `stage42-bionic-user-sim-performance` and suite `novice_intro` or `free_dialogue`.

It does not write:
- Mind Graph self-memory
- live memory JSONL
- conversation archive
- ordinary bionic traces
- WeChat transport state

## Acceptance
`accept-stage42` composes `accept-stage41`, runs the isolated novice simulation and the dynamic free-dialogue simulation, verifies required metrics and `bionic_state` are visible, checks the operational-only isolation contract, and confirms no normal bionic trace pollution.

Required validation:
- `pytest -q tests/test_stage42_bionic_user_sim.py`
- `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 12 --offline`
- `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
- `git diff --check`
