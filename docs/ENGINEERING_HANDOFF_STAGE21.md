# Stage21 Engineering Handoff

## Target Change

Stage21 is implemented as replay-gated policy sediment in Mind Graph. It converts repeated Stage13 calibration evidence into candidate overlays, promotes them only through replay approval, and applies promoted rows as bounded action-market score deltas.

## Runtime Files Changed

- `holo_host/mind_graph.py`
  - creates `policy_sediment`
  - exposes policy sediment wrappers
  - keeps canonical WeChat thread scoping
- `holo_host/mind_graph_parts/policy_sedimentation.py`
  - owns scenario buckets, candidate upsert, replay review, promotion, rollback, and diagnostics
- `holo_host/mind_graph_parts/outcome_appraisal.py`
  - creates/refreshes policy candidates after calibration updates
- `holo_host/policy_runtime/action_market.py`
  - applies promoted overlays after simulation overlay and before final selection
- `holo_host/memory_bridge.py`
  - exposes `mind_packet.stage21`
  - adds policy diagnostics and cache-clearing rollback
- `holo_host/reply_api.py`
  - exposes service/HTTP diagnostics and `accept_stage21`
- `holo_host/cli.py`
  - adds `show-policy-candidates`, `show-promoted-policies`, `rollback-policy`, `trace-policy-influence`, and `accept-stage21`
- `holo_host/reply_service_parts/acceptance.py`
  - adds the Stage21 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds HTTP acceptance dispatch

## Table Contract

Table: `policy_sediment`

Unique key:

- `(channel, thread_key, scenario_bucket, action_type)`

Fields:

- `policy_id`
- `channel`
- `thread_key`
- `scenario_bucket`
- `scenario_features_json`
- `action_type`
- `action_preference_shift`
- `support_count`
- `recency_support`
- `observed_regret_delta`
- `confidence`
- `replay_approval_status`
- `rollback_handle`
- `status`
- `evidence_refs_json`
- `metadata_json`
- `created_at`
- `updated_at`
- `promoted_at`
- `rolled_back_at`

Live promotion requires `status='promoted'` and `replay_approval_status='approved'`.

## Diagnostics

```bash
python -m holo_host show-policy-candidates --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host show-promoted-policies --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-policy-influence --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "continue this carefully"
python -m holo_host rollback-policy --id <policy_id>
```

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The gate checks candidate creation, replay approval, replay rejection, score influence, rollback, replay regret non-worsening, canonical thread identity, hard policy preservation, and Stage20 compatibility.

## Tests

```bash
pytest -q tests/test_stage21_policy_sedimentation.py tests/test_stage20_temporal_commitments.py tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py
pytest -q tests/test_stage13_calibration.py tests/test_stage14_replay.py tests/test_stage15_modularization.py
```

`tests/test_stage21_policy_sedimentation.py` covers:

- repeated evidence creates candidates
- replay approval/rejection gates promotion
- promoted overlays change action-market scoring
- rollback removes overlay effect
- Stage14 replay regret does not worsen
- canonical thread scoping prevents cross-contact leakage
- overlays do not grant send permission

## Contracts To Preserve

- Replay is the promotion gate.
- Sediment is a soft score overlay only.
- Rejected and rolled-back rows are inspectable but inactive.
- Hard policy, owner shutdown, secrets, auth, cooldowns, and initiative whitelist remain final.
- Processor calls stay inside the existing processor fabric.
- Stage18/19/20 continuity behavior remains unchanged.

## Done State

Stage21 is done when repeated experience can create stable default action preferences, those preferences are inspectable and reversible, replay remains the gatekeeper, and acceptance plus Stage13/14/15/18/19/20 regressions remain green.
