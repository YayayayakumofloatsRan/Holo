# Stage27 Long-Horizon Replay And Promotion Gates

## What Stage27 Adds

Stage27 adds an observational long-horizon blackbox soak harness on top of the live Stage26 runtime.

It does not add:

- a new autonomy path
- a hidden self-modification loop
- a second decision layer
- a widening of Stage22 send rights

It does add:

- persisted `blackbox_soak_runs` in `QueueStore`
- long-horizon scorecards over multi-hour and multi-day canary windows
- replay-on-live-artifacts inside the soak path
- blind export packets for transcript and human-vs-Holo review
- `accept-stage27`

## Runtime Surfaces

- `holo_host/store.py`
  - persists `blackbox_soak_runs`
- `holo_host/reply_api.py`
  - adds `run_blackbox_soak(...)`
  - adds `show_blackbox_scorecard(...)`
  - adds `export_blind_packets(...)`
  - adds `accept_stage27(...)`
  - extends Stage22 artifacts and canary trace metadata with bounded Stage24/25/26 provenance plus `identity_snapshot`
- `holo_host/cli.py`
  - adds `run-blackbox-soak`
  - adds `show-blackbox-scorecard`
  - adds `export-blind-packets`
  - adds `accept-stage27`
- `holo_host/reply_service_parts/endpoints.py`
  - adds `/accept-stage27`

## Scorecard Contract

The Stage27 scorecard includes:

- `identity_drift_across_days`
- `resume_success_after_interruption`
- `reread_history_rate`
- `clarification_thrash_rate`
- `duplicate_followup_rate`
- `latency_buckets_by_action_type`
- `policy_regret_on_live_artifacts`
- `raw_policy_regret_on_live_artifacts`
- `cross_thread_fragmentation_rate`
- `window_hours`
- `trace_count`
- `day_bucket_count`
- `thread_count`

Raw replay regret is the only regret value allowed for any Stage27 follow-up eligibility decision.

Rounded replay regret stays reporting-only.

## Blind Export Contract

Blind export writes operational artifacts only:

- `transcript_packets.jsonl`
- `comparison_bundles.jsonl`
- `human_vs_holo_review_packets.jsonl`
- `answer_key.json`

Blind packets must not include:

- canonical thread keys
- chat names
- raw source refs
- absolute file paths
- answer labels

The answer key stays separate from the blind packet files.

## Commands

```bash
python -m holo_host show-blackbox-scorecard --since-hours 168
python -m holo_host export-blind-packets --since-hours 168
python -m holo_host run-blackbox-soak --since-hours 168
python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat
```

## Acceptance And Regression

```bash
pytest -q tests/test_stage27_blackbox_soak.py tests/test_stage22_online_canary.py tests/test_stage14_replay.py
pytest -q
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat
```

## Guardrails

- Stage27 remains observational only.
- No self-memory writes are allowed from soak execution or blind export.
- No replay or safety gate may be bypassed.
- Online long-horizon canary remains deferred beyond Stage28.
