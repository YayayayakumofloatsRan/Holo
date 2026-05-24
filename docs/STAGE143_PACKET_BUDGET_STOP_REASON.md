# Stage143 Packet Budget And Stop-Reason Report

Date: 2026-05-24

## Purpose

Stage143 makes the packet chain observable:

```text
why a packet was sent
why a packet was skipped
why continuation happened
why continuation stopped
what it cost
what grounding or novelty result affected the stop
```

This is an observability layer only. It does not add a loop, force a deep packet, call a provider, execute tools, write memory, change transport behavior, or start WeChat.

## Problem

Stage132 models one user input as a fast first packet plus an optional continuation. Stage142 gates the visible A' and A'' bubbles. Before Stage143, the system could show whether the final text was gated, but it did not expose the packet-level reason chain: why the fast packet ran, why the deep packet ran or was skipped, which cache hint was used, how many tokens were estimated, and whether Stage142 changed the visible stop condition.

For Holo's biomimetic stream work, that packet chain is the practical substrate of the "thought flow." Stage143 records the substrate without changing it.

## Schema

```text
holo.stage143.packet_budget.v1
```

The report contains:

- `schema`
- `packet_count`
- `sent_count`
- `skipped_count`
- `continued_count`
- `stop_reason`
- `total_estimated_tokens`
- `total_elapsed_ms`
- `packets`

Each packet contains:

- `packet_id`
- `packet_type`: `fast`, `deep`, `tool_followup`, `memory_followup`, `repair`, or `skipped`
- `lane`
- `budget_tag`
- `sent`
- `send_reason`
- `skip_reason`
- `cache_hint`
- `estimated_tokens`
- `elapsed_ms`
- `tool_need`
- `memory_need`
- `uncertainty`
- `grounding_status`
- `memory_alignment_status`
- `stage142_status`
- `stop_reason`

## Runtime Integration

`holo_host/stage143_packet_budget.py` builds the report from existing debug metadata:

- Stage132 stream plan
- Stage132 fast context frame
- Stage124 fast/deep thought-loop metadata
- Stage121 packet policy when present
- Stage142 semantic novelty report
- Stage139 tool grounding report
- Stage140 memory grounding report
- Stage141 memory alignment report
- processor timing and usage metadata

`CodexCliProcessor` stores the report in:

```text
ReplyPlan.debug["stage143_packet_budget"]
```

`HoloReplyService` refreshes the report after Stage139/140/141/142 finalization, then propagates it into:

- reply JSON
- outgoing metadata
- archive/observe metadata
- Stage135 topology when a topology needs to be built

Stage135 can render a compact `packet_budget_gate` node with:

- `packet_budget_node_count`
- `packet_budget_packet_count`
- `packet_budget_stop_reason`

## Stop Reasons

Fast-only:

```text
provider_fast_packet_said_fast_answer_enough
```

Fast plus deep:

```text
deep_packet_completed
```

Stage142 suppression or block:

```text
stage142:<status>
```

Examples include:

```text
stage142:suppressed_duplicate
stage142:blocked_ungrounded_claim
stage142:repaired_contradiction
```

## Token And Timing Estimates

Stage143 uses provider usage when available. If usage is missing, it estimates tokens from bounded context character counts or prompt excerpts. Timing uses processor timing and Stage124 fast-packet timing when present.

The estimates are diagnostic, not billing authority.

## Constraints Preserved

- No provider calls.
- No memory writes.
- No tool execution.
- No tool authority changes.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage132 still decides continuation from the fast provider packet.
- Stage142 still decides visible A' to A'' novelty.
- Stage143 reports; it does not make new decisions.

## Next Stage

Stage144 should use Stage143 reports as measurement input for packet policy calibration: compare packet cost, Stage142 suppression, grounding failures, and visible usefulness without widening runtime authority.
