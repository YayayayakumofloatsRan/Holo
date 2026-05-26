# Stage150 Codex-Style Context Memory Fabric

Date: 2026-05-26

## Purpose

Stage150 upgrades Holo's prompt-facing state from chat-history context to a structured working-context packet inspired by Codex-style instruction hierarchy and background compaction.

The goal is practical: before a provider is asked to speak, Holo separates the current user goal, active task, reusable state slots, user directives, project/domain instructions, evidence ledgers, open loops, and compact background summary. This gives the language model a bounded working memory instead of a prompt dump.

## Schema

```text
holo.stage150.context_memory_fabric.v1
```

## Core Behavior

Stage150 builds `stage150_context_memory_fabric` from existing turn evidence:

- current user turn
- Stage148 reusable state and ReAct loop
- Stage149 user directive kernel
- recent dialogue exposed to the current turn
- sidecar and debug evidence already available in the processor path
- tool, memory, visual, grounding, packet, context, and reaction-kernel reports when present

The packet contains these separated sections:

- `user_goal`
- `active_task_state`
- `reusable_state_slots`
- `directive_state`
- `project_or_domain_instructions`
- `relevant_recent_events`
- `evidence_ledger_view`
- `tool_memory_visual_observations`
- `open_loops`
- `compact_background_summary`
- `forbidden_visible_claims`

## Instruction Scope

Stage150 resolves instruction layers deterministically:

```text
system_policy
persona_style_memory
project_instruction
domain_instruction
module_instruction
current_task_instruction
user_directive
```

More specific scopes override broader scopes for keyed instructions. Stage149 user directives outrank persona, style, and profile memory. For example, a no-emoji directive remains authoritative even if persona/style memory suggests playful emoji usage.

## Background Compact

Background compact is internal only. It is not visible speech and must not produce user-facing text such as "I compacted context."

The compact summary preserves:

- task state
- decision summary
- directive summary
- evidence summary
- open loops
- unresolved conflicts
- exact current user request

It filters session, browser, health-check, localhost, and environment noise.

## Evidence Discipline

Stage150 marks visible read, tool, test, and patch claims as unverified unless a matching observation ledger exists. It does not execute tools or create proof. It only prepares the context and records forbidden visible claims for downstream prompt discipline.

Provider-visible instruction:

```text
Do not claim read/test/patch/tool success unless a matching observation ledger exists.
```

## Runtime Integration

`reply_api.py` builds Stage150 before processor generation, after Stage148 and Stage149 are available. This packet is stored in the turn sidecar and rendered by `processors.render_chat_prompt()` under:

```text
Engineering Context State:
```

After final visible repair, Stage150 is rebuilt with grounding, novelty, packet, context-economy, and reaction-kernel metadata when available. The final report is propagated into:

- reply JSON
- outgoing metadata
- archive/observe metadata
- `ReplyPlan.debug`
- Stage135 topology through a `context_memory_fabric` node

## Boundaries

Stage150 does not:

- add provider calls
- execute tools
- write durable memory
- implement approval or sandbox policy
- start WeChat
- widen transport authority
- override Stage149 visible-output repair
- expose background compact as visible speech

## Why This Matters

The prior failure mode was that Holo could possess raw chat events but fail to package them as useful working context. Stage150 moves Holo toward a Codex-like state packet: explicit instruction hierarchy, current task, evidence discipline, and compact background state are separated before generation. This is the substrate needed for better memory recall, tool selection, and coherent agent behavior without adding a second brain.
