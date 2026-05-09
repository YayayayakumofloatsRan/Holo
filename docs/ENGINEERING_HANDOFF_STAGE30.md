# Stage30 Engineering Handoff

## Status
Stage30 adds an explicit unified subject-loop contract over the Stage29 bionic subject kernel. It is a structural/runtime contract stage, not a live online rollout.

## Code Surfaces
- `holo_host/subject_loop/`
  - defines `STAGE30_NAME`, `SUBJECT_LOOP_PHASES`, and `SubjectLoopTrace`
  - assembles bounded `subject_loop` payloads from existing bionic pipeline data
- `holo_host/bionic_kernel_parts/contracts.py`
  - adds `subject_loop` to the serialized bionic capsule
- `holo_host/bionic_kernel_parts/pipeline.py`
  - calls `assemble_subject_loop(...)` after outcome construction and before capsule serialization
- `holo_host/cli.py`
  - adds `accept-stage30`
- `tests/test_stage30_subject_loop.py`
  - validates loop order, invariants, bounded state-update writes, and CLI acceptance

## Contract
- The Stage29 public capsule phases remain unchanged for compatibility.
- Stage30 adds `subject_loop` as an explicit loop contract.
- `state_update.allowed_writes` can only be `[]` or `["operational_trace"]`.
- `self_memory_write`, `policy_write`, and `mind_graph_write` must stay `false`.
- The synthetic WeChat adapter must pass the same subject-loop invariants without starting transport.

## Review Notes
- Stage30 is not a second brain and has no scheduler.
- The loop is assembled from already-computed Stage29 data; it does not call processors or recall.
- This gives future adapters and APIs a single inspectable subject-loop contract before broader provider/API expansion.

## Validation Commands
- `pytest -q tests/test_stage30_subject_loop.py tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
