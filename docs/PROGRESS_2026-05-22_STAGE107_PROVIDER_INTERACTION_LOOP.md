# Progress 2026-05-22: Stage107 Provider Interaction Loop

## Goal

Turn the bottom provider mechanism into a visible loop:

- finite packet
- provider return
- compressed delta
- next packet or local tool observation
- explicit stop condition

## Implemented

- Added `holo_host.stage107_provider_interaction_loop`.
- Added deterministic provider-return delta compression.
- Added state-machine phases:
  - `provider_packet`
  - `provider_return`
  - `distill_delta`
  - `tool_request`
  - `tool_observation`
  - `stop`
- Added provider tool-call interruption behavior:
  - accepted provider tool calls become local `tool_request` events
  - execution authority remains local
- Added `stage107-interaction-loop` CLI dry-run.
- Added focused Stage107 tests.

## Evidence

```powershell
python -m pytest -q tests\test_stage107_provider_interaction_loop.py --basetemp .holo_runtime\pytest-stage107-green3
```

Observed:

- `6 passed`

Manual dry-run:

```powershell
python -m holo_host stage107-interaction-loop --query "回忆任何事情？"
```

Observed:

- `stage=107`
- `status=ready_to_continue`
- `next_action=send_provider_packet`
- only the next `context_seed` packet is emitted when no provider return is
  present
- no-send Stage105 plans terminate as `stop` instead of sending provider packets

## Boundary

Stage107 does not call provider APIs and does not execute tools. It makes the
interaction loop inspectable before the live executor is attached.
