# Kernel v3 Progress - Deep Retrieval System

Date: 2026-06-05
Branch: `kernel-v3`

## Objective

Improve the deep retrieval system without turning Holo into a table-driven
test responder. The target is a general research substrate that can support
finance, academic, technical, and open-ended investigation while preserving
host-owned execution:

- the model proposes retrieval actions and strategy shifts;
- the host expands safe query campaigns, validates budgets and policy, executes
  providers, stores raw bodies in artifacts, and evaluates evidence;
- failed or incomplete retrieval becomes structured feedback for the next loop
  rather than an exception that ends the agent run.

## Changes

- Added automatic generation-gear assessment in
  `kernel_v3/processors/generation.py`.
  - Routine interaction remains fast model / no thinking by default.
  - Replanning and deep-research packets can auto-upshift model class and
    reasoning effort from structured host state, not user keyword tables.
- Expanded query-campaign planning in `kernel_v3/retrieval/query_campaign.py`.
  - Campaigns now include target-entity, profile-facet, mission-coverage,
    source-family, and generic axes.
  - Query diagnostics include target entities and profile facets.
- Attached answer-profile, minimum-coverage, and research-mission metadata to
  retrieval payloads in `AgentRuntime`.
  - General detailed/deep research now gets larger default query/source/fetch
    budgets.
  - Explicit user/CLI budgets are respected and are not silently expanded.
- Improved retrieval ranking and fetch scheduling in
  `kernel_v3/retrieval/operator.py`.
  - Search attempts can retain a larger candidate pool for deep research.
  - Discovery-only and weak sources no longer consume the whole fetch window
    before actual documents can be fetched.
  - Source rejections are journaled separately from evidence rejections.
  - Failure attribution distinguishes search gaps, source-authority gaps,
    fetch failures, extraction gaps, citation gaps, and coverage gaps.
- Tightened discovery/source-quality policy.
  - Academic search/index pages are not final evidence.
  - Finance source-directory entries are not blanket-rejected; SEC search,
    ticker/CIK directories, and filing-directory metadata remain discovery-only
    unless the goal is explicitly a discovery/lookup goal.
- Added a small built-in public issuer registry for common US issuers in
  `kernel_v3/research/issuer_registry.py`.
  - This seeds identifiers such as ticker and CIK for structured provider
    lookup.
  - It is not an answer table; it only helps choose canonical source URLs.
- Improved source-directory ranking so curated template order is a small
  tie-breaker inside a source family.
- Default live retrieval provider strategy is now adaptive. It can stay
  fallback for simple/explicit-budget tasks and switch to aggregate/structured
  when the payload requests it.
- Mission thread working memory now records real attempted queries instead of
  evidence previews as avoid-repeat hints.

## Validation

Deterministic kernel-v3 phase tests:

```text
684 passed in 70.07s
```

Focused regression group:

```text
92 passed in 11.77s
```

Live finance smoke:

```text
query: NVIDIA fundamentals revenue net income market cap valuation
profile: finance_fundamentals
search_attempt_count: 24
fetch_attempt_count: 40
evidence_count: 10
citation_count: 10
status: insufficient_evidence
reason: finance_fundamental_facets_missing
missing facet: valuation
```

Interpretation: the system found SEC filing and SEC companyfacts evidence for
revenue/net income, rejected weak/discovery sources, and correctly refused to
mark the retrieval complete because valuation coverage was missing. This is a
good next-loop signal, not a tool crash.

Live academic smoke:

```text
query: hyperbolic dynamics frontier research recent papers open problems
profile: academic_research
search_attempt_count: 16
fetch_attempt_count: 24
evidence_count: 6
citation_count: 6
status: sufficient
```

Interpretation: the system used scholarly source families such as arXiv and
publisher pages, rejected many discovery-only and weak sources, and produced
accepted citations for the academic profile.

## Current Capability

The retrieval layer is now materially stronger than a single web-search call:
it can run multi-axis query campaigns, route through profile-aware structured
providers, retain large candidate pools, fetch concurrently, reject poor source
families, and return a structured coverage gap for the next agent loop.

The most important remaining gap is not the inner retrieval FSM but the
outer-loop strategy supervisor: when a profile says one facet is still missing,
the next planner packet should be pushed harder toward a different source
family or provider class instead of repeating semantically similar searches.
Finance valuation is the clearest current example.

## Next Work

- Add an explicit strategy-shift directive for missing facets:
  `coverage_gap -> switch_source_family -> new retrieval payload`.
- Add profile-specific direct structured continuations for finance valuation
  and market data.
- Improve cross-loop result compaction so the planner sees accepted evidence,
  missing facets, rejected source families, and attempted queries in one small
  packet.
- Feed successful research reports into the memory proposal pipeline so future
  runs can recall known issuer/source facts before searching.
