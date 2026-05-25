# Stage144 Context Economy And Packet Policy Calibration

Date: 2026-05-24

## Purpose

Stage144 uses Stage143 packet-budget reports, Stage142 visible-bubble novelty, and Stage139-141 grounding results to diagnose whether Holo spent context well in the current turn.

This stage is shadow-only. It reports a bounded working set, sufficiency and waste scores, and a packet-policy recommendation. It does not enforce the recommendation, send a packet, skip a packet, call a provider, execute tools, write memory, change transport behavior, or start WeChat.

## Problem

Stage143 made the packet chain observable: why fast and deep packets were sent or skipped, why continuation stopped, and what estimated cost was visible. That still leaves a calibration question:

```text
Did the turn include the right context, and did the deep packet earn its cost?
```

Stage144 answers this in diagnostic mode. It treats context as a bounded working memory instead of a prompt dump. Evidence is represented as slots with priority, freshness, confidence, token estimate, include reason, and eviction reason.

## Schema

```text
holo.stage144.context_economy.v1
```

The report contains:

- `schema`
- `working_set_slots`
- `context_sufficiency_score`
- `context_waste_score`
- `packet_policy_recommendation`
- `recommended_deep_policy`: `keep`, `skip`, `defer`, `tool_first`, or `memory_first`
- `confidence`
- `reason`
- `shadow_only=true`

Each working-set slot contains:

- `slot_id`
- `slot_type`
- `summary`
- `priority`
- `freshness`
- `confidence`
- `token_estimate`
- `include_reason`
- `eviction_reason`

Slot types:

- `current_user_constraint`
- `active_task`
- `unresolved_question`
- `recent_correction`
- `memory_anchor`
- `tool_observation`
- `visual_observation`
- `risk_permission`
- `packet_budget`
- `novelty_gate`

## Inputs

`holo_host/stage144_context_economy.py` builds the report from already available runtime evidence:

- current user text
- selected action
- active thread state
- recent correction markers
- tool observation ledger
- memory observation ledger
- memory grounding
- memory alignment
- tool grounding
- Stage142 semantic novelty
- Stage143 packet budget
- visual memory when present
- risk and permission metadata

It does not read private memory files directly.

## Recommendation Logic

Stage144 is intentionally bounded and deterministic:

- If Stage139 reports an ungrounded tool claim, recommend `tool_first`.
- If Stage141 reports unsupported or contradicted memory detail, recommend `memory_first`.
- If a deep packet ran and Stage142 suppressed A'' as duplicate, recommend `skip` or `defer`.
- If Stage142 blocked or repaired continuation, recommend `defer`.
- If uncertainty is high and no deep packet ran, recommend `defer`.
- If a deep packet produced useful non-suppressed continuation, recommend `keep`.

These are shadow recommendations only. Runtime authority remains with the existing Stage132 packet decision and Stage142 visible-expression gate.

## Scores

`context_sufficiency_score` rises when the turn has current-user grounding, actual tool observations, memory anchors, aligned memory claims, and a passed novelty gate. It falls when tool or memory grounding fails.

`context_waste_score` rises when the turn includes expensive or numerous context surfaces that do not produce useful claims, packets, or visible continuation. It is especially high when a deep packet ran and Stage142 suppressed A'' as duplicate.

The scores are diagnostic heuristics, not billing authority or routing authority.

## Runtime Integration

`CodexCliProcessor` stores the report in:

```text
ReplyPlan.debug["stage144_context_economy"]
```

`HoloReplyService` rebuilds the report after final Stage139/140/141/142/143 metadata is available, then propagates it into:

- reply JSON
- outgoing metadata
- archive/observe metadata
- Stage135 topology when a topology is built

Stage135 can render a compact `context_economy_gate` node with:

- `context_economy_node_count`
- `context_economy_recommended_deep_policy`
- `context_economy_waste_score`
- `context_economy_sufficiency_score`
- `context_economy_shadow_only`

## Constraints Preserved

- No provider calls.
- No memory writes.
- No tool execution.
- No tool authority changes.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage132 continuation behavior is unchanged.
- Stage142 visible-expression gating remains unchanged.
- Stage139, Stage140, and Stage141 grounding remain authoritative.
- Stage144 is diagnostic and shadow-only by default.

## Next Stage

Stage145 should convert accumulated Stage144 diagnostics into a replayable packet-policy calibration harness before any live enforcement. The first target should be comparing `keep`, `skip`, `defer`, `tool_first`, and `memory_first` recommendations against transcript outcomes without changing live packet behavior.
