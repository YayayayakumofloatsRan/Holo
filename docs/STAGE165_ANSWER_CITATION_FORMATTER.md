# Stage165 Answer Citation Formatter

Date: 2026-05-27

## Purpose

Stage164 gave Holo a source synthesis ledger over opened search pages. Stage165 makes that synthesis visible in final answers. The goal is practical search maturity: a web answer should cite the page evidence it used, report freshness, and degrade honestly when source support is weak, absent, or conflicted.

The search-to-answer chain is now:

```text
model proposes web_search
host executes search provider fallback
Stage162 scores result-list evidence
Stage163 opens candidate pages and verifies body support
Stage164 synthesizes source evidence
Stage165 formats final cited answer from synthesis
host grounding gates verify visible claims against ledgers
```

## Schema

```text
holo.stage165.answer_citation_formatter.v1
```

## API

```text
build_answer_citation_report(web_observation_ledger, user_text, time_observation, max_citations)
render_cited_web_answer(citation_report, channel)
maybe_format_cited_web_answer(user_text, web_observation_ledger, time_observation, channel)
```

## Behavior

Stage165 prefers `web_observation_ledger[*].source_synthesis` and extracts deduplicated citation rows:

```text
index
title
url
status
snippet
```

If an opened page snippet is low-information or contaminated by CSS/page chrome, Stage165 cleans the visible text and can fall back to the same URL's search-result snippet. The ledger still records the opened-page evidence; the formatter only improves the human-readable citation text.

Supported synthesis renders a concise answer with:

```text
web search completed
source pages verified
query
observed time when present
synthesized summary
numbered source URLs and snippets
```

Weak synthesis renders tentative language. Conflicted synthesis reports that sources conflict and avoids settled wording. Unsupported synthesis reports that no supported page evidence is available to cite.

## Runtime Integration

`stage151_tool_decision_loop.build_grounded_web_observation_answer()` now calls Stage165 first. If a Stage164 synthesis exists, Stage165 renders the answer. If no synthesis exists, Stage151 keeps its previous compatibility fallback over raw successful web results.

Stage135 topology now includes:

```text
stage165_answer_citation_formatter
answer_citation_formatter_node_count
answer_citation_formatter_citation_count
```

## Boundaries

Stage165 is formatter and observability logic only. It does not add provider calls, search providers, memory writes, tool execution, WeChat starts, watcher authority, transport changes, hidden reasoning exposure, or approval/sandbox UI.

## Remaining Work

Next stages should test real provider search across more query classes, add richer quote/date extraction, and compare Holo's final cited answers against Codex/Claude-Code-style research-agent expectations.
