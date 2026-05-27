# Stage164 Search Fallback And Source Synthesis

Date: 2026-05-27

## Purpose

Stage163 verifies one or more opened pages after search. Stage164 adds the next practical search capability: provider fallback and source-level synthesis.

The intended search chain is now:

```text
model proposes web_search
host tries search providers in order
Stage162 scores result-list evidence per provider
Stage163 opens candidate pages and scores page-body support
Stage164 synthesizes supported page evidence into a compact source basis
host finalizes only against ledgers
```

## Schema

```text
holo.stage164.search_fallback.v1
holo.stage164.search_fallback_attempt.v1
holo.stage164.source_synthesis.v1
```

## Behavior

Stage164 exposes:

```text
run_search_fallback_controller(query, user_text, network_enabled, search_providers, max_attempts_per_provider)
build_source_synthesis(web_observation_ledger, query)
attach_source_synthesis_to_observations(observations, query)
```

The fallback controller tries providers in order and stops when a provider returns sufficient Stage162 evidence. Each web observation records a `stage164_search_fallback` block with the provider name, provider index, provider status, attempt count, best evidence score, and stop reason.

The source synthesis builder combines supported and weak Stage163 page evidence into a deterministic synthesis report:

```text
status: supported | weak | unsupported | conflicted
supported_source_count
weak_source_count
conflict_count
risk_flags
confidence
citations[]
synthesized_summary
```

Simple contradiction cues such as `supports` versus `does not support` mark the synthesis as `conflicted`, so Holo does not flatten source disagreement into a confident answer.

## Runtime Integration

`stage151_tool_decision_loop.execute_tool_decision()` now routes `web_search` through Stage164. It then applies Stage163 page verification and attaches Stage164 source synthesis back to the same web observation rows.

Visible surfaces:

```text
web_observation_ledger[*].stage164_search_fallback
web_observation_ledger[*].source_synthesis
Stage151/Stage153 event streams: synthesis=<status> supported_sources=<n>
Stage135 topology: source_synthesis node and metrics
```

## Boundaries

Stage164 is host-side evidence control only. It does not add a provider model call path, memory write, WeChat start, watcher authority, transport widening, hidden reasoning exposure, or approval/sandbox UI.

## Remaining Work

Stage164 provides deterministic synthesis over opened page evidence. Future work should add configured real alternate search endpoints beyond DuckDuckGo HTML, richer date/freshness extraction, source quote extraction, and answer-time citation formatting.
