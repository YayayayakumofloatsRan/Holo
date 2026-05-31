# Kernel v3 Phase7 Plan

Phase7 starts from the current `kernel-v3` baseline, not from the older
Phase3.1 retrieval-readiness baseline. The Phase7 planning baseline is after
Phase4 retrieval, Phase5 processors, Phase6 agent runtime, Phase6.1 workloop,
Phase6.2 chat runtime, Phase6.3 semantic intake, and the run-scoped loop
grounding hardening.

## Decision

Phase7 should not rebuild the harness. It should add a controlled durable
memory subsystem that follows the existing kernel shape:

- journal remains the source of truth for task execution
- model output may propose memory, but host code validates and commits it
- memory writes are reviewable, auditable, scoped, and deletable
- context injection uses a frozen snapshot at run/resume boundaries
- no subagents, live transports, scheduler, or background autonomy in the
  first memory-core slice

Resident runtime is a valid later Phase7 slice, but it should not be coupled to
the initial memory store and proposal pipeline. The memory core must be correct
before an always-on worker can safely use it.

## Current Baseline

Already present:

- `JournalStore`: append-only JSONL plus SQLite index
- `ArtifactStore`: artifact refs and blob payload handling
- `ContextPackCompiler`: budgeted context sections and redaction metadata
- `RetrievalOperator`: evidence, citation, report journaling
- `ProcessorFabric`: schema-first processor calls with fake-first providers
- `AgentRuntime`: direct, retrieval, workspace, clarification, failure flows
- `WorkloopEvaluator`: host-derived progress, repetition, evidence, stop
- `ChatRuntime`: thread state, pending user input, resume, summaries
- semantic intake: model/provider JSON can propose unavailable capabilities such
  as `durable_memory:write`; the host validates and blocks them

Not yet present:

- first-class `MemoryItem`, `MemoryProposal`, `ShadowCandidate`, provenance
- durable-memory store, index, TTL, deletion, or export
- memory proposal review/approval pipeline
- durable memory context section
- chat memory admin commands
- resident inbox/outbox, lease, scheduler, or worker

## Phase7.0: Durable Memory Core

Add:

- `kernel_v3/memory/contracts.py`
- `kernel_v3/memory/store.py`
- `kernel_v3/memory/privacy.py`
- `kernel_v3/memory/__init__.py`

Contracts:

- `MemoryItem`
- `MemoryProposal`
- `ShadowCandidate`
- `ProvenanceRef`
- `MemoryTombstone`
- `MemoryRecallResult`

Store rules:

- append-only memory log for audit
- SQLite index for lookup, status, TTL, scope, and dedupe keys
- no vector database dependency in MVP
- all writes are deterministic and idempotent by stable ids
- deletion is tombstone-first; active recall skips deleted/expired records

Privacy rules:

- reject secret-like content by default
- sensitive/private memory requires review
- no API keys, cookies, tokens, private keys, or raw env values may be stored
- provenance must point back to journal/artifact refs

Tests:

- create/list/recall memory item
- rebuild index from log
- TTL expiry removes item from recall
- tombstone hides item from recall but preserves audit
- secret-like text is rejected
- duplicate stable id is idempotent

Implementation note:

- `kernel_v3.memory` now provides the Phase7.0 core surface:
  `MemoryItem`, `MemoryProposal`, `ShadowCandidate`, `ProvenanceRef`,
  `MemoryTombstone`, `MemoryRecallResult`, `MemoryStore`, stable id helpers,
  and privacy validation.
- The store uses an append-only memory log plus a rebuildable SQLite metadata
  index. It has no vector database dependency and no live provider dependency.
- `MemoryStore.commit()` rejects secret-like content before writing an audit
  event. Duplicate writes with the same stable id and identical payload are
  idempotent; conflicting payloads for the same id are rejected.
- Recall skips deleted and expired items by default. Tombstones preserve the
  audit chain while preventing future default recall.
- `tests/test_kernel_v3_phase7_memory_store.py` covers core storage, rebuild,
  TTL, tombstone, privacy rejection, idempotency, shadow candidates, and
  proposals.

## Phase7.1: Proposal Pipeline

Add:

- `kernel_v3/memory/pipeline.py`
- `kernel_v3/memory/migration.py`
- processor schemas for `memory.propose` and optionally `memory.review`

Pipeline:

1. derive `ShadowCandidate` from provider-owned semantic intake that declares
   `durable_memory:write`
2. validate privacy, scope, and evidence refs
3. dedupe by `kind + scope + dedupe_key`
4. detect conflicts instead of overwriting silently
5. create `MemoryProposal`
6. require approval unless policy marks it safe for host auto-commit
7. commit `MemoryItem` only through host pipeline

Agent integration:

- model-backed semantic intake can identify `durable_memory:write`
- model cannot call a memory commit tool directly
- finalization may create proposals, not committed memory
- ask-user can request approval for pending proposals

Tests:

- model-declared memory write creates proposal, not committed memory
- approve commits item
- reject leaves audit but no active recall
- conflict goes to review
- model malformed memory proposal does not crash the loop
- processor calls are journaled without secrets

Implementation note:

- `kernel_v3.memory.pipeline.MemoryPipeline` is now the only Phase7 path from
  semantic memory intent to durable-memory write. It creates shadow candidates
  and proposals first; it never commits unless `approve_proposal()` is called by
  host-side code.
- `AgentRuntime` accepts an optional `MemoryStore`. Without it, the runnable
  skeleton keeps the old no-durable-memory behavior. With it, a provider-owned
  `durable_memory:write` semantic-intake result produces a pending proposal
  while the task still asks the user for clarification/approval.
- `MemoryStore.decide_proposal()` records approval/rejection decisions in the
  append-only memory log and replays them on reload. Candidate/proposal writes
  are tolerant of duplicate stable ids so resume and resident retries can stay
  idempotent.
- `MemoryPipeline.approve_proposal()` is idempotent for already approved
  proposals. A repeated CLI/chat approval returns the existing committed item
  without appending duplicate approval or commit journal records. If a crash
  left an approved proposal without its committed item, the second approval
  repairs the missing commit while preserving the original proposal decision.
- Secret-like candidate text is rejected before writing a shadow candidate,
  proposal, or committed item. The journal records only hashes, risk flags, and
  redaction metadata for that path.
- Implemented tests live in `tests/test_kernel_v3_phase71_memory_pipeline.py`.
  The migration bridge from old semantic-intake records is still a later Phase7
  slice, not part of this iteration.

## Phase7.2: Context Injection And Chat Admin

Add durable memory as a separate context section, not by overloading existing
`memory_refs`, which currently means journal-derived episodic evidence.

Rules:

- recall is scoped by thread/user/project/workspace
- injection happens at new run/resume boundary only
- injected memory is preview/hash/provenance oriented
- sensitive memory is excluded unless explicitly allowed
- budget truncation must preserve provenance ids

Chat/CLI admin:

- `holo-v3 memory list`
- `holo-v3 memory propose`
- `holo-v3 memory approve`
- `holo-v3 memory reject`
- `holo-v3 memory delete`
- `holo-v3 memory export`
- chat commands such as `/memory list`, `/memory approve`, `/memory delete`

Tests:

- new run sees approved memory
- same run does not hot-inject newly committed memory
- resume refreshes snapshot
- deleted/expired memory is not injected
- summary questions still answer from journal, not durable memory, unless memory
  recall is explicitly relevant

Implementation note:

- `ContextPackCompiler` now accepts an optional `durable_memory_store`. When it
  is absent, existing context sections are unchanged. When present, the compiler
  adds a separate `durable_memory` section with compact summaries, ids,
  provenance refs, artifact refs, confidence, privacy class, and payload hashes.
- Durable memory recall is user-and-project scoped when the project profile has
  a real `project_id`, so approved same-user same-project memory can flow
  across threads without leaking across users. When no real project profile is
  available, recall falls back to user-and-thread scope to preserve the
  narrower pre-Phase7 behavior.
- The older `memory_refs` section remains journal-derived episodic evidence and
  is not overloaded with committed durable memory.
- `AgentRuntime` passes its optional `MemoryStore` into the context compiler, so
  a new run/resume sees a frozen snapshot of approved active memory.
- `ChatRuntime` supports `/memory list`, `/memory proposals`,
  `/memory approve <id>`, `/memory reject <id> [reason]`, and
  `/memory delete <id> [reason]`. Chat only routes admin commands; approval and
  deletion still go through host-side `MemoryPipeline` / `MemoryStore`, with
  delete decisions journaled as `memory_item_deleted` or
  `memory_item_delete_observed`.
- `holo-v3 memory propose/list/approve/reject/delete` provides a local CLI admin
  surface. Delete uses the same pipeline journaling path as chat. Ordinary CLI
  agent/chat commands do not create durable-memory files unless a memory store
  is explicitly configured.
- Implemented tests live in
  `tests/test_kernel_v3_phase72_memory_context_admin.py`.

## Phase7.3: Resident Runtime Shell

Defer until the memory core and context injection are stable.

Add:

- `kernel_v3/resident/contracts.py`
- `kernel_v3/resident/queue.py`
- `kernel_v3/resident/runtime.py`
- optional `kernel_v3/resident/scheduler.py`

Rules:

- single local worker by default
- SQLite queue and lease for crash recovery
- worker calls `ChatRuntime`; it does not become a second decision layer
- pending user input stops autonomous continuation
- no live WeChat/Slack/Discord integration inside `kernel_v3`
- scheduler remains local and bounded

Tests:

- enqueue message, worker produces outbox
- worker lease prevents duplicate ownership
- restart resumes pending inbox item safely
- needs_user_input creates pending outbox, not self-answer
- bounded worker loop stops on idle, blocked lease, or max iteration guard
- transient worker failures retry with backoff and eventually enter dead letter
- outbox items can be acknowledged by admin/transport glue without adding a live
  transport decision layer
- resident enqueue, claim, outbox, completion, ack, and loop summaries are
  journaled and renderable through resident trace
- queue health/status reports inbox/outbox counts, claimable work, stale
  running items, due retries, active lease, dead letters, and ready outbox
- no live network or model required for default tests

Implementation note:

- `kernel_v3.resident` now provides `ResidentQueue`, `ResidentRuntime`, and
  typed `InboundMessage` / `OutboxMessage` / `WorkerLease` /
  `ResidentRunResult` contracts.
- The queue is local SQLite with inbox, outbox, and lease tables. A worker must
  acquire the single resident lease before claiming a pending message. Lease
  acquisition and inbox claiming run inside SQLite `BEGIN IMMEDIATE`
  transactions so competing workers cannot both claim the same item.
- `ResidentRuntime.run_once()` claims one inbox item, calls `ChatRuntime`, writes
  exactly one outbox item, marks the inbox item completed, and releases the
  lease. It does not loop forever and does not become a separate decision layer.
- Running inbox items are owned by the claiming worker. `complete` and `fail`
  calls can be guarded by worker id, so an old worker cannot complete a message
  after its lease expired and another worker reclaimed the item. The runtime
  renews its lease before writing outbox to avoid stale external responses.
- `ResidentRuntime.run_loop()` is bounded by `max_iterations` and stops on idle
  or blocked lease. This gives a safe resident worker loop without introducing
  an unbounded always-on loop into the kernel.
- Runtime exceptions move inbox items to `retry_wait` until `max_attempts` is
  reached, then to `dead_letter`. Retry scheduling is local queue metadata, not
  a scheduler or external transport.
- Dead-lettered, failed, or retry-waiting inbox items can be restored through a
  host/admin `requeue` action. Requeue sets the item back to `pending`, clears
  leases and retry timers, records requeue metadata, and is journaled by the
  CLI. Completed and currently running messages are not requeueable.
- Outbox writes are idempotent by inbound `in_reply_to`. If a worker crashes
  after writing the outbox but before completing the inbox item, a later retry
  reuses the existing outbox item instead of creating a duplicate outbound
  response.
- Outbox status updates are constrained by a small host-owned lifecycle instead
  of arbitrary string overwrites. `ready`/`failed` delivery records can be
  acknowledged; `pending_user_input` acknowledgements become
  `pending_user_input_delivered` so the prompt is not resent but the system
  still knows it is waiting for a user answer. Invalid transitions are rejected
  and reported by CLI.
- Inbound enqueue is idempotent by `message_id`. A transport/gateway retry of
  the same thread/source/text returns the existing inbox item instead of
  creating a duplicate task. Reusing a `message_id` with different thread,
  source, or text is rejected as a conflict.
- `needs_user_input` becomes an outbox item with status `pending_user_input`;
  the worker does not fabricate the missing user answer or continue the task.
- When a later inbound message in the same thread answers a pending question
  and `ChatRuntime` resumes via `answer_pending_question`, prior
  `pending_user_input` or `pending_user_input_delivered` outbox items for that
  thread are marked `answered` with the answering inbound `message_id` in
  payload metadata. This keeps queue status from permanently advertising a
  question that has already been answered, while preserving the original
  outbox audit record.
- `holo-v3 resident enqueue/run-once/run/status/inbox/outbox/requeue/ack` provides
  the local dev/admin surface. `resident enqueue --message-id` can replay a
  gateway delivery id to test idempotency. This is not a live transport
  integration.
- `holo-v3 resident inspect` converts queue counts into an actionable health
  report with issue codes, sample message/outbox ids, and recommended host/admin
  actions. This gives a long-running resident worker an operator-facing doctor
  view without adding transport-level autonomy.
- `holo-v3 resident-trace` renders resident journal records, keeping the SQLite
  queue state auditable through the normal kernel trace path.
- Implemented tests live in `tests/test_kernel_v3_phase73_resident_runtime.py`.

## Phase7.4: Migration, Export, And Trace Hardening

Add the close-out pieces that make durable memory auditable across old and new
runs:

- `kernel_v3/memory/migration.py` migrates existing `semantic_intake` records
  containing `durable_memory:write` into shadow candidates and pending
  proposals.
- Migration is idempotent by journaling `memory_migration` records with the
  source semantic-intake record ref.
- `MemoryStore.export_item()` returns the committed item, linked proposals,
  tombstone if present, and matching append-only audit records.
- `TraceRenderer.render_memory_trace()` and `holo-v3 memory-trace <task_id>`
  expose memory proposal, approval, migration, rejection, and deletion events in
  task trace output.
- `holo-v3 memory migrate-semantic` and `holo-v3 memory export <memory_id>` are
  the CLI surfaces for migration and audit export.
- Implemented tests live in `tests/test_kernel_v3_phase74_memory_migration_trace.py`.

## Phase7.6: Bounded Resident Scheduler

Add the smallest scheduler surface needed for long-running resident operation:

- `kernel_v3/resident/scheduler.py`
- `ResidentSchedule`
- `ResidentScheduleTickResult`
- `ResidentScheduleStatus`
- `ResidentScheduleInspection`
- CLI commands:
  - `holo-v3 resident schedule-add`
  - `holo-v3 resident schedule-list`
  - `holo-v3 resident schedule-tick`
  - `holo-v3 resident schedule-disable`

Rules:

- scheduler stores local schedule metadata in the resident SQLite database
- scheduler only enqueues due messages into `ResidentQueue`
- scheduler does not execute tools, call models, synthesize answers, or route
  chat turns
- worker execution still flows through `ResidentRuntime -> ChatRuntime ->
  AgentRuntime`
- resident workers only tick schedules when constructed with a scheduler or
  started through CLI with `--tick-schedules`
- schedule-enabled loop results include `schedule_status`; if no inbox work is
  claimable but a future active schedule remains, the loop reports
  `waiting_for_schedule` instead of a misleading completed idle state
- every schedule add, due enqueue, disable, and tick is journaled
- enqueue is idempotent by deterministic scheduled message id
- repeated schedules require a positive interval and bounded `max_runs` unless
  the operator explicitly requests an unbounded recurring local schedule with
  `schedule-add --unbounded`
- resident status and inspect surfaces report schedule health without merging
  scheduler state into queue ownership or agent decision logic

Implementation note:

- `ResidentScheduler.tick()` scans active due schedules, enqueues each due item
  as a normal inbox message with schedule metadata, advances or completes the
  schedule, and journals both per-schedule enqueue and tick summary records.
- A crash after enqueue but before schedule advancement is safe to retry because
  the scheduled message id is deterministic. `ResidentQueue.enqueue()` returns
  the existing inbox message on identical replay instead of duplicating work.
- `ResidentRuntime` can optionally tick schedules before claiming inbox work.
  Scheduled work is indistinguishable from other inbox work once it has been
  enqueued.
- `ResidentScheduler.status()` and `ResidentScheduler.inspect()` report active,
  due, recurring, and unbounded schedule counts plus recommended operator
  actions such as running the resident loop with `--tick-schedules`.
- `ResidentLoopResult.schedule_status` is empty when no scheduler is attached
  and populated only for schedule-enabled resident workers.
- Implemented tests live in
  `tests/test_kernel_v3_phase76_resident_scheduler.py`.

## Acceptance Gate

Before moving beyond Phase7 memory core:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_kernel_v3*.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q kernel_v3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_public_release_hygiene.py -q -p no:cacheprovider
git diff --check
```

Default tests must remain offline: no live model, no network, no external
transport, and no API key dependency.
