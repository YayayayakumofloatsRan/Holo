# Stage163 Page Evidence Verifier

Date: 2026-05-27

## Purpose

Stage162 made `web_search` evaluate search-result sufficiency. Stage163 verifies the next layer: whether candidate source pages actually contain page-body evidence that supports the search goal.

This moves Holo's search ability from result-list grounding toward Codex-style source inspection:

```text
model proposes web_search
host searches
host scores result-list evidence
host opens candidate pages
host scores page-body support
ledger records search_evidence + page_evidence
final claims are grounded against ledgers
```

## Schema

```text
holo.stage163.page_evidence.v1
holo.stage163.page_evidence_score.v1
```

## Behavior

Stage163 adds:

```text
extract_page_evidence_text(html_text, url)
score_page_evidence(page_observation, query, user_text)
verify_page_evidence_for_search(web_observation, open_page_fn, network_enabled, query, user_text, max_pages)
attach_page_evidence_to_web_observation(web_observation, open_page_fn, network_enabled, query, user_text, max_pages)
```

For `web_search`, Stage151 now attaches `page_evidence` to successful web observation rows. The verifier opens up to two candidate URLs by default, extracts title/body text, scores query-term coverage, and stops early once a page is supported.

## Ledger Shape

`web_observation_ledger[*].page_evidence` contains:

```text
schema
status: supported | weak | unsupported | error | rejected_network_disabled
query
opened_count
selected_url
best_evidence_score
term_coverage
supporting_snippet
missing_evidence
page_observations[]
stop_reason
```

If network is disabled, Stage163 records `rejected_network_disabled` and does not open any page.

## Runtime Integration

Stage163 is additive:

```text
Stage151 execute_tool_decision -> Stage162 search controller -> Stage163 page verifier
Stage153 event stream -> renders page=<status> opened=<count>
Stage135 topology -> page_evidence_verifier node and metrics
```

It does not add a provider call path, memory write, WeChat start, watcher authority, transport widening, or hidden reasoning exposure.

## Live Smoke

A live host smoke against `OpenAI Codex CLI docs` returned:

```text
search_status=sufficient
attempt_count=1
best_sources included https://developers.openai.com/codex/cli
page_status=supported
opened_count=1
selected_url=https://developers.openai.com/codex/cli
score=1.0
```

## Remaining Work

Stage163 validates page-body support for the strongest result pages. Future stages should add multi-provider search fallback, source synthesis over multiple opened pages, freshness/date extraction, and source-citation formatting in final replies.
