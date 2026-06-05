# Kernel v3 Progress - Deep Retrieval System

Date: 2026-06-05
Branch: `kernel-v3`

## Objective

Improve the deep retrieval system without turning Holo into a table-driven
test responder. The target is a general research substrate that can support
finance, academic, technical, and open-ended investigation while preserving
host-owned execution:

- the model proposes retrieval actions and strategy shifts;
- the host validates budgets and policy, executes providers, stores raw bodies
  in artifacts, evaluates evidence, and falls back to safe query expansion only
  when the model has not supplied a usable retrieval strategy;
- failed or incomplete retrieval becomes structured feedback for the next loop
  rather than an exception that ends the agent run.

## Changes

- Added automatic generation-gear assessment in
  `kernel_v3/processors/generation.py`.
  - Routine interaction remains fast model / no thinking by default.
  - Replanning and deep-research packets can auto-upshift model class and
    reasoning effort from structured host state, not user keyword tables.
- Added model-owned retrieval strategy packets.
  - `semantic.intake` and `planner.propose` contracts now tell the model to
    emit `metadata.retrieval_strategy` when a task needs real research
    judgment.
  - The strategy packet can include task understanding, domain hypotheses,
    source-family plan, concrete query plan, avoid-repeat hints, fallback
    moves, evidence criteria, and stop conditions.
  - This is domain-general: mathematics, physics, finance, policy, engineering,
    humanities, and other research tasks should all use the same strategy
    packet shape instead of host-side vertical templates.
- Reworked query-campaign planning in `kernel_v3/retrieval/query_campaign.py`.
  - If `metadata.retrieval_strategy.query_plan` is present, those model queries
    are executed first and fixed host axes are disabled by default.
  - Host axes such as target entity, profile facet, mission coverage, source
    family, and generic research now act as fallback expansion when no model
    strategy exists or when explicitly enabled.
  - Query diagnostics show whether a model strategy was present, how many
    strategy queries were used, and whether host axes were enabled.
- Preserved model retrieval strategies through action binding and payload
  normalization in `AgentRuntime` and `RetrievalOperator`.
  - Top-level `retrieval_strategy`, `preferred_source_families`,
    `source_family_plan`, `source_authority_requirement`, `search_strategy`,
    `query_campaign`, and `minimum_coverage` are normalized into retrieval
    metadata instead of being dropped.
  - The retrieval operator derives default `max_queries` from the strategy
    query plan when no explicit budget is provided.
- Updated retrieval strategy supervision.
  - If a model strategy contains concrete query or source-family plans, host
    supervision preserves it and lets the campaign layer handle attempted-query
    filtering.
  - The host still validates policy, budgets, repetition, evidence sufficiency,
    and termination.
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
705 passed in 76.00s
```

Focused regression group:

```text
26 passed in 0.66s
```

Focused group contents: model retrieval strategy, retrieval campaign,
strategy supervision, and deep retrieval system regressions.

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

Live model-strategy smoke:

```text
thread: codex-smoke-model-strategy
query: 请检索双曲动力学近年研究前沿，重点找论文、综述和开放问题，不要只给定义
model route: semantic.intake -> planner.propose -> retrieval.run -> evaluator.assess
planner payload: metadata.retrieval_strategy present
strategy fields observed: task_understanding, domain_hypotheses,
  source_family_plan, query_plan, avoid_repeating, fallback_moves,
  evidence_criteria, stop_when
retrieval attempts observed before manual interrupt: 3
first campaign queries observed: 5
second campaign queries observed: 3
third campaign queries observed: 6
```

Interpretation: the live planner produced a domain-general academic strategy
packet and the retrieval trace executed those model-proposed queries. This
confirmed the desired boundary: the model chose the research moves, while the
host validated and journaled the tool calls. The smoke was manually interrupted
after the third retrieval because non-interactive JSON mode gave no progress
heartbeat while the next planner call was running; this is an interaction
surface issue to fix separately, not evidence that model strategy propagation
failed.

## Current Capability

The retrieval layer is now materially stronger than a single web-search call:
it can accept a model-owned research strategy packet, run the model's concrete
query plan first, fall back to host expansion when needed, route through
profile-aware structured providers, retain large candidate pools, fetch
concurrently, reject poor source families, and return a structured coverage gap
for the next agent loop.

The most important remaining gap is not the inner retrieval FSM but the
outer-loop strategy supervisor and source acquisition quality: when a profile
or mission says one facet is still missing, the next planner packet now can
carry a different model-owned strategy, but the available providers still need
better specialized source acquisition for some verticals and better heartbeat
visibility while long live calls are running.

## Next Work

- Feed mission-level coverage gaps into model-owned retrieval strategy packets
  as compact prior attempts, rejected source families, and required evidence
  criteria.
- Add profile-specific direct structured continuations for finance valuation
  and market data.
- Improve cross-loop result compaction so the planner sees accepted evidence,
  missing facets, rejected source families, and attempted queries in one small
  packet.
- Add progress heartbeats and host-side timeout/cancel handling for
  non-interactive live `chat --once --output json` runs.
- Feed successful research reports into the memory proposal pipeline so future
  runs can recall known issuer/source facts before searching.
