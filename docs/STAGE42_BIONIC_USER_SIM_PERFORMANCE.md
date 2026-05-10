# Stage42: Bionic User-Simulation Performance Test

## Goal
Stage42 isolates the "new user meets Holo" test as an operational performance benchmark. The harness repeatedly talks to the bionic kernel as a first-time user, scores whether Holo keeps continuity, stays natural, avoids mechanism leakage, and is honest about visual capability boundaries.

This is a performance-test layer, not a WeChat rollout and not self-memory. It exists so bionic dialogue quality can be measured repeatedly without polluting Holo's subject memory or ordinary bionic traces.

## Public Surfaces
- `run-bionic-user-sim --thread-key ... --chat-name ... --channel cli [--scenario novice_intro] [--turns N] [--offline]`
- `show-bionic-user-sim-scorecard --suite novice_intro`
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
Stage42 writes only operational eval evidence through `QueueStore.agent_eval_runs` with stage `stage42-bionic-user-sim-performance` and suite `novice_intro`.

It does not write:
- Mind Graph self-memory
- live memory JSONL
- conversation archive
- ordinary bionic traces
- WeChat transport state

## Acceptance
`accept-stage42` composes `accept-stage41`, runs the isolated novice simulation, verifies required metrics are visible, checks the operational-only isolation contract, and confirms no normal bionic trace pollution.

Required validation:
- `pytest -q tests/test_stage42_bionic_user_sim.py`
- `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
- `git diff --check`
