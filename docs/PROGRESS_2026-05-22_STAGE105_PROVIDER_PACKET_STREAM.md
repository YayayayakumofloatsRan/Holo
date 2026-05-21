# Progress 2026-05-22: Stage105 Provider Packet Stream

## Goal

Turn the theory of finite provider packets into a real Holo control surface: decide how many packets to send, when to stop, when to send punctually, and when to route to tools.

## Changes

- Added `holo_host/stage105_provider_packet_stream.py`.
- Added `stage105-packet-stream` CLI.
- Injected `stage105` and `provider_packet_stream` into `MemoryBridge._finalize_stage2_packet()`.
- Exposed Stage105 from `inspect_mind`.
- Added tests in `tests/test_stage105_provider_packet_stream.py`.
- Saved implementation plan at `docs/superpowers/plans/2026-05-22-stage105-provider-packet-stream.md`.

## Behavior

Stage105 now recognizes these packet decisions:

- `send_multi`: broad recall or uncertain context.
- `send_once`: sufficient context.
- `send_punctual`: deadline pressure.
- `do_not_send`: silence/defer action.
- `tool_first`: query or action requires external tool evidence.

## Evidence

Focused test:

```powershell
pytest -q tests\test_stage105_provider_packet_stream.py --basetemp .holo_runtime\pytest-stage105
```

Result:

```text
7 passed
```

Runtime checks:

```powershell
python -m holo_host stage105-packet-stream --query "回忆任何事情？" --max-packets 4
```

Observed `packet_count=3`, `send_decision=send_multi`, `stop_reason=bounded_stream_ready`.

```powershell
python -m holo_host stage105-packet-stream --query "查一下最新状态" --max-packets 4
```

Observed `next_action=tool_request`, `stop_reason=tool_first`, tool `external_lookup`.

In-process `MemoryBridge.inspect_mind()` also exposed:

- `stage105.packet_count=3`
- `stage105.send_decision=send_multi`
- `provider_packet_stream.packet_count=3`

The already-running live HTTP process may not show `stage105` until restarted with this commit.

## Guardrails

- Stage105 only plans packet/tool flow; it does not execute tools.
- It does not train or mutate provider weights.
- It does not start WeChat or any Windows watcher.
- It is observable through CLI and `inspect_mind`.
