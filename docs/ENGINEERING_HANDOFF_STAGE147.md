# Engineering Handoff Stage147

## Summary

Stage147 adds deterministic replay-driven calibration over Stage146 replay rows. It evaluates whether Stage144 packet-policy recommendations and Stage145 reaction-kernel delta candidates are supported by replay outcomes.

This is shadow-only analysis. It reports calibration findings and promotion candidates but does not apply live policy, mutate memory, call providers, execute tools, start WeChat, or widen transport authority.

## Files Changed

- `holo_host/stage147_replay_calibration.py`
- `tests/test_stage147_replay_calibration.py`
- `holo_host/cli.py`
- `docs/STAGE147_REPLAY_DRIVEN_CALIBRATION.md`
- `docs/ENGINEERING_HANDOFF_STAGE147.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## Schema

- `holo.stage147.replay_calibration.v1`

## CLI

```powershell
python -m holo_host evaluate-replay-calibration --replay-json artifacts\stage146\stage146_replay.json --output artifacts\stage147\stage147_calibration.html --dry-run
```

If `--dry-run` is set, or if the replay JSON is missing, Stage147 uses deterministic Stage146 synthetic rows.

## Runtime Propagation

Stage147 is not integrated into the live reply path. It writes standalone artifacts only:

- `.html`
- `.json`
- `.jsonl`

## Calibration Findings

Each finding records:

- `turn_id`
- `observed_issue`
- `stage144_recommendation`
- `stage145_delta_parameters`
- `later_or_fixture_outcome`
- `support_status`
- `reason`

## Promotion Candidates

Each candidate records:

- `target`
- `candidate_type`
- `recommended_change`
- `support_count`
- `counterexample_count`
- `confidence`
- `shadow_only=true`

Candidates are evidence summaries, not runtime changes.

## Constraints Preserved

- No provider calls.
- No tool execution.
- No memory writes.
- No policy mutation.
- No reaction-kernel delta application.
- No WeChat start.
- No transport or watcher authority widening.
- No second loop.

## Verification

Completed in this thread:

```powershell
python -m pytest tests\test_stage147_replay_calibration.py tests\test_stage146_biomimetic_replay.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage147-targeted
# 14 passed in 1.96s

python -m holo_host evaluate-replay-calibration --output artifacts\stage147\stage147_calibration.html --dry-run
# wrote stage147_calibration.html/.json/.jsonl with row_count=20 and promotion_candidate_count=4

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
# 545 passed in 99.08s

python scripts\check_public_release_hygiene.py
# Public release hygiene passed.

git diff --check
# exit 0; line-ending warnings only for existing Windows checkout behavior
```

## Next Suggested Stage

Stage148 should add a visual replay-calibration dashboard that overlays Stage146 trajectories and Stage147 support/counterexample findings, still without applying live policy.
