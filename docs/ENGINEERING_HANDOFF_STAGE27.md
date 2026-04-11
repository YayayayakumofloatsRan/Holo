# Stage27 Engineering Handoff

## Implemented Change

Stage27 turns the Stage22 canary trace stream into a replay-first long-horizon evaluation harness.

The live rule is:

- evaluate longer-horizon subject stability operationally
- keep all Stage27 state out of self-memory
- keep canary bounded, whitelist-only, rollback-safe, and reversible

## Runtime Surfaces

- `holo_host/store.py`
  - adds `blackbox_soak_runs`
  - stores scorecard, replay report, blind export metadata, and gate snapshot
- `holo_host/reply_api.py`
  - adds long-horizon scorecard computation
  - adds blind export packet generation
  - adds soak execution and Stage27 acceptance
  - extends Stage22 artifact and trace metadata with bounded Stage24/25/26 provenance and `identity_snapshot`
- `holo_host/cli.py`
  - adds:
    - `show-blackbox-scorecard`
    - `export-blind-packets`
    - `run-blackbox-soak`
    - `accept-stage27`
- `tests/test_stage27_blackbox_soak.py`
  - covers scorecard determinism, blind export behavior, persisted runs, raw-vs-rounded replay visibility, and fragmentation scoring

## Operational Contract

Stage27 outputs are operational only:

- soak run rows live in `QueueStore`
- blind packets live under the canary artifact tree
- replay report stays attached to the soak run

Nothing in Stage27 should update:

- `self_model_state`
- `autobiographical_state`
- promoted policy sediment
- send permissions

## Acceptance Checks

`accept-stage27` verifies:

- Stage26 acceptance stays green
- required long-horizon scorecard metrics exist
- replay report exposes both `aggregate_metrics` and `raw_aggregate_metrics`
- blind packets export and remain anonymized
- canary contract is still `host_side_shadow_first_block_only`
- raw live-artifact policy regret is the value used for Stage27 gate status
- no self-memory mutation occurred during soak execution

## Commands

```bash
python -m holo_host show-blackbox-scorecard --since-hours 168
python -m holo_host export-blind-packets --since-hours 168
python -m holo_host run-blackbox-soak --since-hours 168
python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Next Step

Any post-Stage27 work must start from an explicit re-plan.

Online long-horizon canary is still deferred.
