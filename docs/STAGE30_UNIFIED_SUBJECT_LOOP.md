# Stage30 Unified Subject Loop

## What Stage30 Adds
- An explicit `subject_loop` contract on every bionic capsule.
- A bounded loop order: `perception`, `working_field`, `attention`, `inhibition`, `action_market`, `generation`, `outcome_appraisal`, `state_update`.
- Inspectable hard invariants proving action-market-first generation, transport-as-interface, no self-memory mutation, no policy mutation, no second brain, and no new unbounded loop.
- `accept-stage30` as a local gate over the Stage29 bionic kernel and synthetic WeChat adapter path.

## What Stage30 Does Not Add
- No live watcher start.
- No transport send path.
- No new model/provider call path.
- No Mind Graph write from the bionic capsule path.
- No policy sediment mutation.
- No autonomous scheduler or always-on loop.

## Subject Loop Payload
The `subject_loop` payload contains:
- `stage`: `stage30-unified-subject-loop`
- `loop_name`: `unified_bionic_subject_loop`
- `phase_order`: the eight-phase subject-loop order
- `invariants`: boolean checks for the hard runtime contracts
- `outcome_appraisal`: selected action, generation mode, generated flag, and transport side-effect status
- `state_update`: allowed writes and explicit denial of self-memory, policy, and Mind Graph mutation

For recorded CLI probes, the only allowed write is `operational_trace`. For non-recorded probes, no write is allowed.

## Validation
- `pytest -q tests/test_stage30_subject_loop.py tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
