# Stage111 Category Simulation

Stage111 makes packet-control testing category-based.

Stage110 decides how one turn should be packetized. Stage111 defines the
currently enumerable basic units and runs each unit through the Stage105-110
chain:

```text
category fixture -> Stage105 packet plan -> Stage107 loop -> Stage108 expression gate
-> Stage109 theory frame -> Stage110 packet guidance
```

## Base Categories

The initial suite covers these basic units:

- autobiographical recall
- semantic memory linking
- affective support
- simple social reply
- preference continuity
- current fact lookup
- local log debug
- task execution
- no-send boundary
- deferred reply boundary
- long-form reasoning
- conflict correction
- identity self-model
- punctual short reply

These are not final human categories. They are testable engineering units. Holo
can later propose new categories when repeated turns do not fit this suite.

## Route Coverage

Each category is expected to map to one provider route:

- `multi_packet`: continuity, memory, affect, long reasoning, correction.
- `single_packet`: low uncertainty or tight timing.
- `tool_first`: current facts, logs, local actions, external evidence.
- `stop`: silence, deferral, inhibition.

Stage111 records whether observed Stage110 guidance matches the expected route.

## Combination Candidates

Stage111 emits first-order category combinations:

- affective memory repair
- tool-grounded memory audit
- inhibited preference execution
- timed reasoning compression
- identity error correction

These candidates are the bridge toward self-extension. They are not promoted
automatically into the base suite until there is repeated evidence or operator
approval.

## Self-Extension Policy

A new category candidate must include:

- `category_id`
- `query`
- `mind_packet`
- `domain_tags`
- `expected_route`
- `promotion_evidence`

Promotion triggers include route mismatch, repeated low-quality replies, new
tool affordances, new affective patterns, memory retrieval failure clusters,
and explicit operator marking.

## CLI

```powershell
python -m holo_host stage111-category-simulation
```

The command is a dry-run simulator. It does not call a provider and does not
touch live transports.
