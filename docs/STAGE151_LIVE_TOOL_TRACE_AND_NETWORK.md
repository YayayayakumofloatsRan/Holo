# Stage151 Live Tool Trace And Network Grounding

Date: 2026-05-26

## Purpose

Stage151 makes Holo's network use verifiable in the same turn that produced the visible answer. The immediate target is `external_lookup`: if the runtime searches, the search must leave a normalized observation row; if network is disabled, the attempted lookup is rejected and recorded without fetching.

This closes a practical grounding gap: capability pre-processing could provide web snippets to the prompt, while Stage139 only saw provider tool-loop observations. Stage151 carries capability-layer network evidence into the same `tool_observation_ledger` used by visible-claim grounding.

## Schemas

```text
holo.stage151.live_tool_trace.v1
holo.stage151.network_grounding.v1
```

## Runtime Behavior

- `external_lookup` respects `config.runtime.network_enabled`.
- When network is disabled, Holo records a rejected `external_lookup` observation with `error=network_disabled` and does not fetch.
- When network is enabled, Holo records query, status, compact results, source URLs, errors, and `fetched_at`.
- Reply grounding merges capability-layer lookup observations with provider tool-loop observations.
- Visible replies that claim a current web lookup are repaired unless a successful `external_lookup` ledger row exists.
- CLI chat can show a compact trace with `plan`, `tool_call`, `tool_observation`, `grounding`, and `final`.

## CLI

```bash
python3 -m holo_host chat --trace
```

Inside interactive chat:

```text
/trace on
/trace off
```

The trace is intentionally operational. It does not expose hidden chain-of-thought or provider-internal reasoning.

## Boundaries

Stage151 does not add provider calls, approval or sandbox logic, memory writes, tool authority, transport authority, or WeChat startup. It only records and checks the network/tool evidence already flowing through the existing capability and processor paths.
