# Stage141 Memory Claim Alignment

Date: 2026-05-24

## Purpose

Stage141 checks source sufficiency for visible memory claims. Stage140 already answers whether a memory claim has a usable source. Stage141 adds the next gate: whether the selected memory source actually supports the concrete detail stated in the visible answer.

The target failure mode is a reply such as "I remember you prefer fewer emoji" when the selected memory source only says "discussed git diff and tests." That source exists, but it does not support the specific preference claim.

## What Landed

`holo_host/memory_alignment.py` defines `holo.memory_alignment.v1` and implements four deterministic APIs:

- `extract_memory_claims(text)`
- `build_memory_evidence_texts(memory_observation_ledger, sidecar=None, reply_debug=None)`
- `evaluate_memory_alignment(text, memory_observation_ledger, sidecar=None, reply_debug=None)`
- `repair_memory_alignment(text, alignment_report, channel="")`

The gate is local and read-only. It does not call a provider, read private memory files directly, write memory, start transports, or widen tool authority.

## Evidence Sources

Stage141 only consumes evidence already present in turn metadata:

- `memory_observation_ledger[*].summary`
- `memory_observation_ledger[*].selected_ids`
- `sidecar.graph_trace_summary`
- `sidecar.recall_reconstruction.summary`
- `sidecar.recall_reconstruction.anchors`
- `sidecar.vector_hits[*].text`
- `sidecar.recent_dialogue_window.lines`
- `sidecar.thread_recall_lines`
- `reply_debug.recall_reconstruction.summary`
- memory tool observation summaries already present in debug metadata

A source row with only selected ids and no usable summary text can prove that a source exists, but it cannot fully align a detailed semantic claim by itself.

## Alignment Logic

The scorer extracts deterministic English and Chinese claim wrappers, then classifies claims into:

- `preference`
- `prior_statement`
- `previous_conversation`
- `event`
- `date_or_time`
- `project_or_topic`
- `identity_or_profile`
- `relationship_or_style`
- `generic_recall`

It computes a bounded score from:

- key-term overlap;
- source confidence;
- source-family strength;
- phrase match bonus;
- missing critical term penalties;
- contradiction penalties.

Durable, archive, mind-graph, and vector sources are strong. Working memory and current context are weak. `none` and missing sources cannot align detailed recall. Current context alone cannot fully ground an old-memory claim.

Contradiction flags dominate. A contradicted Stage140 ledger row or direct preference/time conflict produces `contradicted_memory_detail`.

## Runtime Integration

`HoloReplyService` now runs gates in this order:

1. normalize tool observations;
2. run Stage139 tool grounding;
3. normalize `memory_observation_ledger`;
4. run Stage140 memory grounding;
5. run Stage141 memory alignment on the Stage140 candidate text;
6. repair unsupported, weak, or contradicted memory details before bubble finalization;
7. archive and return metadata.

Stage141 does not override Stage140 missing-source repairs. If Stage140 already says the memory source is unavailable, that visible limitation remains.

Reply JSON, outgoing metadata, and archive/observe metadata now include:

- `memory_alignment`
- `memory_alignment_status`
- `memory_alignment_claim_count`
- `memory_alignment_unsupported_count`
- `memory_alignment_contradicted_count`

## Stage135 Topology

Stage135 can now render:

- `memory_alignment_gate`
- optional `claim_*` nodes;
- edges from `memory_observation_*` nodes into the gate;
- an edge from `memory_alignment_gate` back to `memory_delta`.

Metrics include:

- `memory_alignment_node_count`
- `memory_alignment_claim_count`
- `memory_alignment_unsupported_count`
- `memory_alignment_status`

This keeps the graph minimal: Stage141 is a source-sufficiency gate, not a multi-turn CT replay.

## Examples

Aligned:

```text
Claim: I remember you prefer fewer emoji.
Evidence: user preference: fewer emoji.
Result: aligned.
```

Weak:

```text
Claim: I remember you told me yesterday that you prefer fewer emoji.
Evidence: user preference: fewer emoji, no time marker.
Result: weakly_aligned or unsupported, not fully aligned.
```

Unsupported:

```text
Claim: I remember you prefer fewer emoji.
Evidence: discussed git diff and tests.
Result: unsupported_memory_detail.
```

Contradicted:

```text
Claim: I remember you prefer more emoji.
Evidence: user preference: fewer emoji, or a contradicted ledger row.
Result: contradicted_memory_detail.
```

## Constraints Preserved

- Stage141 is deterministic and read-only.
- Stage141 does not write memory.
- Stage141 does not add provider calls.
- Stage141 does not widen tool or transport authority.
- Stage141 preserves Stage139 tool grounding and Stage140 memory grounding.
- Stage141 does not expose internal fields such as `alignment_score` in user-visible repair text.

## Next Stage

Stage142 should implement an A' to A'' semantic novelty and contradiction gate. It should consume Stage139 tool grounding, Stage140 memory grounding, and Stage141 memory alignment so unsupported claims cannot reappear in later visible bubbles, and continuation bubbles only emit when they add a real semantic role or state delta.
