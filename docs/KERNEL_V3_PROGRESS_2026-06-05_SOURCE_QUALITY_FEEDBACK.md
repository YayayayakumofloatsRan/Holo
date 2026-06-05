# Kernel v3 Progress: Source Quality Feedback Loop

Date: 2026-06-05

## Purpose

This pass improves retrieval and analysis behavior without adding case-specific
answer tables. Recent live academic retrieval showed a structural failure:
search could find many profile-relevant candidates, but the fallback provider
treated discovery-only search/index pages as a successful result and never
continued to concrete paper pages. The result was `no_fetchable_sources` even
though better providers were configured.

The goal is to make source quality a first-class feedback signal across
retrieval, mission supervision, and planner replan hints.

## Changes

- Added profile-agnostic `source_quality_summary()` in
  `kernel_v3.research.source_policy`.
  - Summarizes authority requirement, acceptable source count, primary/
    secondary/weak counts, best sources, family counts, and the next source
    action.
  - The summary is derived from `SourceAssessment`, so it works for finance,
    technical documentation, academic research, and future research profiles.
- Retrieval reports now include `source_quality` and carry it into
  `failure_attribution`.
  - Weak profile sources are rejected before they become formal evidence or
    citations.
  - Authority gaps are reported as `source_authority_gap` or
    `no_primary_source_for_research_profile` instead of collapsing into a vague
    `insufficient_evidence`.
- Thread working-memory/RAG deltas now preserve compact source-quality and
  failure-attribution fields, so the next loop can see why a previous retrieval
  failed.
- Mission supervision now discounts low-quality retrieval citations when
  estimating mission coverage and material progress.
- Planner replan hints now include source-quality and failure-attribution
  signals such as `source_authority_gap` and
  `retrieval_failure:source_authority_gap`.
- `FallbackSearchProvider` now continues past profile discovery-only sources
  when later providers may return concrete fetchable sources. Discovery pages
  are still retained as diagnostics if no better provider succeeds.
- Fixed a package initialization cycle by lazily exposing mission runtime
  symbols from `kernel_v3.agent`.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase114_source_quality_feedback.py
```

Result: `5 passed`.

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_phase82_research_source_policy.py \
  tests/test_kernel_v3_phase97_retrieval_sufficiency.py \
  tests/test_kernel_v3_phase108_generic_research_profile_policy.py \
  tests/test_kernel_v3_phase109_mission_supervisor.py \
  tests/test_kernel_v3_phase109_research_employee_core.py \
  tests/test_kernel_v3_phase111_academic_research_profile.py \
  tests/test_kernel_v3_phase113_retrieval_campaign.py
```

Result: `57 passed` for the source/mission subset and `55 passed` for the
retrieval/profile subset during the iteration.

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase*.py
```

Result before documentation update: `672 passed`.

Live academic retrieval smoke:

```bash
./holo-v3 retrieve "hyperbolic dynamics frontier research recent papers" \
  --profile academic_research \
  --live-retrieval \
  --live-web-search-provider bing_html,duckduckgo_html \
  --live-fetch-discovered-search-hosts \
  --live-max-network-fetches 32 \
  --live-timeout-seconds 20 \
  --live-max-bytes 300000 \
  --max-queries 8 \
  --max-sources 32 \
  --max-fetches 16 \
  --max-spans-per-document 8
```

Before the fallback fix, this produced 56 source candidates but 0 fetches
because selected sources were discovery-only. After the fix, the same live
smoke fetched 16 arXiv paper pages, extracted 128 spans, selected 14 evidence
items, produced 14 citations, and returned report status `sufficient`.

## Remaining Work

- Source ranking still needs more provider-specific evidence quality signals,
  especially for noisy HTML search results and commercial pages.
- The academic profile now reaches paper pages, but synthesis/report quality
  still depends on stronger answer-profile enforcement and better paper
  metadata extraction.
- Query-level search is still sequential. Fetch is parallel; query parallelism
  should wait until provider diagnostics are safe under concurrent execution.
- Long-term memory should later absorb high-quality retrieval outcomes into
  managed project/thread memory, not raw transcript snippets.
