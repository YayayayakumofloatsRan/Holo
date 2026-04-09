# Stage 14 Offline Replay And Policy Evaluation

## Goal
Build one deterministic offline replay harness so Holo's calibration quality and policy quality can be measured from fixed fixtures instead of inferred from ad hoc traces.

## Boundary
- Replay stays offline and deterministic.
- Replay must not mutate live runtime state by default.
- Read-only archive and calibration-history loading only; artifacts are the only default writes.
- Keep action-market-first deliberation and existing reducers as the evaluator path.
- Do not add a second policy brain or new always-on loop.

## Replay Sources
- `synthetic_fixture`
  - repo-tracked JSON fixtures under `tests/fixtures/stage14/`
- `archive_fixture`
  - read-only fixtures derived from archive rows
- `calibration_history_fixture`
  - read-only fixtures derived from persisted outcome/calibration history

## Canonical Fixture Shape
- Metadata:
  - `fixture_id`
  - `source_type`
  - `channel`
  - `thread_key`
  - `chat_name`
  - `query`
  - `expected_best_action`
  - optional `scenario_tags`
- Prior state:
  - `intent_state`
  - `relationship_state`
  - `game_state`
  - `affect_state`
  - `drive_state`
  - `value_state`
  - `conflict_state`
  - `world_state`
  - optional `calibration_rows`
- Realized evidence:
  - `selected_action`
  - `predicted_outcome`
  - `realized_outcome`
  - `usage_total_tokens`
  - `usage_rows`
  - `evidence_refs`

## Metrics
- `response_quality_mae`
- `relational_delta_mae`
- `risk_mae`
- `calibration_support_by_action_type`
- `false_initiative_block_rate`
- `overlong_reply_rate`
- `stiffness_overflow_rate`
- `cost_per_successful_turn`
- `policy_regret_vs_best_available_action`

## CLI Surfaces
- `python -m holo_host --config .holo_host.example.toml replay-calibration-fixture`
- `python -m holo_host --config .holo_host.example.toml replay-policy-regret`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`

## Default Artifact Layout
- Default output root:
  - `artifacts/replays/stage14/<run-id>/`
- Generated files:
  - `summary.json`
  - `summary.md`
- Curated release notes may be copied into `docs/releases/`, but normal replay runs should stay in `artifacts/`.

## Acceptance Checklist
- Replay metrics are reproducible across repeated runs on the same fixtures.
- Policy regret and calibration MAE are inspectable from CLI/API output.
- Replay updates only isolated temporary graph/runtime state.
- Canonical direct-message WeChat identity remains `wechat:<name>` through fixture normalization.
- At least one controlled fixture shows non-zero regret and a better available action.
- At least one controlled fixture shows initiative false-block accounting.
- At least one controlled fixture shows overlong or stiffness overflow accounting.
- `accept-stage14` returns machine-readable checks.

## Rerun Commands
- Full synthetic replay:
  - `python -m holo_host --config .holo_host.example.toml replay-calibration-fixture --fixture-path tests/fixtures/stage14`
- Policy regret replay:
  - `python -m holo_host --config .holo_host.example.toml replay-policy-regret --fixture-path tests/fixtures/stage14`
- Acceptance:
  - `python -m holo_host --config .holo_host.example.toml accept-stage14`
- Full regression suite:
  - `pytest -q`

## Rollback Notes
- If replay artifacts are correct but ranking impact regresses, disable only the replay overlay read path before touching the appraisal reducer.
- If fixture normalization regresses identity continuity, fix canonical `wechat:<name>` normalization before changing metric formulas.
