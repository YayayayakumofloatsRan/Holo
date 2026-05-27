# Stage159 Agent Kernel Hardening

Date: 2026-05-27

## Purpose

Stage159 hardens Agent Kernel v1 before domain modules begin. It is a reliability and public-surface safety stage, not a new autonomy stage.

The stage closes high-risk gaps found after Stage153-158:

- provider-private `reasoning_content` and internal tool-loop messages must not leak through public JSON, archive metadata, CLI `/json`, or event-stream payloads
- engineering `test_run` must use a strict allowlist and `subprocess.run(argv, shell=False)`
- `agent-kernel-readiness` must actively probe kernel surfaces instead of checking imports only
- HoloCoreBench needs an offline live-smoke mode over real local kernel surfaces
- stop reasons from packet, tool, native DeepSeek, and CLI layers need one canonical vocabulary
- network health must be visible without requiring live network in tests

## New Schemas

```text
holo.stage159.kernel_hardening.v1
holo.stage159.public_metadata_sanitizer.v1
holo.stage159.safe_command_policy.v1
holo.stage159.canonical_stop_reason.v1
holo.stage159.readiness_probe.v1
holo.stage159.network_health.v1
```

## Public Metadata Sanitizer

`holo_host/kernel_metadata_sanitizer.py` provides:

```text
sanitize_public_metadata(value)
build_public_stage152_report(stage152_report)
assert_no_private_reasoning(value)
```

Public Stage152 reports retain only audited fields such as tool counts, usage, stop reason, observations, grounding, and live trace. They drop raw provider messages, `assistant_messages_internal`, `final_decoded`, `raw_decoded`, and all `reasoning_content` text.

The sanitizer is applied before Stage152 metadata reaches reply plans, reply JSON, outgoing/archive metadata, event-stream payloads, and CLI `/json`.

## Safe Command Policy

`holo_host/safe_command_policy.py` parses allowed commands into argv lists and rejects everything else. Stage154 `test_run` now calls `subprocess.run(argv, shell=False)`.

Allowed commands:

```text
python -m pytest ...
pytest ...
python scripts/check_public_release_hygiene.py
git status --short
git diff --
git diff -- <repo-relative-path>
```

Rejected examples:

```text
python -m pytest -q && git status --short
python -m pip install requests
curl ...
git reset --hard
git diff -- ../secret.txt
```

There is still no approval UI. Rejected commands return a ledger row with `status=rejected` and `stderr_summary=command_not_allowlisted` or `path_escape`.

## Active Readiness Probes

`agent-kernel-readiness` now runs local probes:

- builds and sanitizes an event stream
- sanitizes a mocked Stage152 report
- checks safe-command allowlist behavior without running a shell
- performs in-memory `ProjectStateGraph` CRUD
- compiles context while preserving exact request and directives
- evaluates a HoloCoreBench fixture in memory
- confirms public hygiene script availability
- verifies domain modules remain scaffold-only

The report includes `kernel_hardening`, per-check `probe_schema`, `probe_type`, `failed_count`, and `warning_count`.

## Live-Smoke Core Bench

HoloCoreBench supports:

```powershell
python -m holo_host run-core-bench --output artifacts\stage159\holo_core_bench_live_smoke.html --mode live-smoke
```

`live-smoke` uses only local deterministic surfaces:

- Stage153 event stream
- Stage156 context compiler
- Stage151 network-disabled rejection
- Stage154 safe command allowlist/rejection
- Stage155 in-memory project state
- Stage159 sanitizer

It does not call providers, use real network, start WeChat, write memory, or execute arbitrary tools.

## Canonical Stop Reason

`holo_host/canonical_stop_reason.py` maps Stage143, Stage151, Stage152, and Stage153 stop sources into:

```text
final_answer_ready
goal_complete
needs_user_clarification
evidence_exhausted
budget_exhausted
low_marginal_utility
boundary_or_permission
tool_failure_report
model_final_no_tool_calls
unknown
```

Reply metadata now includes:

```text
canonical_stop_reason
canonical_stop_source
```

Stage153 event streams render `[stop] <canonical_stop_reason>`.

## Network Health

Stage151 exposes a lightweight network health report:

```text
network_enabled
provider
proxy_from_env
last_web_status
last_error
observed_at
```

When `runtime.network_enabled=false`, web actions still produce `rejected_network_disabled` observations. Tests do not require live network.

## Stage135 Topology

Stage135 can now expose a compact `kernel_hardening` node with canonical stop reason and network health counters. The node is observability-only and does not change packet policy.

## Boundaries

Stage159 does not add provider calls, memory writes, WeChat starts, transport widening, domain live work, approval UI, or new tool authority. Stage152 may retain `reasoning_content` internally for DeepSeek tool-loop continuity, but public surfaces receive only sanitized reports.
