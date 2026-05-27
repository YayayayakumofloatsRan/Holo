# Stage166 Search Quality Evaluation

Date: 2026-05-27

## Purpose

Stage166 turns the Stage151-165 search chain into a measurable reliability surface. Holo now has a deterministic search-quality evaluation bundle for the kinds of work expected from an advanced engineering and research agent: official documentation lookup, API documentation, current information, financial filings, ambiguous entities, and failure cases.

The purpose is not to add another search path. Stage166 evaluates whether the existing path is good enough:

```text
model proposes web_search
host executes and ledgers search/open-page evidence
Stage162 scores search-result sufficiency
Stage163 verifies opened page bodies
Stage164 synthesizes source support
Stage165 renders cited visible answers
Stage166 scores answer quality and failure behavior
```

## Schema

```text
holo.stage166.search_quality_eval.v1
```

## CLI

```powershell
python -m holo_host run-search-quality-eval --output artifacts\stage166\stage166_search_quality.html --dry-run
python -m holo_host run-search-quality-eval --output artifacts\stage166\stage166_search_quality_live.html --mode live-smoke
```

Dry-run is deterministic and does not require provider calls or live network. Live-smoke uses the local host search/open-page path and should be treated as an operational smoke, not a required unit-test dependency.

## Query Categories

```text
official_docs
api_docs
current_news
financial_filings
ambiguous_entity
failure_case
```

The financial-filings category exists because the target agent base must eventually support market research, filings review, and evidence-backed financial analysis.

## Metrics

```text
pass_rate
source_support_score
citation_sufficiency_score
freshness_score
unsupported_claim_rate
conflict_rate
css_noise_rate
expected_term_coverage
latency_estimate
```

Stage166 also reports a raw-result baseline so the full Stage151-165 stack can be compared against a naive search-result-only answer.

## Artifacts

Stage166 writes:

```text
.html
.json
.jsonl
```

The HTML report is human-readable; JSON and JSONL are intended for regression tracking and future long-horizon benchmark aggregation.

## Boundaries

Stage166 is evaluation logic. It does not add provider model calls, memory writes, WeChat starts, watcher authority, transport widening, hidden reasoning exposure, or a new tool authority path.

## Remaining Work

Future stages should add larger live query sets, provider comparisons, financial filing table extraction, source-date extraction, freshness ranking, and report-level reasoning checks for market-research workflows.
