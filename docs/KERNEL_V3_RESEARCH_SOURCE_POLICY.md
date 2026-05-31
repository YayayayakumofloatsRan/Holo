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

## Research Corpus

`ResearchCorpusStore` is the local webpage/database foundation for later live
web retrieval. It is optional and disabled unless the host passes a store into
`RetrievalOperator`.

Rules:

- raw fetched bodies remain in `ArtifactStore`
- corpus records contain document ids, URIs, artifact refs, payload hashes,
  previews, source assessment, profile ids, and retrieval provenance
- corpus writes are append-only and rebuildable into SQLite
- retrieval journals `retrieval_corpus_document` only when a corpus store is
  configured
- default tests use fake providers and do not require network access

This keeps the future live web path auditable: provider output becomes fetched
artifact, source-assessed evidence, citation, and corpus metadata instead of an
untracked page blob.

## Corpus-Backed Retrieval

`CorpusSearchProvider` and `CorpusFetchProvider` let retrieval reuse the local
web corpus before asking for live web access:

- `CorpusSearchProvider` searches `ResearchCorpusStore` and returns ordinary
  `SearchSource` objects with `provider="research_corpus"`
- `CorpusFetchProvider` reads the referenced artifact blob from `ArtifactStore`
- both providers report `live_network=False`
- profile filtering is applied at corpus search time
- missing artifact refs fail closed instead of fabricating a body

This makes the webpage database a first-class retrieval source while preserving
the existing PolicyGate boundary for future live network providers.

## CLI Workflow

The CLI exposes corpus inspection and corpus-backed retrieval without enabling
live web access:

```bash
holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  --corpus-index .state/kernel_v3/corpus.sqlite \
  retrieve "AAPL 2024 revenue" \
  --uri "https://www.sec.gov/Archives/edgar/data/320193/filing.htm" \
  --title "Apple Form 10-K" \
  --profile finance_fundamentals \
  --index-corpus
```

The command above still uses the bounded fake provider unless a host supplies a
different provider in code. `--index-corpus` only persists safe corpus metadata;
the raw body is stored in the artifact log.

The indexed corpus can then be inspected:

```bash
holo-v3 --corpus-log .state/kernel_v3/corpus.jsonl corpus search "AAPL revenue"
holo-v3 --corpus-log .state/kernel_v3/corpus.jsonl corpus list --profile finance_fundamentals
holo-v3 --corpus-log .state/kernel_v3/corpus.jsonl corpus inspect <document_id>
```

And reused as an offline retrieval source:

```bash
holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  retrieve "AAPL 2024 revenue" \
  --from-corpus \
  --profile finance_fundamentals
```

Repeated observations of the same URI and payload hash are idempotent. The
corpus records a safe re-observation event instead of raising a conflict or
duplicating the document record. If the referenced artifact blob is missing,
corpus-backed retrieval fails closed.

The same persistent stores can be supplied to the main runtime:

```bash
holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  agent "AAPL 2024 revenue" --mode retrieval

holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  resident run-once --worker-id research-worker
```

When a corpus store is configured, the default retrieval operator first queries
`research_corpus`. If it finds a matching document, it fetches the body from the
artifact store and stays offline. If it finds no match, it falls back to the
bounded fake provider used by tests and indexes the resulting fetched document
into the corpus. This is the resident-safe skeleton for future live providers:
live web search can be added behind PolicyGate later without changing the
agent loop or making unit tests depend on network access.
