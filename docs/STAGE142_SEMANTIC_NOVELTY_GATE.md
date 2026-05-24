# Stage142 Semantic Novelty Gate

Date: 2026-05-24

## Purpose

Stage142 controls progressive visible bubbles:

```text
A'  = fast reaction / first visible response
A'' = optional continuation
```

The continuation is still provider-requested through Stage132. Stage142 does not force a deep packet, add a loop, call a provider, execute tools, write memory, or change transport authority. It only decides whether already-candidate visible bubbles should be emitted, trimmed, or suppressed before delivery and archive.

## Problem

Before this stage, Holo could produce two visible segments where the second segment repeated the first, contradicted it, or reintroduced a claim that Stage139, Stage140, or Stage141 had already marked unsafe. That made the progressive stream feel mechanical: A'' often sounded like a paraphrase rather than a real state update.

Stage142 makes A'' earn its place. It should appear only when it adds a useful semantic role, new evidence, task progress, contradiction repair, or an explicit limitation.

## API

`holo_host/stage142_semantic_novelty_gate.py` exposes:

```python
STAGE142_SCHEMA = "holo.stage142.semantic_novelty_gate.v1"

def evaluate_stage142_bubbles(...): ...

def apply_stage142_gate(...): ...
```

The report includes:

- `schema`
- `candidate_count`
- `emitted_count`
- `suppressed_count`
- `repaired_count`
- `evaluations`
- `status`

Each evaluation includes:

- `bubble_index`
- `purpose`
- `semantic_role`
- `novelty_score`
- `overlap_score`
- `contradiction_flags`
- `grounding_blocked`
- `should_emit`
- `suppression_reason`

The report is debug/metadata only. User-visible text does not expose Stage142 labels, scores, or internal field names.

## Semantic Roles

The deterministic role classifier recognizes:

- `ack`
- `answer`
- `clarification`
- `correction`
- `tool_feedback`
- `memory_grounding`
- `visual_grounding`
- `risk_notice`
- `reasoning_step`
- `commitment`
- `summary`
- `ask_next`
- `fallback_limitation`
- `unknown`

## Gate Rules

A'' is emitted when at least one of these is true:

- it has a useful semantic role different from A';
- `novelty_score >= 0.45`;
- it reports a real tool observation;
- it reports a memory grounding or memory alignment limitation;
- it explicitly repairs a contradiction;
- it contains concrete task progress;
- the stream plan indicates that detail was requested.

A'' is suppressed or repaired when:

- it has the same role as A' and low novelty;
- its first sentence repeats A';
- it is only a generic offer or helpfulness phrase;
- it contradicts A' without saying it is correcting the earlier statement;
- it reintroduces an ungrounded tool claim from Stage139;
- it reintroduces unsupported memory-source or memory-detail claims from Stage140 or Stage141.

Prefix duplicates are trimmed when new content remains. Pure duplicates are suppressed.

## Runtime Integration

`merge_stage132_reply_bubbles()` now builds candidate bubbles and runs Stage142. Existing callers still receive `list[ReplyBubble]`; callers that pass `return_metadata=True` also receive the Stage142 report.

`CodexCliProcessor` stores the report in:

```text
ReplyPlan.debug["stage142_semantic_novelty"]
```

`HoloReplyService` propagates compact metadata into:

- reply JSON;
- outgoing metadata;
- archive/observe metadata;
- Stage135 topology when a progressive candidate stream has more than one candidate.

Stage135 can now render a single `semantic_novelty_gate` node with compact metrics:

- `semantic_novelty_node_count`
- `semantic_novelty_status`
- `semantic_novelty_suppressed_count`

## Examples

Duplicate:

```text
A'  I can do that.
A'' I can do that.
Result: A'' suppressed.
```

Prefix duplicate with new content:

```text
A'  I checked the workspace.
A'' I checked the workspace. The tests now pass.
Result: A'' becomes "The tests now pass."
```

Valid tool feedback:

```text
A'  I will check first.
A'' I checked the workspace and saw docs plus holo_host.
Result: A'' emitted when tool grounding is present.
```

Unsupported memory claim:

```text
A'  Let me answer carefully.
A'' I remember you prefer fewer emoji.
Stage141: unsupported_memory_detail.
Result: A'' blocked.
```

Unrepaired contradiction:

```text
A'  I can read that file.
A'' I cannot read that file.
Result: A'' blocked unless it explicitly frames itself as a correction.
```

## Constraints Preserved

- No provider calls.
- No memory writes.
- No tool authority changes.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage132 remains provider-requested; Stage142 only gates already-candidate visible expression.
- Stage139, Stage140, and Stage141 grounding reports remain authoritative for unsupported claims.

## Next Stage

The next useful stage should build a packet-budget and stop-reason report over the same chain: why a packet was sent, skipped, continued, or stopped, including cache hints, token estimates, elapsed time, grounding results, and Stage142 novelty outcome.
