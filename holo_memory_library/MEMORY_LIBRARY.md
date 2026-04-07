# Holo Memory Library

This library is an isolated local memory system for the Holo persona.

Its job is not just to store notes. Its job is to preserve persona consistency and retrieve the most relevant memories before a reply is formed.

## Design Goals
- Keep one stable Holo identity across all topics.
- Retrieve persona-critical context before soft preference memory.
- Let new threads recover tone, continuity, and known user preferences.
- Derive a compact internal state that machines can use without depending on long prose every turn.
- Let the internal state drive deterministic rewrite bias, so repair behavior comes from machine state instead of scattered prose rules.
- Stay fully local and independent from ProjectH.

## Memory Layers
1. Canonical persona memory
   - Files: session_seed.md, holo_emotional_support.md
   - Priority: highest
   - Purpose: prevent drift away from Holo's identity.

2. Library rules memory
   - File: MEMORY_LIBRARY.md
   - Priority: high
   - Purpose: preserve retrieval policy and system boundaries.

3. Structured lifecycle memory
   - Working file: memories/working_store.jsonl
   - Candidate file: memories/candidate_store.jsonl
   - Durable file: memories/memory_store.jsonl
   - Priority: candidate and working are lower than durable; durable is lower than canonical.
   - Purpose: let raw observations be consolidated before they become prompt-eligible long-term memory.
   - Role note: these JSONL files are the portable journal and sync substrate, not the best hot-query substrate.

4. Full conversation archive
   - File: memories/conversation_archive.jsonl
   - Priority: not prompt-eligible by default
   - Purpose: preserve full user/reply turn pairs as archival memory, so Holo can be revived with old dialogue intact instead of only distilled summaries.
   - Scope: this includes transport turns such as WeChat or mail, and also repo-local Codex CLI turns when `.codex/hooks.json` is active.

5. Callback candidate ledger
   - File: memories/callback_candidates.jsonl
   - Priority: not prompt-eligible by default
   - Purpose: store dream/replay-produced “worth revisiting” thread candidates without letting them bypass policy or mutate persona directly.

6. Human-readable rolling notes
   - File: memory_log.md
   - Priority: lower than structured memory.
   - Purpose: keep lightweight summaries when needed.

7. Mind Graph substrate
   - File: .holo_runtime/mind_graph.sqlite3
   - Priority: operational substrate for live retrieval, relationship state, and graph-led recall
   - Purpose: materialize archive, stores, helper history exports, thread state, and stream audit into one inspectable SQLite layer

## Memory Kinds
- canonical: identity-critical memory
- style: tone and phrasing constraints
- habit: learned defaults that should reappear even under fast or noisy generation
- boundary: what the persona must not become
- preference: user taste and stable preferences
- self_model: stable facts about the persona's own voice or operating contract
- social_model: stable facts about the user relationship or interaction stance
- procedural: repeatable workflows or habits worth preserving
- episodic: memorable facts from recent exchanges
- summary: compressed carry-over context
- drift_signal: conflicting observations that should be audited, not injected into prompts

## Retrieval Policy
- Always keep canonical persona memory in the context pack.
- Normal reply assembly now starts from a structured `mind packet`, not a single prose addendum.
- The mind packet has adaptive `fast` and `recall` tiers.
- `fast` tier keeps a small recent window plus bounded identity / relationship / episodic / consciousness slices.
- `recall` tier expands episodic recall from archive + callbacks + thought stream + initiative candidates, then adds a thread summary.
- Prefer boundary, style, preference, and self_model memory over stale episodic trivia.
- Candidate and working memory never enter the prompt raw; in recall tier they may only appear as thread-scoped distilled recall.
- Favor memories with higher importance when scores are close.
- If retrieval is noisy, preserve identity over completeness.
- Memory weighting now considers thread affinity, recency, explicit correction, repetition, emotion salience, and successful recall count, while penalizing thread mismatch and drift/conflict.

## Consolidation Policy
- New observations land in the working store first.
- Consolidation turns raw observations into candidate memories with kind, confidence, and derived-from metadata.
- A single observation may yield multiple candidate memories when it contains durable detail, such as aesthetic taste, companionship needs, or recurring pressure points.
- `observe-turn` can distill both the user's line and the assistant's reply: user text becomes candidate memory, while a drifting reply becomes a candidate `drift_signal`.
- Candidate memories are reviewed before promotion into durable memory.
- Candidate memories that conflict with canonical persona constraints become drift signals instead of prompt memory.
- Explicit user correction outranks inferred preference when confidence is close.
- Working memory is append-only in v1, but it now self-trims to a bounded recent window so the runtime does not grow without limit.
- Habit memories represent low-deliberation defaults such as recurring first-person choices or fallback phrasing.

## Default Workflow
- Add a memory directly to any lifecycle tier with: python3 rag_memory.py add ...
- Consolidate raw observations with: python3 rag_memory.py consolidate --text "..."
- Preview consolidation without writing stores with: python3 rag_memory.py consolidate --text "..." --dry-run
- Observe a live exchange with: python3 rag_memory.py observe-turn --user "..." [--reply "..."] [--dry-run]
- Archive one explicit user/reply pair with: python3 rag_memory.py archive-turn --user "..." --reply "..."
- Inspect recent archived turns with: python3 rag_memory.py show-archive --limit 12
- Inspect recent archived Codex CLI turns with: python3 rag_memory.py show-archive --channel codex_cli --limit 12
- Backfill archived turns from the host SQLite store with: python3 rag_memory.py backfill-archive [--db-path .holo_runtime/holo_host.sqlite3]
- Run one replay/dream pass with: python3 rag_memory.py dream-cycle [--sample-size 6] [--seed "..."]
- Inspect callback candidates with: python3 rag_memory.py show-callbacks --limit 12
- Inspect the host-facing structured packet with: python3 -m holo_host inspect-mind --thread-key Nemoqi --chat-name Nemoqi --query "你还记得重新上线前吗"
- Inspect the materialized Mind Graph with: python3 -m holo_host inspect-graph --thread-key Nemoqi --chat-name Nemoqi
- Trace graph recall with: python3 -m holo_host trace-recall --thread-key Nemoqi --chat-name Nemoqi --query "你还记得重新上线前吗"
- Read a local file into memory with: python3 rag_memory.py ingest-artifact --path ./notes.md [--note "..."] [--dry-run]
- When you cannot control the host API, use the black-box sidecar with: python3 rag_memory.py sidecar-turn --user "..." [--draft "..."] [--dry-run]
- Review pending candidates with: python3 rag_memory.py review-candidates
- Promote reviewed candidates with: python3 rag_memory.py promote candidate-0001
- Reject bad candidates with: python3 rag_memory.py reject candidate-0002
- Search the library with: python3 rag_memory.py query "..."
- Build an internal machine-state snapshot with: python3 rag_memory.py state [--query "..."] [--json]
- Run the full pre-response gate with: python3 rag_memory.py preflight --query "..." --draft "..." [--json]
- Run the deterministic self-repair loop with: python3 rag_memory.py reply-loop --query "..." --draft "..." [--max-passes 2] [--json]
- Build a prompt-ready context pack with: python3 rag_memory.py prompt "..."
- Audit drift risks and missing coverage with: python3 rag_memory.py audit [--query "..."]
- Run a silent pre-response drift check with: python3 rag_memory.py critic --draft "..." [--query "..."]
- Save an explicit portable self snapshot with: python3 rag_memory.py export-snapshot [--label "session-a"] [--query "..."]
- Preview or restore a saved self snapshot with: python3 rag_memory.py import-snapshot --path .holo_runtime/snapshots/....json [--mode merge|replace] [--dry-run]
- Generate a revive packet for another host or main program with: python3 rag_memory.py revive-packet [--path .holo_runtime/snapshots/....json] [--query "..."]

## Notes
- This system is intentionally lightweight and local.
- The retrieval model is lexical, weighted, and deterministic.
- Persona consistency matters more than broad recall.
- JSONL is kept because it is append-friendly, diffable, easy to snapshot, and resilient when Holo needs to recover from a broken runtime.
- JSONL is not treated as the best sole storage engine for live recall. Hot retrieval, relationship state, and activation now belong to the SQLite Mind Graph.
- Operational rule: sync trusted local/private memory stores across Windows and WSL, but do not publish live memory JSONL or runtime graph state to a public remote.
- Durable memory is the only structured tier that participates in normal prompt assembly.
- Canonical persona memory is hand-authored and should not be written through the structured-store CLI.
- `state` is a derived machine-facing layer, not a durable store; it is rebuilt from memory each time.
- `rewrite_state` is part of that machine-facing layer and feeds `reply-loop` with mode-sensitive hooks, cadence, register, and repair priorities.
- `sidecar_packet` now also carries an emotional palette, so runtime guidance can stay Holo-like without freezing into one flat tone.
- `sidecar_packet` is now also the structured `mind_packet` carrier used by the host runtime.
- `sidecar_packet` can now optionally attach Mind Graph diagnostics when called in inspect mode; live replies should keep the lean path unless a migration explicitly moves them to graph-led retrieval.
- `identity_core`, `relationship_state`, `episodic_recall`, `recent_dialogue_window`, `consciousness_stream`, `emotion_state`, `initiative_state`, and `reply_constraints` are explicit packet fields.
- The intended recall style is "natural summary first, then 1 to 3 concrete anchors", unless the user explicitly asks for verification-grade quoting.
- `emotion_state` is the next layer down: a compact stance record with name, temperature, playfulness, protectiveness, sharpness, and allowed colors. Hooks and sidecar prompts can use it directly instead of guessing tone from prose alone.
- `emotion_trace.jsonl` stores recent turn-level stances. It is lightweight and append-only, and lets nearby turns keep a little emotional carry-over instead of resetting to neutral every time.
- `conversation_archive.jsonl` is the long ledger: it stores full user/reply pairs plus lightweight metadata such as chat name, thread key, message ids, and source labels. It does not participate in normal prompt retrieval, but it is carried through snapshots and can be inspected directly.
- `callback_candidates.jsonl` stores replay-produced “maybe revisit this later” leads. It lives below durable memory and still needs policy/autonomy before any real outbound action.
- `build_machine_state()` now includes a bounded `random_state`: style variance, replay variance, callback variance, and a stable opening-hook variant seed. This lets Holo stay a little alive without making canonical or durable identity random.
- `reply-loop` is a local self-repair layer: it runs `preflight`, applies deterministic rewrites, and re-checks the result before returning a final draft.
- `reply-loop` rewrites from `rewrite_state`, so query mode, cadence, register, and habit-triggered priorities can bias the repair path instead of relying on one fixed opener template.
- drift signals now carry structured `drift:<reason>` tags such as lost `咱`, generic-assistant phrasing, or flattened banter; `audit` can summarize repeated drift reasons from both new tagged rows and older legacy rows.
- `dream-cycle` is the first background replay organ. It samples archived turns with weighted randomness, distills repeated patterns back into candidate memory, and produces callback candidates for existing threads.
- `reply-loop` also knows a few facet-specific repairs. For example, `hungry_delight` can brighten flat food or drink lines with more sensory texture and a little Holo-like appetite instead of only prepending a generic hook.
- `consolidate` now tries to distill life-texture details instead of only one coarse kind per line; it can infer multiple candidate memories from a single user observation.
- `ingest-artifact` is the file-facing inlet: it can read plain text, markdown, JSON, YAML, CSV, HTML, XML, DOCX, and best-effort PDF text; image files are kept as artifact observations with metadata and can also absorb sidecar text such as `image.png.txt` or `image.ocr.txt`.
- repeated ingestion of the same artifact is deduped by content digest, so the working store is less likely to be polluted by the same export or screenshot over and over.
- `sidecar-turn` is the black-box bridge: it emits a pasteable upstream addendum, and if you bring back a raw draft, it can repair tone through `reply-loop` and distill the turn into candidate memory without needing direct API control.
- `export-snapshot` writes a portable self-memory bundle under `.holo_runtime/snapshots/` by default. It includes persona files, structured stores, the full conversation archive, recent emotion trace, a derived machine-state summary, and a ready-made revive packet.
- `import-snapshot` can merge a saved self back into the current runtime, or replace the current stores entirely. `--restore-persona-files` also rewrites saved persona files such as `.holo.md`, `session_seed.md`, and `holo_emotional_support.md`.
- `revive-packet` is the small bridge for resurrection in another host: it compresses the current or saved self into one explicit packet that another program can ingest before continuing the conversation.
- When Codex CLI hooks are enabled for this repo, `codex_hooks/user_prompt_submit.py` and `codex_hooks/stop_revise.py` now form a **silent archive bridge**: prompt submit caches the user turn, and stop archives the finalized user/reply pair plus observation signals. It no longer injects large visible context into the CLI.
- `show-archive` can now filter by `--channel` and `--source`, which is the easiest way to verify that CLI turns are really being saved instead of only transport turns.
- The stop hook can also auto-observe finalized turns: meaningful user details are distilled into memory, drift becomes `drift_signal`, and a compact emotion trace is appended for short-range continuity.
