# Stage149 User Directive Kernel

Date: 2026-05-26

## Purpose

Stage149 addresses a concrete runtime failure: user corrections such as "不要用 emoji" could be stored somewhere in dialogue or archive rows, but they were not reliably promoted into every provider packet as hard visible-output constraints. The result was low recall for user requirements and persona-like drift.

Stage149 treats stable user directives as reusable state, not ordinary chat transcript.

## Runtime Behavior

`holo_host/stage149_user_directives.py` builds a deterministic report:

```text
holo.stage149.user_directives.v1
```

The report is built from:

- current user turn
- recent dialogue history
- sidecar recent dialogue window
- graph trace summary if already present
- thread archive rows exposed by the existing memory/RAG interface

It currently recognizes:

- visible no-emoji directives
- no-roleplay / subject-runtime identity directives

The core identity line is always present:

```text
visible_identity_mode=subject_runtime_not_roleplay
```

This means Holo should speak as the local subject runtime and memory state, not as a fictional-character roleplay costume.

## Prompt Integration

`processors.render_chat_prompt()` renders Stage149 as:

```text
User Directive State:
visible_identity_mode=subject_runtime_not_roleplay
core_identity: speak as Holo's local subject runtime, not as a fictional-character roleplay.
hard_directive: no emoji or emoticons in visible speech.
hard_directive: do not roleplay; do not explain yourself as a character imitation.
```

This block appears before situational state, short-term working memory, reusable state memory, and reply constraints so it can constrain the packet rather than appear as passive background.

## Visible Repair

`reply_api.py` applies `apply_stage149_visible_directives()` after the processor result and again after tool/memory grounding repairs and bubble finalization.

This prevents downstream repairs or A'/A'' bubble assembly from reintroducing emoji or roleplay phrases.

## Metadata And Topology

Stage149 metadata is propagated into:

- final reply JSON
- outgoing metadata
- archive/observe metadata
- `ReplyPlan.debug`

Stage135 topology exposes a compact `user_directive_kernel` node and metrics:

- `user_directive_node_count`
- `user_directive_count`
- `user_directive_status`

## Authority Boundaries

Stage149 is deterministic and local.

It does not:

- add provider calls
- write memory
- execute tools
- start WeChat
- change transport authority
- add a second brain loop
- mutate private persona files

## Core Setting Location

Tracked public defaults live in:

```text
holo_host/policies.py
```

Prompt assembly lives in:

```text
holo_host/processors.py
```

Private local subject-profile files may exist under:

```text
holo_memory_library/subject_seed.md
holo_memory_library/voice_profile.md
```

Those files are deployment-local profile inputs, not public repo truth. Stage149 intentionally gives user directives and subject-runtime identity higher priority than persona or roleplay-like style hints.
