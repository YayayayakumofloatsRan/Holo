# Stage121 Theory-Guided Conscious Packet Scheduler

Date: 2026-05-22

## Purpose

Stage121 starts converting Holo's theory-guided packet work into a live packet
scheduler for continuous thought flow.

The core adjustment is:

- do not send small fixed packets by habit;
- do not blindly fill the context with irrelevant text;
- dynamically build the longest useful packet that preserves cacheable prefix
  stability and leaves room for tool observations and final expression.

## Provider Cache Constraint

DeepSeek's API exposes context caching through usage counters such as
`prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`. Cache hits require
repeated prompt prefixes. Therefore Holo's packet structure should keep stable
content first and volatile content last.

Stage121 defines the ordering contract:

1. stable system and identity contract first;
2. stable tool schema working set second;
3. selected memory and attractor summaries third;
4. volatile user turn and tool observations in `dynamic_tail_last`.

This makes long packets compatible with prefix caching instead of fighting it.

## Dynamic Packet Policy

The scheduler computes:

- observed prompt token estimate;
- target input token budget;
- expansion budget;
- output budget;
- stream mode;
- max tool rounds and tool calls;
- stable prefix target;
- cache hit/miss counters when the provider returns them.

The policy uses these signals:

- prompt size;
- tool working-set size;
- uncertainty;
- selected action type;
- research/architecture/memory/cache/topic hints.

Stream modes:

- `compact_reply_packet`: small ordinary reply;
- `single_reflective_packet`: one larger reflective provider packet;
- `continuous_thought`: longer packet with deliberation, tool observation
  reentry, and expression phases.

## Live Integration

`CodexCliProcessor.generate` now attaches `stage121_packet_policy` to provider
metadata and applies:

- `max_output_tokens = policy.output_budget_tokens`
- `max_provider_tool_rounds = policy.tool_loop.max_rounds`
- `max_provider_tool_calls = policy.tool_loop.max_tool_calls`

Stage120 still chooses the bounded tool working set. Stage121 decides how much
room the turn deserves and how long the thought/tool loop may continue.

## CLI

Inspect a policy without calling a provider:

```text
python -m holo_host stage121-packet-policy \
  --query "构建理论指导下的连续意识流，尽可能长包并考虑缓存" \
  --prompt-repeat 80 \
  --uncertainty 0.8 \
  --tool memory_recall \
  --tool test_runner
```

## Authority Boundaries

- Stage121 does not execute tools.
- Stage121 does not start or touch WeChat/watchers.
- Stage113 remains the local execution authority.
- Stage120 remains the provider-visible tool working-set gate.
- Stage121 changes packet scheduling metadata and budgets only.

