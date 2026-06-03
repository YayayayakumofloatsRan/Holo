# Kernel v3 progress: retrieval source quality hardening

Date: 2026-06-04

## Context

Live retrieval tests showed that broad web search could return high-noise
same-name pages. For example, a query for a specific organization could return
dictionary pages, TV pages, banks, schools, or generic official search shells.
The previous loop often learned from evidence rejection, but it still wasted
fetch budget and could treat template/search-shell text as citable evidence.

## Changes

- Added source-level target-entity gating before fetch. If a query has a clear
  multi-token target entity and a ranked web source does not cover that entity
  in its title, snippet, or URI, the retrieval operator journals
  `retrieval_source_rejections` and does not spend fetch budget on that source.
- Kept host-curated direct/structured sources exempt from this source gate, so
  explicit URLs and structured official data paths can still be fetched.
- Added compact-domain matching for target entities. A query target such as
  `Citadel Security` can match a source URI like `citadelsecurity...`.
- Treated technical/source-platform terms such as `API`, `docs`, `SEC`,
  `EDGAR`, `Crunchbase`, and `LinkedIn` as query/source hints rather than target
  entities.
- Added template/placeholder evidence rejection. Spans dominated by
  `{{field}}`, `${field}`, or `<% field %>` placeholders are rejected as
  `template_placeholder_evidence`.
- Wired `retrieval_source_rejections` into workloop progress and replan hints so
  failed candidate matching becomes useful LLM feedback rather than silent
  failure.

## Live validation

- Direct live retrieval for `Citadel Security company size employees revenue
  operations` returned only mismatched Citadel candidates and produced
  `source_rejection_count=10`, `fetch_attempt_count=0`, and no citations.
- Direct live retrieval for `DeepSeek API docs authentication pricing models`
  still fetched and extracted normally, with `source_rejection_count=0`; the
  remaining gap was the authentication facet, not source gating.
- A live agent run for `Citadel Security` no longer finalized from the CNINFO
  search-template shell after placeholder rejection. It eventually returned a
  failure report after repeated live strategies exhausted the configured network
  budget.

## Remaining work

- Ordinary `holo-v3 agent` still lacks the streaming activity display available
  in the interactive chat console.
- Deep live research can grow context above 100k prompt characters after many
  mission iterations. The next hardening pass should compact repeated retrieval
  diagnostics before processor calls.
- Search strategy is still mostly provider-driven. Better domain/source
  selection and structured source discovery should continue to reduce blind web
  search reliance.
