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
- semantic intake: detects unavailable `durable_memory:write` capability

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

1. derive `ShadowCandidate` from explicit user memory intent or semantic intake
2. validate privacy, scope, and evidence refs
3. dedupe by `kind + scope + dedupe_key`
4. detect conflicts instead of overwriting silently
5. create `MemoryProposal`
6. require approval unless policy marks it safe for host auto-commit
7. commit `MemoryItem` only through host pipeline

Agent integration:

- semantic intake can continue to identify `durable_memory:write`
- model cannot call a memory commit tool directly
- finalization may create proposals, not committed memory
- ask-user can request approval for pending proposals

Tests:

- explicit "remember this" creates proposal, not committed memory
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
  skeleton keeps the old no-durable-memory behavior. With it, explicit
  `durable_memory:write` semantic intake produces a pending proposal while the
  task still asks the user for clarification/approval.
- `MemoryStore.decide_proposal()` records approval/rejection decisions in the
  append-only memory log and replays them on reload. Candidate/proposal writes
  are tolerant of duplicate stable ids so resume and resident retries can stay
  idempotent.
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
- no live network or model required for default tests

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
