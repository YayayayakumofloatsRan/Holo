# Kernel v3 Agent Loop Notes

Kernel v3 is a host-owned single-agent harness. The model may propose,
evaluate, or synthesize, but the host validates policy, executes tools,
journals every transition, checks evidence, and decides when to stop.

## Current Loop

One agent task runs through this chain:

1. compile context from journal
2. planner proposes one `CandidateAction`
3. `PolicyGate` validates the action and tool manifest
4. `ToolRegistry` executes only allowed actions
5. evaluator returns feedback
6. `WorkloopEvaluator` derives progress, repetition, evidence sufficiency,
   and a host-owned termination decision
7. `StopController` and loop guards stop, continue, ask the user, or fail
8. final answer or failure report is journaled

`LoopControllerV3` remains tool-name-agnostic. Concrete flows such as
retrieval and workspace answering are configured by recipes, registries, and
operators outside the controller.

## Semantic Task Graph

Model-backed semantic intake is now normalized into a host-visible
`TaskGraphProposal` and `TaskExecutionPlan` before an agent recipe is selected.
This graph/plan layer is not an execution engine. It is an audit and validation
layer over the model's proposed semantic structure:

- each proposed task node carries kind, goal, dependencies, capabilities,
  evidence requirements, and a suggested recipe mode;
- the host validates blocked capabilities, dependency integrity, node limits,
  and whether user confirmation is required;
- `AgentRuntime` journals `semantic_task_graph` with both the proposal and the
  validation decision;
- `AgentRuntime` journals `semantic_task_plan` with ordered host-visible steps,
  approval requirements, blocked capabilities, and a confirmation prompt;
- `LoopControllerV3` still receives only the selected recipe, planner,
  PolicyGate, registry, and evaluator. It remains tool-name-agnostic.

This is the anti-table path for compound and open-ended requests. The fake
semantic fallback stays conservative, while model mode can propose broad task
structure through JSON and the host validates it before anything runs.

Semantic intake is intentionally capability-driven. Model mode may emit an
open `kind` / semantic label such as a domain-specific research or operator
task; the host no longer collapses unknown labels into `direct_answer`. The
task graph preserves that label for audit, then compiles execution from
`required_capabilities` such as `retrieval.run`, `workspace.search`, or
`file.read`. Unknown labels with safe read capabilities can still select the
right recipe, while unknown labels that request blocked capabilities remain
non-executable and require user confirmation or scope reduction. This keeps
open-ended semantics in the processor layer and keeps permissions, tools,
evidence, and termination in the host layer.

When a semantic node needs concrete tool arguments, model mode can place them in
`metadata.capability_args` keyed by capability name. For example,
`{"workspace.search":{"query":"overview"},"file.read":{"path":"README.md"}}`
lets the host run a workspace read without guessing a filename from free text.
These arguments are still only proposals: the plan records them for audit, the
recipe turns them into bounded `CandidateAction` payloads, and `PolicyGate` plus
`ToolRegistry` remain responsible for validation and execution.

## Plan Review Commands

`ChatRuntime` exposes `/plan` as a host-owned review surface for the latest
`semantic_task_plan` in the thread:

- `/plan` or `/plan show` renders the latest model-proposed, host-validated
  plan;
- `/plan reject [plan_id] [reason]` journals a
  `semantic_task_plan_decision` and does not execute anything;
- `/plan approve [plan_id]` journals approval and runs only the first safe
  executable step through `AgentRuntime`;
- `/plan finalize [plan_id]` builds a plan-level final answer only from
  journaled outputs of completed approved steps.

Approval is deliberately narrow. It does not execute an arbitrary model graph
and it does not bypass `LoopControllerV3`. The selected step must be ready or
waiting for confirmation, use only safe read/respond/ask-user capabilities, and
then it is re-entered through the normal recipe, planner, PolicyGate, registry,
workloop, and finalization path. Blocked capabilities such as shell execution,
workspace writes, live transports, network fetches, and durable-memory writes
remain non-executable in this path.

Plan approval is also step-aware. Approved steps are recorded by
`plan_ref + node_id`, so repeated `/plan approve` calls do not rerun the same
tool step. A later safe step can run only after its dependency node was
approved and completed through the same journaled decision path. Dependent
`respond` or synthesis nodes are not executed as standalone direct answers,
because they would not carry the prior step's evidence context; those require a
future explicit plan-level synthesizer/finalizer instead of an implicit direct
fallback.

The plan finalizer is deliberately conservative. It does not call tools, does
not re-run semantic intake, and does not invent citations. It reads completed
approved step decisions, loads their `agent_final_answer` records, preserves
their `citation_refs` and `used_evidence`, and journals
`semantic_task_plan_final_answer` on the original plan task. If a dependency has
not completed, finalization fails with a journaled command result instead of
filling the gap.

For resident-style progress, `/plan approve` also converges to the same host
finalizer when there are no more safe tool steps and all finalizer dependencies
are complete. A repeated approval after finalization returns the existing
`semantic_task_plan_final_answer` instead of writing a duplicate.

When the active pending question is a host-generated plan confirmation, natural
language approval or rejection goes through the same bounded `chat.route`
processor contract as other turn routing. The provider may propose
`route="answer_pending_question"` with `command="approve_plan"` or
`command="reject_plan"`, and `ChatRuntime` then verifies that a pending plan
confirmation actually exists before mapping it to `/plan approve` or
`/plan reject`. There is no kernel-level phrase table for open-ended approval,
continuation, or summary semantics.

`/plan` also renders journal-derived progress. It reports per-step pending,
approved, completed, blocked, or finalized state from
`semantic_task_plan_decision`, spawned task ids, spawned statuses, dependency
final answer refs, and the plan-level final answer ref when present. This
progress is computed from journal records, not from model memory or hidden
state.

## Stop Semantics

The agent stops when one of these host-visible conditions is reached:

- sufficient evidence exists and evaluator feedback is terminal
- citations are required but missing and no allowed action can repair them
- the same action/query/path/observation/missing-evidence/failure repeats
- consecutive steps make no host-derived progress
- user input is required
- policy or resource guards block continuation
- loop limits are reached: steps, tool calls, network fetches, artifact bytes,
  or duration

Model feedback is never the only stop authority. It is combined with host
progress signals, repetition detection, evidence checks, and loop guards.

## Run Scope

Multi-turn and resumed tasks may share one task id, but each resume creates a
new run id. Runtime decisions that can affect completion are run-scoped:

- evidence sufficiency reads only current-run evidence, citations, and file
  observations
- retrieval and workspace finalization use only current-run grounding
- failure reports list current-run attempted actions, sources, missing
  evidence, and last observations
- repetition and no-progress counters are isolated per run
- recipe action ids are bound to the current run to avoid trace collisions

This prevents a later failed resume from completing with stale evidence from an
earlier successful run.

## Chat And Resident Model Path

`ChatRuntime` and the resident worker are routing shells around
`AgentRuntime`; they are not separate decision layers. They can now pass the
same Phase5 execution modes used by `holo-v3 agent`:

- `planner_mode`
- `evaluator_mode`
- `synthesizer_mode`
- `semantic_mode`
- `turn_router_mode`

The default remains fully offline fake mode. CLI model modes for `holo-v3 chat`
and `holo-v3 resident run/run-once` are gated by `HOLO_V3_LIVE_MODEL=1`, then
use the configured provider fabric. This lets a resident worker use model-backed
semantic intake, turn routing, or planner/evaluator/synthesizer behavior
without letting the worker execute tools directly, bypass PolicyGate, or become
a transport-level decision maker.

Resident outbox payloads keep the full `ChatRuntimeResult`. Resident run
results also surface `chat_route`, `command_result`, `pending_question`, and
`final_answer_ref` so a supervisor can see whether a message approved,
rejected, finalized, or answered a pending plan without scraping visible text.
Pending plan-confirmation outboxes are marked `answered` when the user's later
message approves or rejects the plan. Pending-user-input answer marking is
scoped to the answered task id, so multiple waiting questions in the same thread
do not clear each other.

Resident loop summaries include the queue health snapshot used to decide the
loop result. A loop no longer reports `completed` when unresolved failed,
dead-letter, retry-wait, delivery-failed, or pending-user-input work remains
after an idle turn. It reports `failed` for unresolved failed/dead-letter work,
`delivery_failed` for failed outbox delivery, `retry_wait` for delayed retry
work, and `awaiting_user_input` when the next useful step is a user reply. This
keeps long-running supervision from confusing "no claimable message right now"
with a healthy completed queue.

Failed delivery recovery is an explicit resident operation. `resident
retry-outbox <outbox_id>` transitions a `delivery_failed` outbox back to
`ready`, records retry metadata in the payload, and journals
`resident_outbox_retried`. This keeps transport recovery auditable without
treating it as a user acknowledgment.

Natural-language turn routing is processor-shaped rather than phrase-table
driven. A model or fake provider may emit a bounded `chat.route` proposal such
as `summary`, `continue_task`, `continue_plan`, `answer_pending_question`, or
`new_task`; `ChatRuntime` then validates that proposal against the current
thread state and journal. If the proposal asks to continue a plan, the host only
routes to `continue_plan` when an unfinished approved plan exists in the thread,
and it executes the same host-owned `/plan approve` path. Finalized plans are
not reused.

## Iteration 2026-05-31

Hardening completed in this iteration:

- blocked model `semantic.intake.response_hint` from becoming a final answer
- made repetition and no-progress detection run-scoped
- made evidence sufficiency and finalization grounding run-scoped
- made failure report attempt/observation summaries run-scoped
- bound recipe action ids to run ids
- added regression tests for stale retrieval evidence, stale workspace file
  reads, and semantic-intake answer leakage

Validation used:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_kernel_v3*.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q kernel_v3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_public_release_hygiene.py -q -p no:cacheprovider
git diff --check
```
