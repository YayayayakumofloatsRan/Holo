# Stage156 Context Compiler And Cache Discipline

Date: 2026-05-27

## Purpose

Stage156 introduces a deterministic context compiler surface for Holo Core. It turns the Stage150 working-context packet into explicit prompt sections:

```text
stable_prefix
project_instruction_block
tool_schema_block
directive_block
dynamic_turn_block
observation_block
final_constraints_block
```

The compiler is local and deterministic. It does not call providers, execute tools, write memory, start WeChat, or widen transport authority.

## Schema

```text
holo.stage156.context_compiler.v1
```

## Core Behavior

The compiler preserves:

- the exact current user request
- hard user directives
- active project state
- latest tool, memory, visual, and engineering observations
- open loops and next actions

It filters common session noise such as local health-check URLs, CLI banners, health checks, session/environment prefixes, and repeated generic text. Background compact output is internal metadata only and must not appear as visible user-facing speech.

## Runtime Integration

Stage156 now runs as a real packet compiler, not only an importable availability surface:

- `reply_api.py` compiles `stage156_context_compiler` before provider generation from the Stage150 working-context packet.
- `processors.py` renders a `Context Compiler State` block into the provider prompt alongside `Engineering Context State`.
- `CodexCliProcessor` includes Stage156 lines in the fast-packet context frame and updates cache counters from provider usage metadata after generation.
- `reply_api.py` recompiles the final report after grounding and project-state updates so reply JSON, outgoing metadata, archive metadata, and `ReplyPlan.debug` share the same report.
- `stage135_i_state_topology.py` exposes a `stage156_context_compiler` node with token, cache, and truncation counters.
- CLI chat supports `/context`, `/compact`, and `/cache`; these commands show metadata only.

The compiler repairs visible text that tries to say "I compacted context" into ordinary working-context wording before delivery/archive. Compact remains an internal maintenance artifact.

## Cache Discipline

The compiler records:

```text
estimated_prompt_tokens
stable_prefix_tokens
dynamic_suffix_tokens
truncated_sections
cache_hit_tokens
cache_miss_tokens
cache_hit_ratio
stable_prefix_cache_key
dynamic_suffix_digest
```

Stable-prefix content is separated from dynamic observations so provider cache behavior can be inspected instead of guessed.

Low-priority dynamic sections are truncated before directives and the exact current user request. The directive block is protected because Stage149 hard directives must survive compaction and budget pressure.

## Boundary

Stage156 is a context compiler, not a policy engine. It prepares context and budget metadata. It does not decide whether another packet should run and does not apply live policy changes.

Stage156 does not add provider calls, execute tools, write memory, start WeChat, widen transport authority, expose hidden reasoning, or implement approval/sandbox policy.
