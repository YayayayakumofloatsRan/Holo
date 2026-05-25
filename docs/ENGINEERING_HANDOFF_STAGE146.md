# Engineering Handoff Stage146

## Summary

Stage146 adds a read-only unified biomimetic replay and deterministic benchmark bundle.

The replay exporter derives multi-turn rows from stored outbound reply metadata when available, paired with the preceding inbound text. It falls back to deterministic synthetic fixtures in dry-run or empty-runtime cases. The benchmark compares baseline conditions against the full Stage139-145 RK-CSM stack using deterministic fixture metrics.

## Files Changed

- `holo_host/stage146_biomimetic_replay.py`
- `holo_host/stage146_benchmark_bundle.py`
- `holo_host/cli.py`
- `tests/test_stage146_biomimetic_replay.py`
- `docs/STAGE146_BIOMIMETIC_REPLAY_BENCHMARK.md`
- `docs/ENGINEERING_HANDOFF_STAGE146.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schemas

- `holo.stage146.biomimetic_replay.v1`
- `holo.stage146.benchmark_bundle.v1`

## CLI

```powershell
python -m holo_host export-biomimetic-replay --thread-key cli:Stage146Fixture --limit 20 --output artifacts\stage146\stage146_replay.html --dry-run
python -m holo_host run-biomimetic-benchmark --output artifacts\stage146\stage146_benchmark.html --dry-run
```

Both commands write `.html`, `.json`, and `.jsonl` artifacts and do not require provider, network, WeChat, tool execution, or memory writes.

## Replay Row Shape

Each row includes:

- `turn_id`
- `time`
- `input_summary`
- `packet_budget`
- `tool_grounding`
- `memory_grounding`
- `memory_alignment`
- `semantic_novelty`
- `context_economy`
- `outcome_appraisal`
- `reaction_kernel_shadow`
- `visible_bubbles`
- `state_delta_summary`

## Benchmark Conditions

- `single-call baseline`
- `simple RAG baseline`
- `fixed two-bubble baseline`
- `multi-packet without Stage142/143/144/145`
- `full current RK-CSM stack`

The fixture is calibrated so the full current RK-CSM stack has a lower duplicate rate than the fixed two-bubble baseline.

## Constraints Preserved

- No provider calls.
- No WeChat start.
- No memory writes.
- No tool execution.
- No policy mutation.
- No second loop.
- No transport or watcher authority widening.
- Existing Stage139-145 ledgers are consumed only as stored metadata.

## Verification

Completed in this thread:

```powershell
python -m pytest tests\test_stage146_biomimetic_replay.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage146-targeted
# 7 passed in 0.38s

python -m holo_host export-biomimetic-replay --thread-key cli:Stage146Fixture --limit 20 --output artifacts\stage146\stage146_replay.html --dry-run
# wrote stage146_replay.html/.json/.jsonl with row_count=20

python -m holo_host run-biomimetic-benchmark --output artifacts\stage146\stage146_benchmark.html --dry-run
# wrote stage146_benchmark.html/.json/.jsonl with condition_count=5

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
# 538 passed in 66.34s

python scripts\check_public_release_hygiene.py
# Public release hygiene passed.

git diff --check
# exit 0; line-ending warnings only for existing Windows checkout behavior
```

## Next Suggested Stage

Stage147 should turn Stage146 replay output into a replay-driven calibration report for packet policy and reaction-kernel parameters while remaining shadow-only by default.
