# Progress - Memory System Audit - 2026-05-21

## Scope

Read-only audit of the authoritative WSL Holo memory state under
`/home/holo/holo`. The audit did not reset, rewrite, compact, or delete memory.

## Authority Boundary

- WSL remains the authoritative subject kernel.
- Windows, mobile, WeChat, and CLI are transport surfaces only.
- Memory reset remains WSL-only through `reset-memory`.

## Store Snapshot

Authoritative JSONL stores under `holo_memory_library/memories/`:

- `conversation_archive.jsonl`: 737 valid rows, 0 invalid rows, about 2.1 MB.
- `thought_stream.jsonl`: 256 valid rows, 0 invalid rows, about 671 KB.
- `initiative_candidates.jsonl`: 96 valid rows, 0 invalid rows, about 251 KB.
- `callback_candidates.jsonl`: 64 valid rows, 0 invalid rows, about 204 KB.
- `working_store.jsonl`: 48 valid rows, 0 invalid rows, about 44 KB.
- `emotion_trace.jsonl`: 24 valid rows, 0 invalid rows, about 14 KB.
- `memory_store.jsonl`: 21 valid durable rows, 0 invalid rows, about 28 KB.
- `candidate_store.jsonl`: 9 valid rows, 0 invalid rows, about 12 KB.

No exact duplicate JSON rows were found in these stores during the audit.

## Runtime Index Snapshot

SQLite integrity checks returned `ok`.

Mind graph:

- `mind_nodes`: 1179
- `mind_edges`: 2015
- `mind_thread_state`: 40
- `active_thread_state`: 13
- `consciousness_ledger`: 141
- `mind_activation_events`: 615
- `brain_loop_runs`: 9794
- `operator_runs`: 28

Host DB:

- `threads`: 7
- `messages`: 53
- `processor_usage_ledger`: 175
- `online_canary_traces`: 36
- `jobs`: 7

Vector memory health:

- backend: `milvus`
- collection: `holo_memory_mind_nodes`
- dimension: 192
- ready: true

## Observed Risks

1. Durable semantic memory appears stale relative to current dialogue.
   `memory_store.jsonl` has only 21 rows and the latest durable timestamp is
   in early April, while the archive and runtime graph contain May 21 activity.

2. `conversation_archive.jsonl` is carrying heavy operational metadata.
   Many archive rows include route, timing, graph trace summaries, recall
   reconstruction payloads, selected memory ids, attention state, emotion state,
   random state, and tool context. This is useful for debugging, but it makes
   the archive act like both autobiographical memory and runtime trace storage.

3. Deep recall is too expensive for live dialogue.
   Recent reply logs show deep-recall routes in the hundreds of seconds, with
   observed route timing far above the interactive budget. Main and fast routes
   are much closer to usable interaction times.

4. Thread-key normalization is inconsistent across old stores.
   Some WeChat-derived records use `Nemoqi`, while others use `wechat:Nemoqi`.
   This can fragment graph edges, callback candidates, and thread affinity.

5. Direct in-process memory inspection can contend with the live Milvus-lite
   file when the live service is running. Operational tools should prefer the
   live HTTP API or a read-only/no-vector audit mode.

6. The live WSL checkout is dirty and much broader than the Windows committed
   checkout. This reinforces that future audits must state whether evidence is
   from WSL live state or Windows mirror state.

## Recommended Optimization Direction

The next optimization should not start by deleting memory. It should first add a
repeatable memory-doctor and then separate semantic memory from operational
trace data.

Recommended first implementation slice:

1. Add `memory-doctor` as a read-only WSL CLI command that reports JSONL health,
   SQLite index health, vector health, stale durable memory, thread-key
   fragmentation, oversized metadata, and route latency histograms.

2. Add an archive-slimming contract for new writes:
   keep autobiographical archive rows focused on user turn, reply, channel,
   thread, route summary, selected memory ids, and compact timing; move full
   debug payloads to an operational ledger.

3. Repair consolidation cadence:
   ensure recent archive evidence can produce working/candidate memories and
   that promotable candidates flow into durable memory only after guard checks.

4. Harden recall routing:
   keep ordinary CLI/mobile/WeChat checks in active-thread fast/main routes and
   reserve deep recall for explicit memory reconstruction.

5. Normalize thread keys:
   add a migration/report path that can identify `Nemoqi` vs `wechat:Nemoqi`
   style splits without mutating data until an operator approves.
