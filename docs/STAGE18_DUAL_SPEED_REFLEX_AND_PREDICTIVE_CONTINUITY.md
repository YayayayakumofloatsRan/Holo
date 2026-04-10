# Stage18 Dual-Speed Reflex And Predictive Continuity

## Goal

Stage18 turns Stage17 thread-resident active state into a dual-speed subject path:

- ordinary short low-risk WeChat turns can still use `active-thread-fast`
- if action-market selection chooses safe speech, generation can route through the existing `micro_fast` lane
- predictive continuity is carried in `ActiveThreadState` and is visible to prompts/diagnostics

This is not a second brain. Prediction is compact runtime metadata for the current canonical thread.

## Scope Boundary

- No new processor lane names.
- No new unbounded always-on loop.
- No transport-side decision branch.
- No prediction-only action selection.
- No default multi-line recent-history block in fast/reflex prompts.
- Explicit memory/history/factual/search/visual requests still escalate before active fast routing.
- Preserve canonical WeChat identity as `wechat:<chat_name>` unless the real transport id is a `wxid_` or chatroom key.

## Runtime Contract

Action selection remains first:

1. `MemoryBridge.sidecar_packet()` builds the packet and action market.
2. The subject runtime selects `selected_action`.
3. `CodexCliProcessor.generate()` chooses a generation lane from the selected action, uncertainty, and Stage18 reflex metadata.
4. Only safe speech actions can use `micro_fast`.

Conservative `micro_fast` criteria:

- `turn_plan.fast_path == true`
- `memory_route == "active_thread"`
- no `recall` / `deep_recall` tier and no recall reason
- no attachments, tools, search, visual, factual, or explicit memory/history request
- pressure is not high
- selected action is `reply_once`
- uncertainty is below `0.45`
- `reflex_eligibility == true`
- `active_prediction_confidence >= 0.55`
- `predicted_reply_pressure < 0.5`

High-conflict actions and uncertainty above the existing reply threshold still route to `kernel_xhigh`. Other ordinary cases stay on `subject_main`.

## Data Contract

`active_thread_state` stores `predictive_continuity_json` and exposes it as both:

- `active_thread_state.predictive_continuity`
- top-level aliases for the same fields

Minimum fields:

```json
{
  "predicted_next_user_act": "",
  "predicted_reply_pressure": 0.0,
  "likely_reference_targets": [],
  "expected_social_valence": "neutral",
  "reflex_eligibility": false,
  "turn_rhythm": {},
  "freshness_at": "",
  "active_prediction_confidence": 0.0
}
```

`mind_packet.stage18` exposes:

```json
{
  "fast_lane": true,
  "reflex_eligible": true,
  "prediction_confidence": 0.0,
  "predicted_next_user_act": "",
  "predicted_reply_pressure": 0.0,
  "likely_reference_targets": [],
  "micro_fast_candidate": true,
  "micro_fast_reason": "active_thread_reflex_candidate"
}
```

## Prompt Contract

For `active-thread-fast`, prompt context is ordered:

1. `continuity_summary`
2. `last_outbound_action`
3. `predictive_continuity`
4. optional one-line `last_exchange`

`history_lines_in_prompt` counts only verbatim recent-history lines. Stage18 also records `active_state_lines_in_prompt` and `predictive_lines_in_prompt`.

## Diagnostics

```bash
python -m holo_host show-fast-path-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host show-predictive-continuity --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-reflex-routing --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"
```

## Acceptance

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The gate verifies:

- Stage17 acceptance remains green.
- Predictive continuity fields are inspectable and persisted.
- Ordinary short active-thread speech can route generation to `micro_fast`.
- Explicit memory/history query still escalates.
- Low prediction confidence alone does not trigger `deep_recall`.
- Fast prompts use predictive continuity before any optional verbatim history.
- Action-market-first is preserved.

Recommended regression commands:

```bash
pytest -q tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Regression Risks

- Treating prediction as an action selector instead of prompt/routing metadata.
- Letting `micro_fast` bypass action-market selection.
- Letting explicit memory/history/factual requests stay on the reflex path.
- Counting compact active-state lines as verbatim history and masking recent-history growth.
- Allowing low confidence to become a recall escalation reason.
- Splitting WeChat identity between `Nemoqi` and `wechat:Nemoqi`.

## Rollback

Stage18 is additive. If `predictive_continuity_json` is missing or empty, Stage17 active-thread behavior still works and generation remains on `subject_main` unless existing high-risk rules upgrade to `kernel_xhigh`.
