# Memory Fabric Stage-1

## Goal

Stage-1 turns Holo memory into a four-layer fabric:

- `JSONL ledger`: append-only journal, snapshot, sync, recovery
- `SQLite Mind Graph`: thread state, relationship state, graph recall, stream audit
- `Milvus vector layer`: optional local high-dimensional semantic recall in WSL
- `Runtime activation state`: hot nodes, motifs, recall priors, stream contributors

The invariant for this stage is:

- memory is the self
- processor is replaceable compute
- transport is eyes and hands

## Live write path

Every real turn now aims to flow through:

1. append to archive / JSONL memory stores
2. sync thread materialization into SQLite Mind Graph
3. upsert thread-scoped vector documents into the vector backend
4. update activation state and recall priors

`JSONL` is no longer treated as the hot retrieval substrate.

## Retrieval path

`mind_packet` is now V4 and exposes:

- `graph_hits`
- `vector_hits`
- `activation_state`
- `retrieval_trace`
- `memory_route`
- `recall_confidence`

Reply routing now supports three diagnostic views:

- `legacy`: old JSONL-first sidecar
- `graph`: graph-led packet without vector expansion
- `hybrid`: graph + vector + activation packet

## Vector backend

The configured backend is `milvus`.

- default URI: `.holo_runtime/milvus/memory_fabric.db`
- expected runtime: local WSL deployment
- current code path is optional-safe: if `pymilvus` is missing, Holo keeps running and falls back to graph-led recall

This stage does not publish live vector data to the public code repo.

## Activation state

Activation state is stored in SQLite tables inside the same runtime database family and mirrored in memory cache.

It tracks:

- hot node ids
- motifs
- recall priors
- contributor counts
- recent activation events

The four background streams remain bounded:

- `maintenance_stream`
- `association_stream`
- `social_stream`
- `deep_dream_cycle`

They may influence:

- graph weight / affinity
- recall ordering
- activation motifs
- initiative seeds

They may not directly rewrite:

- canonical persona
- durable identity rules
- policy gates

## Diagnostics

New CLI commands:

- `python -m holo_host --config /home/holo/holo/.holo_host.toml backfill-vector-memory`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml inspect-mind --thread-key TestUser --chat-name TestUser --channel wechat --query "你还记得重新上线前吗"`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml trace-hybrid-recall --thread-key TestUser --chat-name TestUser --channel wechat --query "你还记得重新上线前吗"`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml show-activation-state --thread-key TestUser --chat-name TestUser --channel wechat`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml vector-health`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml reply-probe --thread-key TestUser --chat-name TestUser --channel wechat --query "你还记得重新上线前吗" --mode hybrid`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml stream-tick --stream-name association_stream`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml sync-private-memory --label stage1`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml benchmark-memory-fabric --thread-key TestUser --chat-name TestUser --channel wechat --query "你还记得重新上线前吗" --iterations 5 --warmup 1 --probe mind`
- `python -m holo_host --config /home/holo/holo/.holo_host.toml accept-memory-fabric-stage1 --thread-key TestUser --chat-name TestUser --channel wechat`

When the reply API is already online, these diagnostics now prefer the live HTTP service first instead of starting a second local process. That avoids reopening the local Milvus file from another process and keeps the WSL live kernel as the single authority.

New read-only HTTP endpoints:

- `GET /inspect-mind`
- `GET /trace-hybrid-recall`
- `GET /activation-state`
- `GET /vector-health`
- `GET /reply-probe`

New write-through HTTP endpoints for the same live kernel:

- `POST /backfill-vector-memory`
- `POST /stream-tick`
- `POST /sync-private-memory`
- `POST /reply-probe`

## Private sync boundary

Live memory and runtime state must not be pushed to the public code repo.

Private sync bundles may include:

- memory snapshots
- archive bundles
- graph export snapshots
- stream audit bundles
- vector health / metadata exports

Private sync bundles must not include:

- live SQLite runtime files
- live Milvus data directories
- Windows helper live config
- transient runtime temp artifacts

## Acceptance for Stage-1

Stage-1 is considered done when all of these hold:

- every real turn completes ledger -> graph -> vector -> activation within one logical chain
- explicit recall returns a natural summary plus 1 to 3 anchors
- origin queries prefer the earliest substantive thread events
- hybrid recall remains thread-scoped and does not drift to other contacts
- stream influence is observable through activation state, recall ordering, and thread-state motif / unfinished-thread updates
- WSL remains the only authoritative live kernel
- public repo remains code-only and does not absorb live memory

The fixed closure gate is:

- `python -m holo_host --config /home/holo/holo/.holo_host.toml accept-memory-fabric-stage1 --thread-key TestUser --chat-name TestUser --channel wechat`

That command now exercises the live Stage-1 stack end-to-end:

- checks `/health`, vector readiness, and WSL authority
- runs explicit recall and origin recall probes
- validates recall reconstruction quality
- ticks bounded streams and verifies influence writeback
- benchmarks `fast / recall / deep_recall` mind-packet latency
- reports private-sync as either pass or explicit external blocker
