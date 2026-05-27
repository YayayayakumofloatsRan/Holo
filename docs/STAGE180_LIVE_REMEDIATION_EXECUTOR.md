# Stage180 Live Remediation Executor

Stage180 executes available Stage179 remediation actions through existing safe host surfaces.

The control rule is:

```text
remediation action candidate -> host-safe execution -> observation ledger -> FSM re-entry -> stop re-evaluation
```

Stage179 made evidence gaps visible as next-action candidates. Stage180 turns the executable subset of those candidates into actual observations.

## Schemas

```text
holo.stage180.live_remediation_executor.v1
holo.stage180.live_remediation_execution_simulation.v1
```

## Executable Actions

Stage180 deliberately uses existing action surfaces. It does not create a new arbitrary tool executor.

Supported execution bridges:

```text
required_tool=web_search
  -> Stage151 web observation ledger through the network gate

required_tool=file_read
  -> Stage154 engineering action ledger using an explicit artifact path

required_tool=memory_recall
  -> Stage140-style memory observation ledger through an injected host recall surface
```

Unsupported or authority-sensitive actions remain rejected and visible.

## Runtime Re-entry

When execution succeeds, Stage180:

- appends web, memory, or engineering observations
- reruns the FSM with `stage180_live_remediation_execution`
- emits a `remediation_execute` FSM step
- suppresses stale `next_action_candidates` when the execution resolves the block
- replaces stale failure final text with a concise ledger-backed execution summary
- exposes `[remediation_exec]` in the event stream
- exposes a `live_remediation_executor` node in Stage135 topology

When execution is rejected or fails, the stop reason remains bounded:

```text
network disabled -> boundary_or_permission
tool failure -> tool_failure_report
missing artifact path -> needs_user_clarification
```

## CLI Simulation

```powershell
python -m holo_host run-live-remediation-execution --output artifacts\stage180\stage180_live_remediation_execution.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Boundaries

Stage180 does not:

- call provider models
- bypass the network gate
- bypass Stage159 safe command policy
- execute write actions
- write memory
- start WeChat
- widen transport authority
- expose hidden reasoning

## Why It Matters

This stage turns the evidence-action loop into an actual agent loop. A failed memory, source, or experiment claim can now become a host action, produce an observation ledger, and re-enter the same stop controller. That is the minimal practical form of continuous agent behavior.
