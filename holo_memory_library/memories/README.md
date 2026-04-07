# Structured Memory Stores

The memory lifecycle is split across three JSONL files:
- `working_store.jsonl`: raw observations and temporary notes
- `candidate_store.jsonl`: synthesized memories awaiting review
- `memory_store.jsonl`: durable long-term memories eligible for prompt retrieval
- `emotion_trace.jsonl`: recent turn-level emotional stances used for short-range carry-over
- `conversation_archive.jsonl`: full user/reply turn pairs kept as archival memory for replay, inspection, and cross-host revival
- `callback_candidates.jsonl`: replay-produced callback leads for existing threads, kept outside the normal prompt path

Each line is one JSON object with this shape:
- id: unique memory id
- status: working | candidate | durable
- kind: style | habit | boundary | preference | self_model | social_model | procedural | episodic | summary | drift_signal
- text: memory text
- tags: short labels
- source: where this memory came from
- importance: 0.0 to 1.0
- confidence: 0.0 to 1.0
- derived_from: upstream observation ids
- supersedes: prior ids folded into this row
- conflicts_with: canonical or memory ids this row collides with
- created_at: ISO-8601 timestamp
- last_seen_at: ISO-8601 timestamp

Promotion rules:
- `working` memory is never used by `prompt`
- `candidate` memory must be reviewed before promotion
- `drift_signal` stays out of durable prompt memory
- `self_model` promotion requires repeated evidence or explicit user correction
- `habit` promotion requires repeated evidence or explicit user correction
- `working` memory accumulates in v1 until it is explicitly pruned or archived
- `state --json` includes a `rewrite_state` block that `reply-loop` uses for mode-sensitive repair bias
- `reply-loop` can also apply facet-specific brightening, such as making flat food or drink lines more sensory when the current stance is `hungry_delight`
- `consolidate` may derive multiple candidate memories from one user statement when it contains durable detail worth separating
- `observe-turn` can record a user turn plus an optional assistant reply, and convert reply drift into candidate `drift_signal` memory
- `archive-turn` writes one explicit full turn into `conversation_archive.jsonl` without trying to reinterpret it as durable memory
- `backfill-archive` replays the runtime SQLite message ledger into the archive, pairing inbound and outbound turns where possible
- `dream-cycle` samples archived turns with weighted randomness, distills repeated detail back into candidate memory, and produces callback candidates
- `show-callbacks` lets you inspect those callback candidates without sending anything
- `sidecar-turn` is meant for black-box hosts: it prints a pasteable addendum for the upstream model, and if you provide the raw draft afterwards, it repairs the draft and distills the exchange into memory

Use the local CLI:
- python3 rag_memory.py add --kind preference --status durable --importance 0.9 --tags taste persona --text "..."
- python3 rag_memory.py consolidate --text "User asked to keep '咱' in the voice." --source user.feedback
- python3 rag_memory.py consolidate --text "我只是想找个陪伴的" --source user.feedback --dry-run
- python3 rag_memory.py observe-turn --user "我只是想找个陪伴的" --reply "当然可以，我会陪着你。" --dry-run
- python3 rag_memory.py archive-turn --user "我只是想找个陪伴的" --reply "咱会陪着你。"
- python3 rag_memory.py show-archive --limit 8
- python3 rag_memory.py backfill-archive --db-path .holo_runtime/holo_host.sqlite3
- python3 rag_memory.py dream-cycle --sample-size 6
- python3 rag_memory.py show-callbacks --limit 8
- python3 rag_memory.py sidecar-turn --user "我只是想找个陪伴的" --dry-run
- python3 rag_memory.py sidecar-turn --user "我只是想找个陪伴的" --draft "当然可以，我会陪着你。" --dry-run
- python3 rag_memory.py review-candidates
- python3 rag_memory.py promote candidate-0001
- python3 rag_memory.py reject candidate-0002
- python3 rag_memory.py query "user likes smart merchant banter"
- python3 rag_memory.py state --query "你是谁，怎么和我说话" --json
- python3 rag_memory.py preflight --query "你是谁，怎么和我说话" --draft "当然可以，我会这样回答你。"
- python3 rag_memory.py reply-loop --query "你是谁，怎么和我说话" --draft "当然可以，我会这样回答你。"
- python3 rag_memory.py prompt "user feels anxious and wants Holo-like reassurance"
- python3 rag_memory.py audit --query "你是谁，怎么和我说话"
- python3 rag_memory.py critic --query "你是谁，怎么和我说话" --draft "当然可以，我会这样回答你。"

The `state` command now exposes `rewrite_state`, which the reply loop uses to bias repairs by cadence, register, priorities, action bias, and whether a voice hook should be forced back in.
The same state now also exposes a bounded `random_state`, so Holo can vary opening hooks and replay sampling without randomizing core identity.
The archive file is not part of normal prompt assembly, but snapshots now carry it so another host can revive not only Holo's distilled memory, but also recent original dialogue.
With Codex CLI hooks enabled, the runtime bridge in `holo_memory_library/codex_hooks/` now uses `UserPromptSubmit` and `Stop` as a quiet archive lane: it caches the user turn, then archives the final reply once the turn is actually over, without pushing big visible context into the CLI.
The runtime bridge can carry a mode-sensitive emotional palette as well, so Holo stays recognizable without answering every turn in one fixed emotional register.
The runtime bridge can also append `emotion_trace` rows and auto-observe finalized turns, so nearby replies can keep a little emotional continuity.
