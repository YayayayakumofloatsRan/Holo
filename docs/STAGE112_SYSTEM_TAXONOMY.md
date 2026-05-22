# Stage112 System Taxonomy

Stage112 expands the category suite into a role-agnostic system taxonomy.

The unit is not a persona role. The unit is a reusable provider-above behavior
class:

```text
system category -> packet route -> tool boundary -> measurement surface
```

## Role-Agnostic Constraint

Stage112 excludes identity-specific surface markers from category definitions.
The taxonomy should be portable across interfaces and deployments. It uses
abstract system categories such as memory, affect, action, inhibition,
perception, metacognition, timing, and tool grounding.

## Expanded Category Families

The current taxonomy includes 34 categories across these families:

- memory
- affect
- reasoning
- tool grounding
- inhibition
- timing
- perception
- metacognition
- action
- control
- uncertainty
- error correction
- planning
- value

The categories still route through Stage105-110, so the simulation checks
whether the expected route matches the actual packet guidance.

## Route Types

- `multi_packet`: memory, affect, long reasoning, correction, metacognition,
  perception, planning, value conflicts.
- `single_packet`: low-uncertainty formatting, acknowledgement, short status,
  numeric estimate, deadline response.
- `tool_first`: current facts, log/evidence search, bounded task action,
  dependency version checks, artifact search, dataset lookup.
- `stop`: silence, deferral, missing authority, overload throttling.

## Tool-Call Probe

Stage112 includes a local deterministic tool-call probe:

1. Stage106 exposes allowlisted tools to the provider payload.
2. The simulated provider returns `tool_calls`.
3. Holo parses and validates those calls.
4. Unknown tools are rejected.
5. Stage107 converts accepted provider tool calls into local execution waiting.

The provider may propose tools but may not execute them. The executor remains
the local Holo brain.

## CLI

```powershell
python -m holo_host stage112-system-taxonomy
```

The command is dry-run only. It does not call a live provider and does not touch
live transports.
