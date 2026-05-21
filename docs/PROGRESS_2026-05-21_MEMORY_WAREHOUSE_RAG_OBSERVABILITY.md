# Memory Warehouse and RAG Observability Progress

Date: 2026-05-21

## Trigger

The operator requested an explicit view of Holo's memory warehouse:

- what is inside each memory layer
- when memory starts
- whether poor recall comes from missing memory, extraction, retrieval, or model-packet composition

## Implemented

Added a first-class CLI report:

```text
python3 -m holo_host memory-warehouse
```

Default mode is redacted. Raw local excerpts require WSL and exact confirmation:

```text
python3 -m holo_host memory-warehouse \
  --repo-root /home/holo/holo \
  --include-raw \
  --confirm SHOW_HOLO_MEMORY_FROM_WSL \
  --sample-limit 24 \
  --max-chars 700 \
  --query "回忆任何事情？" \
  --thread-key holo_cli:main \
  --chat-name HoloCLI \
  --channel holo_cli \
  --output-dir /mnt/d/Holo/holo/.holo_runtime/memory-warehouse-current
```

The command writes:

- `holo_memory_warehouse.json`
- `holo_memory_warehouse.html`

The raw report is written under `.holo_runtime/` and is not committed.

## Current Live Evidence

Current live WSL report path:

```text
D:\Holo\holo\.holo_runtime\memory-warehouse-current\holo_memory_warehouse.html
```

Warehouse range:

- first timestamp: `2026-04-02T00:00:00Z`
- latest timestamp: `2026-05-21T15:42:59Z`

Store counts:

- `memory_store.jsonl`: 21 rows, `2026-04-02T00:00:00Z` to `2026-04-07T13:40:17Z`
- `working_store.jsonl`: 48 rows, `2026-05-21T08:45:33Z` to `2026-05-21T15:29:06Z`
- `candidate_store.jsonl`: 9 rows, `2026-04-03T03:47:29Z` to `2026-04-11T06:57:24Z`
- `conversation_archive.jsonl`: 750 rows, `2026-04-03T10:00:01Z` to `2026-05-21T15:29:06Z`
- `thought_stream.jsonl`: 256 rows, `2026-04-08T08:58:04Z` to `2026-05-21T15:42:59Z`
- `emotion_trace.jsonl`: 24 rows, `2026-04-07T02:15:37Z` to `2026-05-21T15:29:06Z`
- `callback_candidates.jsonl`: 64 rows, `2026-04-08T14:50:08Z` to `2026-05-21T14:48:23Z`
- `initiative_candidates.jsonl`: 96 rows, `2026-04-06T19:21:38Z` to `2026-04-07T13:01:00Z`

RAG trace for `回忆任何事情？`:

- `inspect_mind.tier`: `deep_recall`
- `inspect_mind.selected_memory_count`: 18
- `trace_hybrid.tier`: `deep_recall`
- `trace_hybrid.memory_route`: `hybrid`
- `trace_hybrid.recall_confidence`: 1.0

Memory doctor health:

- substrate integrity: `ok`
- semantic consolidation: `critical`, durable semantic memory is 44 days behind archive
- episodic/semantic balance: `warn`, archive-to-durable ratio is 35.71
- thread continuity: `warn`, one identity-fragmentation candidate
- vector index: `ok`

## Diagnosis

The live warehouse is not empty. The main failure is that current experience is not being consolidated into durable semantic memory:

1. Episodic archive and thought stream are current.
2. Working memory is current.
3. Vector and graph retrieval are present.
4. Durable semantic memory is stale and small.
5. RAG therefore reconstructs from archive/thought/vector hits instead of stable semantic self-memory.

This makes Holo look foolish under broad recall prompts: it can retrieve recent similar recall-test turns, but its durable semantic store does not yet represent the current Stage100+ project history and operator intent.

## Next Cut

The next fix should be consolidation, not more visualization:

1. Add a promotion/replay job that turns recent archive and working-store evidence into candidate semantic memories.
2. Add freshness gates so `memory_store.jsonl` cannot lag archive by weeks.
3. Add prompt-packet tests that assert current stage, operator intent, and recent project direction appear in the mind packet for broad recall queries.
4. Keep raw warehouse viewing WSL-only and outside committed artifacts.
