# Stage230 Action Self-Feedback Loop

Kernel version remains `2.1.0`.

## Purpose

Stage230 makes self-feedback a first-class part of the agent loop. A tool return
is not treated as the end of a step. Every action observation is evaluated into
a structured feedback report before the next model decision or final answer.

The loop is:

```text
candidate action
-> host execution
-> observation ledger
-> self-feedback report
-> model sees feedback
-> continue or final
```

## Schema

```text
holo.stage230.self_feedback.v1
```

Each report records:

- action
- observation id/tool/status
- required observations
- evidence sufficiency
- recoverable failure
- evidence gap
- recommended next action
- canonical stop reason
- marginal utility
- grounded observation summary

## Runtime Behavior

The agent now emits:

```text
[self_feedback] <tool> sufficient=<true|false> next=<action> stop=<reason>
```

The same reports are inserted into the next model decision context as:

```text
context.self_feedback_reports
```

and into final metadata as:

```text
metadata.self_feedback_reports
```

## Current Rules

Initial feedback rules are intentionally bounded:

- `web_search ok` with results is not sufficient by itself. It recommends
  `open_page` because search snippets are not page evidence.
- `open_page ok` on an explicit URL is sufficient for summarization and
  recommends `answer_direct`.
- `open_page error` with HTTP diagnostics stops as `tool_failure_report`.
- empty search can be recoverable if another query exists.

This is a host-side feedback contract. The target intelligence path remains
model-first: the model should use the feedback reports to choose the next
meaningful action, while the host verifies ledgers and stop reasons.

## Why This Matters

Holo's core reliability depends on post-action self-evaluation. Without this
step, the system can:

- execute a tool but fail to use its result
- continue after sufficient evidence and create irrelevant failures
- claim a task is done without checking evidence gaps
- stop with an unclear or wrong reason

Stage230 turns this into an explicit engineering surface instead of relying on
style, persona, or hidden state.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage230_self_feedback_loop.py tests\test_stage220_context_infra.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage230-targeted2
```

Result:

```text
11 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
75 passed
```
