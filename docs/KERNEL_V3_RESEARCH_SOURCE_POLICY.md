# Kernel v3 Research Source Policy

This note records the first kernel-v3 infrastructure slice for domain-directed
research. It does not add live web retrieval. It adds a host-owned source policy
that future live search/fetch providers must pass through before their evidence
can support a final answer.

## Boundary

- Search and fetch providers may return candidate sources.
- The host classifies source family and authority.
- The model may propose a research task, but it does not decide whether a
  source is authoritative.
- Raw fetched bodies still go to `ArtifactStore`; journal records contain
  previews, hashes, assessments, diagnostics, evidence, and citations.
- Unit tests remain offline and use fake providers.

## Finance Fundamentals Profile

`finance_fundamentals` is the first profile. It prefers primary sources:

- regulatory filings
- exchange filings
- company investor relations
- earnings releases
- government statistics

Secondary sources such as reputable news and market data can provide context,
but they do not replace primary evidence for fundamental claims. Weak sources
such as blogs, forums, social posts, generic domains, or unknown sources cannot
by themselves make a finance retrieval report sufficient.

## Retrieval Integration

When a `SearchGoal` includes:

```json
{"metadata": {"research_profile": "finance_fundamentals"}}
```

the retrieval operator:

- journals `retrieval_source_assessment`
- ranks sources with source authority included in the score
- attaches `source_assessment` diagnostics to evidence items
- requires at least one primary source before returning a sufficient finance
  retrieval report
- includes source-authority counts in the final `RetrievalReport`

This prepares the kernel for future live web/database providers without making
live retrieval the default.
