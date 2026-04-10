# Stage21 Engineering Handoff

## Target Change

Add reversible policy sediment and negotiated-will biasing on top of existing hard policy and action-market simulation.

## Files To Touch First

- `holo_host/policy.py`
  - keep hard gates authoritative
  - expose sediment only as soft context, not as permission
- `holo_host/policy_runtime/action_market.py`
  - apply sediment bias to candidate scoring
- `holo_host/policy_runtime/action_simulation.py`
  - include sediment rationale in simulated outcomes
- `holo_host/mind_graph.py`
  - persist policy sediment and counterevidence
  - update sediment from outcome appraisal evidence
- `holo_host/memory_bridge.py`
  - expose `mind_packet.stage21`
  - include applied policy keys and hard-gate preservation flag
- `holo_host/brain_ops.py`
  - update `trace_resistance` or add adjacent diagnostics for negotiated will
- `holo_host/reply_api.py`
  - add `accept_stage21`
  - expose `/accept-stage21`
- `holo_host/cli.py`
  - add `accept-stage21`
- `holo_host/reply_service_parts/acceptance.py`
  - add acceptance wrapper

## Tests To Add

- `tests/test_stage21_policy_sedimentation.py`

Minimum cases:

- positive repeated outcomes create soft sediment
- explicit correction lowers or supersedes sediment
- sediment biases action-market score but does not select action directly
- hard policy denial still denies
- initiative gates are not bypassed
- resistance posture uses sediment only when risk allows it
- sediment is canonical-thread scoped
- replay policy regret remains inside Stage14 threshold

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Expected supporting checks:

```bash
pytest -q tests/test_stage21_policy_sedimentation.py
pytest -q tests/test_stage20_temporal_commitments.py
python -m holo_host --config .holo_host.example.toml replay-policy-regret --fixture-path tests/fixtures/stage14
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Contracts To Preserve

- Hard policy, owner shutdown, secrets, and auth boundaries are not sediment scopes.
- Sediment cannot grant send permission.
- Sediment cannot bypass initiative whitelist, cooldown, or policy.
- Processor calls remain routed through the processor fabric.
- Negotiated will must be inspectable, reversible, and evidence-linked.

## Implementation Notes

Start with `negotiated_will_mode=observe` or equivalent config behavior if runtime risk is unclear. Biasing can be enabled after diagnostics show stable sediment rows.

Keep sediment narrow:

- thread-scoped by default
- confidence-gated
- evidence refs required
- counterevidence lowers confidence before broadening any rule

Do not convert tone preferences into safety constraints. A style negotiation can bias expression or action-market scoring, but it cannot rewrite policy.

## Done State

Stage21 is done when Holo can accumulate reversible, evidence-linked preferences and resistance tendencies that shape action-market scoring while hard policy remains unchanged.
