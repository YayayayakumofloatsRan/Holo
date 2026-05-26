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

It filters common session noise such as local health-check URLs, CLI banners, and repeated generic text. Background compact output is internal metadata only and must not appear as visible user-facing speech.

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
```

Stable-prefix content is separated from dynamic observations so provider cache behavior can be inspected instead of guessed.

## Boundary

Stage156 is a context compiler, not a policy engine. It prepares context and budget metadata. It does not decide whether another packet should run and does not apply live policy changes.
