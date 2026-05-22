# Stage111 Category Simulation Design

## Context

Stage110 can guide packet dispatch for one turn. The next problem is coverage:
Holo needs a category-level simulator so packet policies are tested across
memory, affect, tools, inhibition, timing, identity, correction, and reasoning.

## Design

Stage111 defines a base fixture list. Each fixture contains:

- category id and label;
- query;
- domain tags;
- expected route;
- synthetic mind packet;
- optional deadline.

Each fixture is passed through Stage105, Stage107, Stage108, Stage109, and
Stage110. The simulator records observed route, packet budget, packet count,
applied axioms, and whether the result matches expectation.

## Routes

- `multi_packet`: continuity, memory, affect, long reasoning, correction.
- `single_packet`: simple low-risk reply or punctual reply.
- `tool_first`: current facts, local logs, task execution.
- `stop`: silence and deferred reply.

## Self-Extension

The simulator emits combination candidates and a candidate schema for future
Holo-generated categories. A new category is not promoted just because it is
generated. It needs repeated route mismatch, repeated reply-quality failure,
new tool affordance, new affective pattern, memory retrieval failure cluster,
or explicit operator approval.

## Testing

Tests verify:

- core category coverage;
- every fixture runs the full Stage105-110 chain;
- expected route matching;
- combination candidates;
- self-extension schema;
- CLI dry-run output.

Stage105 also gets a regression test so `research` does not falsely trigger
the `search` lookup route.
