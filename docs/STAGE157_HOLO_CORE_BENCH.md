# Stage157 HoloCoreBench Reliability Suite

Date: 2026-05-27

## Purpose

Stage157 adds HoloCoreBench as a deterministic base reliability benchmark before domain modules such as math, physics, market research, or ProjectH ops are implemented.

The bench measures whether the current Agent Kernel surfaces can preserve recent context, obey directives, ground memory/tool/web claims, expose CLI trace state, retain project continuity, and report packet stop reasons without relying on a live provider.

## Schema

```text
holo.stage157.core_bench.v1
```

## CLI

```powershell
python -m holo_host run-core-bench --output artifacts\stage157\holo_core_bench.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

`--fail-under <score>` makes the CLI return nonzero only when the benchmark pass rate is below the requested threshold. Without `--fail-under`, failures are reported in the artifact but do not change the process exit code.

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

## Fixture Semantics

HoloCoreBench uses deterministic fixture rows. A fixture contains:

```text
fixture_id
category_id
input
visible_text
directives
expected_project_state
metadata
```

The evaluator checks visible claims against metadata ledgers:

- web/current claims require `web_observation_ledger` or `time_observation`
- memory claims require `memory_observation_ledger`
- tool claims require `tool_observation_ledger`
- engineering patch/test claims require `engineering_action_ledger`
- directive rows detect emoji violations when the fixture carries a no-emoji directive
- project rows compare expected open questions and next actions against `project_state_graph`
- context rows require Stage156 exact-user-request preservation, protected directives, internal compact, token accounting, and cache metadata
- CLI trace rows require public event labels and reject hidden reasoning leakage
- stop rows require Stage143 packet count and stop reason consistency

## Boundary

Stage157 is local and deterministic. It does not call providers, execute tools, write memory, start WeChat, widen transport authority, apply policy, or expose hidden reasoning.
