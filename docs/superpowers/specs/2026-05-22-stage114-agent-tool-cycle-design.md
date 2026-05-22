# Stage114 Agent Tool Cycle Design

## Context

Stage113 executes local tools, but the agent needs a loop that starts from
provider tool proposals and returns to provider packet dispatch.

## Design

Stage114 accepts:

- Stage105 packet plan;
- optional decoded provider response with `tool_calls`;
- optional local memory corpus;
- optional external lookup backend or live network flag.

It then:

1. Parses provider tool calls with Stage106.
2. Executes allowlisted calls with Stage113.
3. Builds a Stage107 loop with the resulting observations.
4. Extracts the next provider packet and its observation-bearing inputs.

If no provider response is supplied but Stage105 selected `tool_first`, Stage114
executes the Stage105 tool request directly.

## Tests

Tests verify:

- provider `tool_calls` are parsed, accepted/rejected, and executed;
- rejected tools remain skipped;
- Stage105 tool-first requests execute;
- Stage107 receives a `tool_observation`;
- the next provider packet contains `tool_observation_summary`;
- CLI can run a simulated provider tool cycle.

## Boundary

The CLI uses simulated provider `tool_calls` so it is deterministic. It is
designed to be replaced by a real decoded DeepSeek response without changing
the execution and reentry stages.
