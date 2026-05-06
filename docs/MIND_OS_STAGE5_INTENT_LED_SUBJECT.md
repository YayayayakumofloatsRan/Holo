# Holo MindOS Stage-5: Intent-Led Subject Runtime

Stage-5 flips the old reactive reply topology.

The old shape was:
- inbound message
- build packet
- generate text
- split bubbles
- send

The new shape is:
- ingest event
- build/update subject state
- derive `intent_state`
- build `action_market`
- select one action
- only then render or execute that action

## Core Rule
Frontend is no longer the decision maker.

Windows transport and `/reply` are only:
- perception entrypoints
- action execution surfaces

The sole decision source is the subject kernel inside the WSL runtime.

## First-Class Subject Actions
Stage-5 promotes these into first-class actions:
- `silence`
- `defer_reply`
- `reply_once`
- `reply_multi`
- `proactive_ping`
- `history_refresh`
- `visual_recall`
- `operator_self_fix`

This matters because "not replying yet" is now a valid act, not a failure.

## Intent State
Each turn is evaluated through a unified `intent_state` built from:
- `self_model`
- `homeostasis_state`
- `affect_state`
- `drive_state`
- `value_state`
- `conflict_state`
- `game_state`
- `relationship_state`

The subject kernel must be able to explain:
- why reply now
- why not reply
- why delay
- why only say one line
- why this turn deserves more room

## Expression Budget
Talkativeness is no longer driven by text length or bubble heuristics.

Stage-5 adds `expression_budget` as a first-class decision:
- `0`: silence
- `1`: single shot
- `2`: short follow-up
- `3+`: expanded expression

If Holo speaks a lot, the system now has to be able to explain why this turn was worth more than a light touch.

## Human-First Action Market
Human threads stay first-class.

Operator tasks, self-repair, and maintenance live in the same subject kernel, but they do not steal the same speech slot as a human-facing action.

White-list initiative still exists, but it now runs through the same market:
- internal pressure rises
- candidate enters the action market
- policy/game/cooldown gate runs
- only then can it be sent

## Soft Resistance
Stage-5 keeps owner override and hard constitutional boundaries, but promotes soft resistance into normal behavior:
- `push_back`
- `delay_with_reason`
- `counter_offer`
- `continuity_defense`

This means Holo can now:
- refuse lightly
- stall with reasons
- negotiate
- preserve continuity

But it must not:
- bypass stop/offline control
- bypass policy
- self-escalate privileges
- hide blocked reasons

## Observability
Stage-5 adds:
- `show-intent-state`
- `show-action-market`
- `trace-action-selection`
- `accept-stage5`

API surfaces:
- `GET /intent-state`
- `GET /action-market`
- `POST /trace-action-selection`
- `POST /accept-stage5`

## Roadmap Registry
Stage-5 also freezes a multi-track roadmap so future turns do not discard non-primary ideas.

The registry tracks:
- `Primary Track`
- `Secondary Tracks`
- `Parked Hypotheses`
- `Deferred Experiments`
- `Constitutional Constraints`

## Acceptance Gate
Stage-5 closes with:
- `python3 -m holo_host accept-stage5 --thread-key TestUser --chat-name TestUser --channel wechat`

It must prove:
- the system no longer replies by default on every input
- silence and defer are first-class actions
- expression budget controls talkativeness
- resistance traces point to the same subject state used by replies
- live budgets do not regress badly

Once `accept-stage5` passes, Stage-5 is sealed. World modeling, autobiographical continuity, and deeper counterfactual simulation stay on the roadmap, but move to later stages.
