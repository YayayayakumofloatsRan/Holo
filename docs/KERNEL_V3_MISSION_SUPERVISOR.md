# Kernel v3 Mission Supervisor

Kernel v3 now has two loop layers:

1. `LoopControllerV3` is the inner step loop. It compiles context, asks the
   planner for one action, validates the action through `PolicyGate`, executes
   the tool/operator, journals the observation, asks the evaluator, and applies
   local workloop termination.
2. `MissionRuntime` is the outer global task loop. It preserves the user's root
   goal across inner runs, summarizes what the previous run actually did, and
   decides whether the mission needs another run, a final answer, user input, a
   blocked state, or a failure report.

The model still only proposes or assesses. The host still validates, executes,
journals, and stops.

## Runtime Flow

```text
user goal
-> MissionRuntime creates MissionState
-> AgentRuntime runs the existing inner loop
-> MissionSupervisor collects run_delta from JournalStore
-> MissionSupervisor builds MissionAssessment
-> if incomplete and viable: journal MissionDirective and resume same task
-> if covered: return final answer
-> if no viable strategy: return failure report
```

Tool failures are treated as observations. They are not automatically mission
failures. A failed retrieval, timeout, empty search result, or budget guard can
still lead to another run when the mission supervisor sees a materially
different safe strategy.

## Processor Packets

`mission.assess` is a schema-first processor task. It receives:

- the root mission goal;
- current mission state;
- the latest agent result;
- the run delta from journal records;
- the host rule assessment.

The required JSON output is a coverage decision, missing requirements, a
coverage score, a concise reason summary, and an optional next directive. It
must not include chain-of-thought, direct tool calls, memory writes, invented
sources, or permission grants.

The planner and evaluator packets also receive:

- `mission_context`: mission state and current directive;
- `thread_rag_context`: recent thread turns, assistant results, task trace,
  evidence refs, citation refs, and failure diagnostics.

This is how a later agent loop can know the original global goal and the useful
history of previous attempts.

## Thread RAG Boundary

`ThreadWorkingMemoryProvider` is a journal-derived, thread-scoped working-memory
surface. It is intentionally not durable memory and does not write facts. It
only compacts same-thread records into model-visible context.

Future durable memory or vector/RAG stores should plug into this boundary by
returning additional bounded context slices. They should not bypass journal,
policy, memory approval, or redaction.

## Journal Records

Mission execution journals:

- `mission_created`
- `mission_run_delta`
- `mission_assessment`
- `mission_directive`
- `mission_iteration`
- `mission_decision`
- `mission_final_answer`
- `mission_failure_report`
- `mission_ask_user`

These records are the handoff surface for debugging why a task continued,
stopped, retried with a new strategy, or failed.

## Current Limits

- The mission supervisor has a rule-first assessment path and an optional
  model-backed `mission.assess` path.
- The thread RAG surface is lightweight: recency plus task trace, not vector
  search.
- Durable memory remains separate and host-controlled. Mission supervision does
  not auto-commit memory.
- Search/retrieval strategy quality is still determined by the retrieval
  subsystem and planner prompts. Mission supervision ensures failed attempts
  feed back into the next loop instead of silently ending the user task.
