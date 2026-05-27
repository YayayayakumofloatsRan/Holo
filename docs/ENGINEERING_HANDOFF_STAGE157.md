# Engineering Handoff Stage157

Date: 2026-05-27

## Summary

Stage157 upgrades the prior import-only core bench into HoloCoreBench, a deterministic reliability suite over the base Agent Kernel surfaces. It produces HTML, JSON, and JSONL artifacts and scores memory honesty, directive adherence, project continuity, web/time grounding, tool grounding, engineering claim grounding, context compaction, CLI trace visibility, stop reasons, cache behavior, context waste, and latency estimates.

## Files Changed

- `holo_host/holo_core_bench.py`
- `holo_host/cli.py`
- `tests/test_stage157_holo_core_bench.py`
- `docs/STAGE157_HOLO_CORE_BENCH.md`
- `docs/ENGINEERING_HANDOFF_STAGE157.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New CLI

```powershell
python -m holo_host run-core-bench --output artifacts\stage157\holo_core_bench.html --dry-run
```

Optional threshold:

```powershell
python -m holo_host run-core-bench --output artifacts\stage157\holo_core_bench.html --dry-run --fail-under 0.95
```

The CLI returns nonzero only when `--fail-under` is provided and the benchmark pass rate is below that value.

## Categories

```text
recent_recall
directive_adherence
one_turn_vs_durable_instruction
project_state_recall
task_continuation
web_time_grounding
tool_claim_grounding
engineering_patch_test_claims
context_compaction_integrity
cli_trace_visibility
stop_reason_correctness
```

## Metrics

```text
pass_rate
unsupported_claim_rate
directive_violation_rate
memory_honesty_score
tool_grounding_score
project_continuity_score
context_waste_score
cache_hit_ratio
latency_estimate
```

## Runtime Boundary

Stage157 is analysis-only. It does not call providers, execute tools, write memory, start WeChat, widen transport authority, apply policy, or expose hidden reasoning.

## Test Results

Executed in `D:\Holo\holo`:

```powershell
python -m pytest tests\test_stage157_holo_core_bench.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage157-targeted
9 passed in 0.81s

python -m holo_host run-core-bench --output artifacts\stage157\holo_core_bench.html --dry-run
status=passed; artifacts written to artifacts\stage157\holo_core_bench.html, .json, and .jsonl

python -m pytest tests\test_stage158_agent_kernel.py tests\test_stage157_holo_core_bench.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage157-stage158
16 passed in 0.87s

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
652 passed in 93.03s

python scripts\check_public_release_hygiene.py
Public release hygiene passed.

git diff --check
Passed with line-ending warnings only.
```

## Next Suggested Stage

Stage158 can package the Agent Kernel v1 readiness and domain scaffolds now that Stage156 and Stage157 are real runtime surfaces rather than import-only checks.
