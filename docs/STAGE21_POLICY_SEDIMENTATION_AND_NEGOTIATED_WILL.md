# Stage21 Policy Sedimentation And Negotiated Will

## Goal

Stage21 turns repeated empirical calibration into inspectable, replay-gated, reversible policy sediment. Holo can form stable default action preferences under recurring scenarios without adding hidden training, a second policy brain, new processor lanes, or transport-side decision logic.

The implemented split is:

- Stage13 `action_calibration` remains the empirical evidence layer.
- Stage14 replay remains the approval gate.
- Mind Graph `policy_sediment` stores candidate/promoted/rejected/rolled-back policy overlays.
- The action market applies promoted overlays only as bounded soft score deltas.

## Boundary

- No hidden ML training.
- No black-box weights.
- No hard-policy rewrite.
- No owner shutdown, secrets, auth, or safety-scope sediment.
- No direct send permission changes.
- No initiative whitelist/cooldown/policy bypass.
- No new loop family.
- Preserve action-market-first deliberation.

## Runtime Surfaces

Mind Graph owns one table:

- `policy_sediment`
- unique key: `(channel, thread_key, scenario_bucket, action_type)`
- statuses: `candidate`, `promoted`, `rejected`, `rolled_back`
- replay statuses: `pending`, `approved`, `rejected`, `rolled_back`

Required fields:

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

Public helpers:

- `MindGraph.upsert_policy_candidate_from_calibration(...)`
- `MindGraph.list_policy_sediment(...)`
- `MindGraph.policy_scenario_bucket(...)`
- `MindGraph.promoted_policy_overlays(...)`
- `MindGraph.review_policy_candidate(...)`
- `MindGraph.rollback_policy(...)`
- `MindGraph.show_policy_candidates(...)`
- `MindGraph.show_promoted_policies(...)`

## Scenario Buckets

Scenario buckets use inspectable features only:

- `channel`
- canonical `thread_key`
- Stage19 thread warmth when already present in packet context
- relationship tension/risk band
- correction-heavy vs relaxed pattern
- low-risk short turn vs high-risk ambiguity
- action family
- base Stage13 calibration bucket

No raw history block, learned weight vector, or opaque feature is stored.

## Promotion Contract

Candidates are written from outcome appraisal only after repeated calibration evidence reaches:

- support count `>= 3`
- confidence `>= 0.55`
- evidence refs present
- bounded non-zero preference shift
- observed regret delta indicates likely benefit

Promotion requires replay approval. `review_policy_candidate(...)` sets `replay_approval_status`; a candidate promotes only when approval is `approved` and the candidate remains promotable. Rejection and rollback are terminal, inspectable states for v1.

## Action Market Contract

Promoted policies apply after simulation/empirical overlay and before final action selection metadata is frozen. The overlay:

- matches same canonical thread, scenario bucket, and action type
- clamps total score delta to `[-0.18, 0.18]`
- annotates candidates with `policy_sedimentation_delta`, `policy_sedimentation`, `policy_scenario_bucket`, and rollback handles
- never sets `send_allowed`
- never bypasses explicit memory/history/factual/search/visual escalation

Supported v1 action targets:

- `silence`
- `defer_reply`
- `push_back`
- `counter_offer`
- `continuity_defense`
- `proactive_ping`

`mind_packet.stage21` exposes:

```json
{
  "sediments_visible": true,
  "sediment_bias_applied": true,
  "applied_policy_keys": [],
  "scenario_bucket": "",
  "hard_gate_preserved": true,
  "negotiated_will_mode": "active_soft"
}
```

## Diagnostics

```bash
python -m holo_host show-policy-candidates --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host show-promoted-policies --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-policy-influence --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "continue this carefully"
python -m holo_host rollback-policy --id <policy_id>
```

HTTP/service surfaces mirror the CLI:

- `/policy-candidates`
- `/promoted-policies`
- `/policy-influence`
- `/rollback-policy`
- `/accept-stage21`

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The gate verifies:

- repeated appraisal evidence creates a policy candidate
- replay can approve a candidate
- replay can reject a candidate
- a promoted policy changes action-market scoring in a controlled fixture
- rollback removes the overlay effect
- replay policy regret is not worse
- canonical WeChat identity remains `wechat:<name>`
- hard policy gates remain final
- Stage20 acceptance remains green

Required regressions:

```bash
pytest -q tests/test_stage21_policy_sedimentation.py tests/test_stage20_temporal_commitments.py tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py
pytest -q tests/test_stage13_calibration.py tests/test_stage14_replay.py tests/test_stage15_modularization.py
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Regression Risks

- Soft sediment acts like a hard policy override.
- Rejected or rolled-back rows continue to affect ranking.
- Scenario buckets are too broad and leak across contacts.
- Initiative timing is biased past whitelist/cooldown/policy gates.
- Replay approval is skipped.
- Stage14 replay baselines drift without an explicit reason.

## Rollback

Stage21 degrades by ignoring `policy_sediment` rows or rolling promoted rows back. Hard policy behavior and Stage20 temporal continuity are unchanged by rollback.
