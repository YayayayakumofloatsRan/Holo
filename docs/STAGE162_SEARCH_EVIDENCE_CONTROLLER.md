# Stage162 Search Evidence Controller

Date: 2026-05-27

## Purpose

Stage161 made tool choice model-first. Stage162 improves the actual web-search leg so `web_search` is not a single blind fetch. The host now evaluates whether search results are sufficient for the user's requested evidence type, retries with query variants when needed, and exposes the evidence quality in CLI traces and Stage135 topology.

This is still host-side guardrail logic. It does not add provider calls, memory writes, WeChat starts, watcher authority, or new transport surfaces.

## Schema

```text
holo.stage162.search_evidence_controller.v1
holo.stage162.search_evidence_score.v1
```

## Behavior

The controller derives a required source type from the user turn and query:

```text
general
current
docs
official
official_docs
```

For official/docs requests, it expands query variants such as:

```text
<query>
<query> official
<query> docs
<query> official documentation
```

It stops early when a result is sufficient, or stops with `evidence_exhausted` after the retry budget.

## Evidence Scoring

Each web observation now receives a `search_evidence` block:

```text
status: sufficient | weak | failed
evidence_score
result_count
source_count
official_source_count
docs_source_count
query_term_coverage
missing_evidence
source_urls
```

Official/documentation requests require an official/documentation-like source, not merely any URL.

## Integration

`stage151_tool_decision_loop.execute_tool_decision()` now routes `web_search` through `run_search_evidence_controller()`. Stage152 native DeepSeek web calls already use Stage151 execution, so they inherit the same controller.

Stage153 event streams render search evidence:

```text
[observation] web_search status=ok sources=1 results=1 evidence=sufficient score=0.9
```

Stage135 topology exposes:

```text
search_evidence_controller_node_count
search_evidence_observation_count
search_evidence_best_status
search_evidence_best_score
```

## Boundary

Stage162 improves evidence control and observability. It does not claim that search is solved forever: ranking, multi-provider fallback, page-open validation, and long-form source synthesis remain future work.

## Network Note

Stage162 also removes the explicit empty proxy handler from host DuckDuckGo HTML search/open-page paths. The host now uses the default urllib opener so environment proxy settings can work when the machine requires them.
