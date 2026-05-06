# Stage18 Engineering Handoff

## Implemented Change

Stage18 adds a conservative dual-speed subject path:

- `active_thread_state.predictive_continuity_json` persists bounded next-turn continuity metadata.
- `MemoryBridge` exposes `mind_packet.stage18` on active-thread and non-active paths.
- `CodexCliProcessor` can route safe short active-thread speech generation to existing `micro_fast`.
- Fast prompts use predictive continuity before any optional verbatim exchange line.

The watcher/transport still does not decide. The action market still selects before language generation.

## Runtime Surfaces

- `holo_host/mind_graph.py`
  - schema migration for `predictive_continuity_json`
  - deterministic inbound/outbound predictive reducer
  - top-level aliases for the Stage18 predictive fields
- `holo_host/memory_bridge.py`
  - Stage18 packet diagnostics
  - active fast eligibility gated by `reflex_eligibility` and confidence
  - diagnostics: fast-path metrics, predictive continuity, reflex routing trace
- `holo_host/processors.py`
  - `_select_reply_lane()` conservative lane policy
  - prompt ordering: continuity summary, last outbound action, predictive continuity, optional one exchange
- `holo_host/reply_api.py`
  - `accept_stage18`
  - `show_fast_path_metrics`
  - `show_predictive_continuity`
  - `trace_reflex_routing`
- `holo_host/cli.py`
  - `accept-stage18`
  - `show-fast-path-metrics`
  - `show-predictive-continuity`
  - `trace-reflex-routing`

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat
```

Expected pass checks:

- predictive fields visible
- ordinary short turn routes generation to `micro_fast`
- explicit memory query escalates
- low confidence alone does not deep recall
- predictive continuity persists
- fast prompt uses predictive continuity before history
- action market first preserved
- Stage17 acceptance green

## Regression Commands

```bash
pytest -q tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat
```

## Contracts To Preserve

- Do not add a Stage18 daemon loop.
- Do not let prediction choose, send, or schedule.
- Do not add a transport-side branch for prediction.
- Do not bypass processor routing.
- Do not add new lane names.
- Do not expand fast prompts into multi-line recent-history prompts.
- Do not treat low confidence or prediction mismatch as a deep recall reason.

## Notes For Stage19

Stage19 can reuse Stage18 predictive continuity as one input to an attention frontier, but must keep that frontier bounded by thread key, count, and expiry. It should not broaden `micro_fast` routing or initiative sending rights.
