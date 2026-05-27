# Engineering Handoff Stage159

Date: 2026-05-27

## Summary

Stage159 hardens the Agent Kernel v1 public surface before domain-module work begins. It sanitizes provider-private metadata, replaces shell-based engineering test execution with an allowlisted argv policy, upgrades readiness to active probes, adds an offline live-smoke HoloCoreBench mode, canonicalizes stop reasons, and exposes lightweight network health metadata.

This is a safety/reliability stage. It does not add provider calls, memory writes, WeChat starts, transport widening, live domain work, approval UI, or durable policy mutation.

## Files Changed

Added:

```text
holo_host/kernel_metadata_sanitizer.py
holo_host/safe_command_policy.py
holo_host/canonical_stop_reason.py
tests/test_stage159_kernel_hardening.py
docs/STAGE159_AGENT_KERNEL_HARDENING.md
docs/ENGINEERING_HANDOFF_STAGE159.md
```

Modified:

```text
holo_host/agent_event_stream.py
holo_host/agent_kernel_readiness.py
holo_host/cli.py
holo_host/codex_runner.py
holo_host/engineering_workspace_tools.py
holo_host/holo_core_bench.py
holo_host/processors.py
holo_host/reply_api.py
holo_host/stage135_i_state_topology.py
holo_host/stage151_tool_decision_loop.py
tests/test_stage153_interactive_cli.py
tests/test_stage154_engineering_action_fabric.py
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## New Schemas

```text
holo.stage159.kernel_hardening.v1
holo.stage159.public_metadata_sanitizer.v1
holo.stage159.safe_command_policy.v1
holo.stage159.canonical_stop_reason.v1
holo.stage159.readiness_probe.v1
holo.stage159.network_health.v1
```

## Runtime Propagation

Sanitized Stage152 reports are propagated through:

```text
ReplyPlan.debug
reply JSON
outgoing metadata
archive/observe metadata
Stage153 event stream source payloads
CLI /json
```

Canonical stop metadata is propagated as:

```text
canonical_stop_reason
canonical_stop_source
```

Network health metadata is propagated as:

```text
network_health
```

Stage135 topology exposes:

```text
kernel_hardening_node_count
canonical_stop_reason
canonical_stop_source
network_enabled
last_web_status
```

## Safe Command Policy

Stage154 `test_run` now parses allowed commands via `safe_command_policy.parse_allowed_command()` and calls `subprocess.run(argv, shell=False)`.

Allowed:

```text
python -m pytest ...
pytest ...
python scripts/check_public_release_hygiene.py
git status --short
git diff --
git diff -- <repo-relative-path>
```

Rejected:

```text
command chaining
pipes and redirects
package installs
curl/wget
deletion/reset/clean commands
credential reads
path escape outside repo root
```

## Active Readiness

`python -m holo_host agent-kernel-readiness` now runs active local probes instead of import-only checks:

```text
interactive_cli_probe
tool_loop_probe
engineering_action_probe
project_state_probe
context_compiler_probe
core_bench_probe
public_hygiene_probe
domain_scaffold_probe
```

Each check reports `holo.stage159.readiness_probe.v1`.

## Live-Smoke Bench

`python -m holo_host run-core-bench --output artifacts\stage159\holo_core_bench_live_smoke.html --mode live-smoke` uses local deterministic surfaces only:

```text
Stage153 event stream
Stage156 context compiler
Stage151 network-disabled rejection
Stage154 safe command rejection
Stage155 in-memory project state
Stage159 sanitizer
```

## Verification

Run during Stage159 implementation:

```text
python -m pytest tests\test_stage159_kernel_hardening.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage159-targeted
13 passed in 1.15s

python -m pytest tests\test_stage152_deepseek_tool_loop.py tests\test_stage153_interactive_cli.py tests\test_stage154_engineering_action_fabric.py tests\test_stage157_holo_core_bench.py tests\test_stage158_agent_kernel.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage159-neighbor
45 passed in 10.15s

python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage159-runtime
91 passed in 21.96s
```

Additional final verification:

```text
python -m holo_host agent-kernel-readiness
status=passed; passed_count=8; failed_count=0; active_probe_count=8

python -m holo_host run-core-bench --output artifacts\stage159\holo_core_bench_live_smoke.html --mode live-smoke
status=passed; category=kernel_hardening_live_smoke; artifacts html/json/jsonl written

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
672 passed in 102.82s

python scripts\check_public_release_hygiene.py
Public release hygiene passed

git diff --check
exit 0; only CRLF normalization warnings for touched existing files
```

## Constraints Preserved

- no provider calls added
- no memory writes added
- no WeChat start
- no transport authority widening
- no live domain-module behavior
- no approval UI
- no public raw `reasoning_content`
- Stage152 still retains `reasoning_content` internally only for DeepSeek continuity

## Next Suggested Stage

Stage160 should focus on provider/network abstraction and real web reliability after Stage159 hardening, while preserving the public/private metadata split and canonical stop reason contract.
