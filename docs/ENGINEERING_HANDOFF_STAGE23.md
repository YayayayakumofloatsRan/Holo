# Stage23 Engineering Handoff

## Target Change

Stage23 orthogonalizes the Stage22 canary shell from the core reply semantics.

The key rule is simple:

- semantic reply results stay semantic
- delivery suppression is expressed separately

This stage also restores release parity by fixing artifact-ingest compatibility and raw-vs-display replay drift.

## Runtime Files Changed

- `holo_host/reply_api.py`
  - adds semantic vs delivery result fields
  - preserves semantic `action` and `reason` under shadow/canary suppression
  - keeps Stage22 traces and artifacts transport-facing through `returned_action`
  - adds legacy-compatible artifact ingest fallback
  - adds `accept_stage23`
- `holo_host/stage14_replay.py`
  - exposes raw prediction error and raw policy regret aggregation
- `holo_host/mind_graph.py`
  - exposes raw prediction error in action prediction traces
- `holo_host/mind_graph_parts/policy_sedimentation.py`
  - gates replay approval on raw replay metrics
- `holo_host/reply_service_parts/acceptance.py`
  - adds Stage23 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds `/accept-stage23`
- `holo_host/cli.py`
  - adds `accept-stage23`

## Result Contract

Required top-level fields on `handle_reply()` results:

- `semantic_action`
- `semantic_reason`
- `delivery_verdict`
- `delivery_send_allowed`
- `delivery_suppressed_by_canary`
- `returned_action`

Compatibility:

- `action == semantic_action`
- `reason == semantic_reason`
- `returned_action` is the only transport-facing action field

## Stage22 Contract After Stage23

- `disabled`: no Stage22 trace, no suppression
- `shadow`: preserves the semantic result and sets `returned_action="silence"` for delivery-capable actions
- `canary_live`: preserves semantic results and allows delivery only when whitelist, rollback, and rate gates pass

Stage22 still:

- records artifacts
- records `online_canary_traces`
- enforces whitelist/rate/rollback gates
- feeds replay-on-live-artifacts

Stage22 no longer:

- rewrites semantic `action` or `reason`

## Artifact Ingest Compatibility

`reply_api.ingest_artifact()` now:

- passes richer metadata when the memory backend supports it
- falls back to the legacy keyword surface for older/fake backends
- preserves helper-path normalization and dry-run behavior

## Replay Contract

- `aggregate_metrics` are display-rounded
- `raw_aggregate_metrics` are gating values
- Stage21/Stage23 replay approval paths must read raw metrics first

Raw-vs-display consistency is now explicit for:

- `risk_mae`
- `policy_regret_vs_best_available_action`

## Acceptance Commands

```bash
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat
pytest -q
```

## Regression Surfaces

```bash
pytest -q tests/test_holo_host.py
pytest -q tests/test_stage22_online_canary.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py
pytest -q tests/test_stage21_policy_sedimentation.py
```

## Contracts To Preserve

- memory is the self
- processors remain replaceable
- transport remains eyes and hands only
- action-market-first deliberation remains the decision path
- no second brain
- no new unbounded always-on loop
- no canary send-right expansion
- no change to canonical `wechat:<name>` identity
