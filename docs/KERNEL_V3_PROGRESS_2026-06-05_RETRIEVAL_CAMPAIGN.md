# Kernel v3 Progress: Retrieval Campaign and Failure Attribution

Date: 2026-06-05

## Purpose

This pass targets the weakest current capability: real deep retrieval. Earlier
live tests showed that large fetch budgets did not guarantee better search
behavior because a `retrieval.run` payload could still produce only one query.
When that query failed or produced weak evidence, the next loop often lacked a
clear diagnosis for how to change strategy.

The goal here is not to add case-specific search strings. The goal is to make
the retrieval FSM expose a reusable search campaign and a precise failure model
that the agent loop can feed back to the planner.

## Changes

- Added `kernel_v3.retrieval.query_campaign`.
  - Builds a bounded `QueryCampaign` from the base query, research profile
    templates, model/mission query hints, source-target hints, source-family
    switches, and generic research axes.
  - Skips exact or materially similar attempted queries when the caller passes
    `attempted_queries`, `avoid_repeating`, or mission directive metadata.
  - Emits query signatures and selected/skipped diagnostics for journal audit
    and next-loop planning.
- Rewired `rank.plan_queries()` to delegate query construction to
  `build_query_campaign()`, leaving ranking focused on source ranking.
- Connected `RetrievalOperator` query plans to campaign diagnostics.
- Changed retrieval payload defaults so a large fetch/source budget, aggregate
  search strategy, or balanced/deep research depth defaults to a multi-query
  campaign instead of a single query when the model omits `max_queries`.
- Added retrieval report failure attribution:
  - `query_plan_empty`
  - `search_no_sources`
  - `ranking_no_sources`
  - `no_fetchable_sources`
  - `fetch_failed_or_empty`
  - `extraction_no_spans`
  - `all_evidence_rejected`
  - `citation_generation_missing`
  - `coverage_gap`
- Added `next_strategy_hint` so a later planner loop can distinguish query
  diversification, source-family switch, direct/structured-source repair,
  extraction repair, citation repair, and coverage-gap targeting.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase113_retrieval_campaign.py \
  tests/test_kernel_v3_phase103_model_retrieval_feedback.py \
  tests/test_kernel_v3_phase105_adaptive_search_strategy.py \
  tests/test_kernel_v3_phase112_strategy_supervision.py
```

Result: `23 passed`.

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase*.py
```

Result after this pass: `668 passed`.

Live retrieval campaign smoke, isolated under
`/tmp/holo-v3-live-campaign-smoke-2`, queried public DeepSeek API documentation
terms with `bing_html,duckduckgo_html`, `max_sources=16`, and `max_fetches=16`.
The CLI now defaulted `max_queries` to `8`, produced eight search attempts,
collected eighty source candidates, fetched ten pages, and produced nine
citations with report status `sufficient`.

Observed limitation from the live smoke: without an explicit
`technical_documentation` profile, generic query axes can still collect broad
DeepSeek pages instead of official API documentation first. This is an authority
ranking/source-profile problem, not a loop-control problem.

## Remaining Work

- Query search itself is still sequential. Fetch is already parallel, but
  query-level search concurrency needs provider diagnostics that are safe under
  parallel execution before it should be enabled.
- The live HTML search engines remain fragile. Multi-engine search and
  structured/source-directory providers are more reliable than a single HTML
  engine, but the provider layer still needs stronger live canaries, fallback
  routing, and source-specific extraction tests.
- Failure attribution is now present in reports; the next step is to make
  mission/planner prompts consume it more explicitly when deciding the next
  retrieval strategy.
- Generic campaign expansion improves breadth, but authority ranking still
  needs to prefer official/source-profile matches more aggressively for
  documentation, academic, and finance tasks.
