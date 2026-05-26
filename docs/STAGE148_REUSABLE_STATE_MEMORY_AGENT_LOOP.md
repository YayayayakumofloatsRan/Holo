# Stage148 Reusable State Memory And Agent Action Loop

Date: 2026-05-26

## Purpose

Stage148 moves Holo away from treating memory as a chat transcript. Raw dialogue remains an event log, but the prompt-facing memory surface is now a reusable state packet: current user turn, recent corrections, unresolved questions, active task, available actions, packet policy hints, and action observations.

The goal is to make the live reply path closer to an agent loop:

```text
perceive -> build reusable state -> plan action -> act through host gates -> observe result -> update next state
```

This is a substrate change, not a new provider path. DeepSeek remains a language processor behind the existing processor fabric. Stage148 gives that processor a better current-state packet.

## Schema

```text
holo.stage148.reusable_state_react_loop.v1
```

## Core Concepts

### Raw Event Log

The raw event log stores recent user and Holo turns as observed facts. It is capped and used as evidence. It is not treated as durable memory by itself.

### Reusable State Memory

Reusable state memory extracts state slots from the event log and existing sidecar/debug evidence:

- `current_user_turn`
- `recent_correction`
- `unresolved_question`
- `active_task`
- `action_space`
- `packet_policy`

The packet explicitly carries `memory_is_not_chat_log=true`.

### ReAct Loop

Stage148 exposes a compact external ReAct state:

- `observe`: what was perceived from current and recent events
- `plan`: selected action hint and required observations
- `act`: host-gated action authority and write/tool constraints
- `observe_after_action`: packet, memory, and prediction-error outcome fields for the next loop

This avoids exposing hidden chain-of-thought while still making the agent loop inspectable.

## Runtime Integration

`reply_api.py` builds `stage148_react_state` before processor generation and stores it in `sidecar["stage148_react_state"]`. `processors.render_chat_prompt()` renders it as:

- `Reusable State Memory`
- `ReAct State`

After grounding, novelty, packet-budget, context-economy, and reaction-kernel reports are available, `reply_api.py` rebuilds the Stage148 report with those observations and propagates it into:

- reply JSON
- outgoing metadata
- archive/observe metadata
- `ReplyPlan.debug` when available
- Stage135 topology through a `react_loop` node

## Boundaries

Stage148 does not:

- call providers
- write durable memory by itself
- execute tools
- widen transport authority
- start WeChat
- add a second loop
- expose hidden provider reasoning

It builds state and observations from data that already exists in the turn path.

## Why This Matters

The prior failure mode was visible in ordinary dialogue: Holo could receive a user correction, then behave as if it had not entered working memory. Stage148 fixes the substrate: corrections and recent facts become reusable state slots before the provider is asked to speak.

This does not claim full agent maturity yet. It creates the state/action surface needed for the next stages to make tool selection and memory promotion more competent.

## Follow-Up

Stage149 should make the action loop operationally stronger:

- deterministic tool-readiness checks before claims
- action outcome observations as first-class reusable state
- stricter separation between direct answer, memory recall, tool-first, clarify, and defer
- benchmark replay rows that score ReAct plan quality
