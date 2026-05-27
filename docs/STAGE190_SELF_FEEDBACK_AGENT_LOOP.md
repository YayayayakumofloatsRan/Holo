# Stage190 Self-Feedback Agent Loop

Stage190 adds a public, auditable self-feedback loop for agent actions.

The goal is to move Holo away from isolated tool calls and toward a control loop:

```text
goal -> action -> observation -> appraisal -> next_action_or_stop -> final
```

This is the engineering equivalent of a thought/action loop. It does not expose hidden chain-of-thought or provider private reasoning. It exposes the public control state needed to debug and improve agent behavior.

## Schema

```text
holo.stage190.self_feedback_loop.v1
holo.stage190.feedback_step.v1
```

## First Integration

Stage190 is first integrated into Stage186 live crawler search. Each query/open/evaluate pass now produces a feedback step with:

```text
goal
action
query
observation_status
evidence_score
authority_status
authority_required_family
authority_score
combined_sufficiency_score
marginal_utility
unresolved_items
remaining_query_budget
next_action
stop_decision
stop_reason
public_summary
```

The crawler report now includes:

```text
stage190_self_feedback_loop
```

## CLI Trace

Stage153 renders feedback events as:

```text
[feedback] web_search score=... delta=... next=... stop=... authority=...
```

This shows why the loop continued or stopped without exposing raw hidden reasoning.

## Architectural Notes

Stage190 follows the same split used by mature agent tooling:

```text
model or policy proposes
host executes
ledger records
feedback controller appraises
stop controller closes or continues
```

The first target is search/crawling because evidence sufficiency, source authority, and marginal utility are easiest to audit there. The same schema can be reused for engineering tools, market-research packs, report generation, and later domain modules.

## Boundaries

Stage190 does not add provider calls, memory writes, WeChat startup, transport changes, unbounded loops, or hidden reasoning exposure.
