# Stage112 System Taxonomy Design

## Context

Stage111 introduced category-based simulation, but the first category set still
contained deployment-specific wording. Stage112 generalizes the categories into
system behavior classes that can be copied across interfaces and deployments.

## Design

Stage112 owns a role-agnostic fixture set. Each fixture has:

- `category_id`;
- label;
- role-neutral query;
- domain tags;
- expected packet route;
- synthetic mind packet;
- `system_level=true`;
- `role_agnostic_template=true`.

The fixtures are passed through the Stage111 simulator, so every category still
runs the Stage105-110 chain.

## Coverage

The suite covers memory, affect, reasoning, tool grounding, inhibition, timing,
perception, metacognition, action, control, uncertainty, planning, value, and
error correction.

The four routes remain:

- `multi_packet`;
- `single_packet`;
- `tool_first`;
- `stop`.

## Tool Probe

Stage112 adds a deterministic tool-call probe. It constructs a Stage106 provider
tool payload with `external_lookup`, `memory_recall`, and a forbidden
`shell_exec`. The first two are exposed and accepted when returned by the
provider. The forbidden tool is rejected. The accepted tool calls are fed into
Stage107, which must enter `awaiting_tool_execution` with
`next_action=execute_tool_locally`.

## Tests

Tests verify:

- at least 30 role-agnostic system categories;
- no role marker leakage in category surfaces;
- broad family and route coverage;
- successful tool-call probe;
- unknown tool rejection;
- CLI dry-run output.
