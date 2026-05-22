# Stage113 Agent Tool Executor Design

## Context

Stage106 exposes tool schemas to providers. Stage107 can pause on
`execute_tool_locally`. Stage112 proves provider tool calls can be parsed and
bounded. The missing piece is local execution.

## Design

Stage113 takes parsed provider tool calls and returns local observations.

Inputs:

- provider tool calls from Stage106 parsing;
- optional external lookup backend;
- optional local memory corpus path;
- optional repo root for documentation-memory fallback;
- network enable flag.

Outputs:

- executed observations;
- skipped rejected calls;
- compact observation summary;
- Stage107 reentry contract.

## Tools

`external_lookup`

- Executes through an injected backend in tests.
- Uses DuckDuckGo HTML lookup only when network is explicitly enabled.
- Returns status, result snippets, URLs, and errors.

`memory_recall`

- Loads JSONL or local docs corpus.
- Ranks rows by query-term overlap.
- Returns matched ids, scores, terms, and excerpts.

## Authority

Provider execution remains forbidden. The provider proposes calls. Stage113
executes allowlisted calls locally.

## Tests

Tests verify:

- accepted calls execute;
- rejected calls are skipped;
- memory recall returns local matches;
- external lookup can execute through the backend contract;
- observations re-enter Stage107 before the next provider packet;
- CLI executes memory recall.
