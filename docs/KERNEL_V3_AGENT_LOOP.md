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

Tool execution is bound to the policy decision for the exact action. A
`PolicyDecision` with `allowed=True` cannot be reused for a different
`action_id`; `ToolRegistry` blocks that as `policy_decision_action_mismatch`
before calling the tool executor. This keeps direct registry callers aligned
with the loop's host-owned validation path.

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

## Durable Memory Boundary

Durable memory uses a split audit model. `MemoryStore` is the memory subsystem's
append-only fact log and can retain the approved memory item/proposal payloads
needed for replay and export. The task Journal remains the agent run audit
surface, so `MemoryPipeline` journals only memory manifests: ids, scope,
state, provenance refs, risk flags, preview/hash/length fields, and redaction
metadata. Shadow candidates, proposals, committed items, and tombstones do not
duplicate full candidate text, proposed item bodies, or deletion reasons into
the main Journal. Approval is still host controlled, and secret-like candidates
are rejected before a shadow candidate or proposal is recorded.
`MemoryStore.inspect()` follows the same operator-facing rule: active, expired,
deleted, and pending proposal samples expose ids, state, scope, and
summary preview/hash metadata rather than full summaries.

## Plan Review Commands

`ChatRuntime` exposes `/plan` as a host-owned review surface for the latest
`semantic_task_plan` in the thread:

- `/plan` or `/plan show` renders the latest model-proposed, host-validated
  plan;
- `/plan reject [plan_id] [reason]` journals a
  `semantic_task_plan_decision` and does not execute anything;
- `/plan approve [plan_id]` journals approval and runs only the first safe
  executable step through `AgentRuntime`;
- `/plan run [plan_id]` repeatedly runs safe executable steps through
  `AgentRuntime` until a host boundary is reached;
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
approved and completed through the same journaled decision path. Completion is
not inferred from approval alone; the spawned child task must have a journaled
`agent_final_answer` before it can unlock dependent steps. Failed or
needs-user-input child tasks stop the plan run instead of allowing downstream
work to proceed with missing evidence. Dependent
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

For resident-style progress, `/plan run` is the bounded workloop form of plan
execution. It recomputes the next executable step from journal state after each
child task, records every approval as `semantic_task_plan_decision`, and stops
when a child task needs user input, fails, no safe step remains, or the
plan-level finalizer can produce an answer from completed dependency outputs.
Blocked write/shell/live-transport/memory capabilities remain boundaries, not
things to skip silently. `/plan approve` still performs a single-step approval;
if no more safe tool steps remain and finalizer dependencies are complete, it
also converges to the same host finalizer. A repeated approval after
finalization returns the existing `semantic_task_plan_final_answer` instead of
writing a duplicate.

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

Network fetch limits are costed before execution, not only after a tool returns.
For `network` side-effect actions, the loop reads a generic cost from payload
fields such as `max_fetches` / `network_fetch_count`, or from the manifest's
`default_network_fetch_cost`. The loop does not branch on concrete tool names;
this lets a future live retrieval/search operator declare bounded page-fetch
cost without getting a special path in `LoopControllerV3`.

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

Resident outbox payloads keep a compact `ChatRuntimeResult` manifest. Resident
run results also surface `chat_route`, compact `command_result`,
`pending_question`, and `final_answer_ref` so a supervisor can see whether a
message approved, rejected, finalized, or answered a pending plan without
scraping visible text. Large command payloads such as rendered traces are stored
as preview/hash manifests in resident payloads and resident journal events.
Outbox administration events such as `resident_outbox_ack` and
`resident_outbox_retried` journal the same manifest projection, not the full
reply body or payload.
Resident inbox administration and claim events likewise record transport state,
text preview/hash, and metadata manifests rather than duplicating the full user
message body in resident-specific journal records.
Pending plan-confirmation outboxes are marked `answered` when the user's later
message approves or rejects the plan. Pending-user-input answer marking is
scoped to the answered task id, so multiple waiting questions in the same thread
do not clear each other.

Resident loop summaries include the queue health snapshot and scheduler health
used to decide the loop result. A loop no longer reports `completed` when
unresolved failed, dead-letter, failed-outbox, retry-wait, delivery-failed,
pending-user-input, or scheduler-failed work remains after an idle turn. It
reports `failed` for scheduler tick/status failures, unresolved
failed/dead-letter inbox work, or failed agent/command outbox work,
`delivery_failed` for failed outbox delivery, `retry_wait` for delayed retry
work, and `awaiting_user_input` when the next useful step is a user reply. This
keeps long-running supervision from confusing "no claimable message right now"
with a healthy completed queue.

Resident queue inspection is bounded at the queue layer. Health issues and
sample inbox/outbox rows are queried with SQL limits and clamped before
rendering, so a long-running resident database can be inspected without loading
or returning every historical message. Inspection samples are operational
manifests: message text is exposed only as a bounded preview plus length/hash,
and metadata/outbox payloads are value-hash manifests rather than raw JSON
bodies.

Worker exception records also journal the queue state that was actually written
after containment. `resident_inbox_failed` includes `resulting_status`,
`attempts`, and `next_attempt_at_ms`, and its state delta uses `retry_wait`,
`dead_letter`, or the observed queue status rather than a generic `failed`.
This keeps resident traces aligned with the retry/dead-letter state machine.
`resident-trace` renders a bounded tail view by default and reports how many
older resident records were truncated, so trace inspection remains usable after
long resident runs.

The resident scheduler is deliberately below the agent loop. It stores local
schedule records, ticks due schedules, and enqueues normal resident inbox
messages with deterministic message ids. It does not route chat turns, execute
tools, call providers, or synthesize answers. Once a scheduled item enters the
inbox, `ResidentRuntime` handles it through the same `ChatRuntime` and
`AgentRuntime` path as any other message. The `resident schedule-*` commands
are local operator surfaces, not live transport integrations. Long-running
workers can opt into `resident run --tick-schedules` or `resident run-once
--tick-schedules`; without that explicit flag, run and run-once preserve normal
queue-only behavior. Schedule ticks and inspection samples are clamped inside
`ResidentScheduler`, so a large CLI/runtime limit cannot cause one resident
iteration to enqueue or render an unbounded number of schedules. Scheduler
journal records and inspection samples use schedule/message manifests with
text preview/hash and metadata manifests rather than duplicating the full
scheduled prompt body. `resident status` and `resident inspect` include
schedule health, including due schedules
and unbounded recurring schedules, so operators can see whether a resident loop
should run with schedule ticking enabled. When
schedule ticking is enabled and no inbox item is claimable, `resident run`
reports `waiting_for_schedule` instead of plain `idle` if a future active
schedule is still pending; the loop result includes `schedule_status` so a
supervisor can see the next due time.
Resident run loops also accept `--max-duration-ms` as a host-owned wall-clock
budget in addition to `--max-iterations`. Hitting that budget returns
`max_duration_ms` and journals the loop result; it does not let the model decide
termination and it does not change `run-once` semantics.

`resident doctor` is the read-only operator snapshot for long-running work. It
aggregates queue inspection, schedule inspection, and any configured durable
memory, research corpus, or retrieval-provider inspections into one status,
issue list, and action list. It does not create memory/corpus stores unless
their CLI paths are configured, and it does not enqueue, approve memory,
retrieve, fetch, or execute tools. When the journal and artifact store are
configured, doctor also asks durable memory inspection to verify committed
memory provenance refs and artifact refs, using metadata/blob presence checks
only. Retrieval-provider inspection is capability-only: it reports fake/corpus/
future-live provider metadata, network capability, and research-profile support
without running retrieval or reading artifact bodies. Retrieval-provider errors,
such as an empty fallback search chain, are promoted into the doctor status and
recommended actions so a resident supervisor does not mistake an unusable
research configuration for a healthy worker. Doctor also isolates component
inspection failures: if queue, schedule, memory, corpus, or retrieval inspection
raises, the report still returns `error` with the component, failure code,
exception type, and redacted exception message instead of crashing the operator
path. This keeps long-running memory and research operation auditable without
exposing raw artifact payloads.

Crash recovery is outbox-aware. If a worker already wrote an outbox but crashed
or lost ownership before completing the inbox message, a later worker that
reclaims the inbox first checks for the existing `in_reply_to` outbox. When it
finds one, it journals `resident_outbox_recovered`, completes the inbox, and
does not re-run `ChatRuntime` or the agent loop. This prevents duplicated tool
work and duplicated agent journal records after a partial worker failure.

Failed delivery recovery is an explicit resident operation. `resident
retry-outbox <outbox_id>` records retry metadata in the payload and journals
`resident_outbox_retried`. Ordinary reply outboxes return to `ready`. Pending
user-input outboxes remember the state they failed from and return to
`pending_user_input`, so retrying question delivery does not collapse a waiting
question into an ordinary ready reply. Generic `resident ack --status ready` is
not a retry path for failed delivery, and `resident ack --status acknowledged`
cannot clear a `delivery_failed` outbox. Operators must retry delivery first,
then acknowledge the retried outbox after actual delivery. This keeps transport
recovery auditable without treating it as a user acknowledgment.

Natural-language turn routing is processor-shaped rather than phrase-table
driven. A model or fake provider may emit a bounded `chat.route` proposal such
as `summary`, `continue_task`, `continue_plan`, `answer_pending_question`, or
`new_task`; `ChatRuntime` then validates that proposal against the current
thread state and journal. If the proposal asks to continue a plan, the host only
routes to `continue_plan` when an unfinished approved plan exists in the thread,
and it executes the same host-owned `/plan run` path. Finalized plans are not
reused.

Live semantic scenario tests must not include answer-key JSON in provider
prompts. They provide only the contract, task context, host rules, and
acceptance criteria. The local validator checks the returned JSON afterward.
This keeps DeepSeek/OpenAI-compatible smokes from becoming prompt-level
golden-output copying while preserving deterministic fake-provider tests.

## Iteration 2026-05-31

Hardening completed in this iteration:

- blocked model `semantic.intake.response_hint` from becoming a final answer
- made repetition and no-progress detection run-scoped
- made evidence sufficiency and finalization grounding run-scoped
- made failure report attempt/observation summaries run-scoped
- bound recipe action ids to run ids
- removed answer-key JSON from live semantic scenario prompts
- added bounded `/plan run` for journal-driven multi-step plan continuation
- added regression tests for stale retrieval evidence, stale workspace file
  reads, semantic-intake answer leakage, scenario prompt leakage, and
  multi-step plan continuation boundaries

Validation used:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_kernel_v3*.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q kernel_v3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_public_release_hygiene.py -q -p no:cacheprovider
git diff --check
```
