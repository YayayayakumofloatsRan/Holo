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
- exchange filings, including SEC/exchange and China disclosure hosts such as
  CNINFO, SSE, SZSE, and HKEX
- company investor relations
- earnings releases
- government statistics

Secondary sources such as reputable news and market data can provide context,
but they do not replace primary evidence for fundamental claims. Weak sources
such as blogs, forums, social posts, generic domains, or unknown sources cannot
by themselves make a finance retrieval report sufficient.

Known official, news, and market-data families are matched by host and
subdomain, so provider URLs such as `static.cninfo.com.cn`,
`markets.reuters.com`, or `quote.eastmoney.com` classify consistently without
live network access.

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
- records retrieval budgets and `network_access` in both query-plan and report
  diagnostics

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
- providers expose a bounded `RetrievalProviderCapability` with provider id,
  provider kind, `live_network`, `default_enabled`, profile awareness, and
  supported research profiles
- profile filtering is applied at corpus search time
- missing artifact refs fail closed instead of fabricating a body

This makes the webpage database a first-class retrieval source while preserving
the existing PolicyGate boundary for future live network providers.
Retrieval query-plan and report diagnostics include these provider capabilities,
so a resident operator can audit whether a run used corpus-only, fake, or
future live-capable providers.

Composite search providers fail soft across provider boundaries. If one search
provider raises, the fallback chain records the provider id, failure status, and
exception type in diagnostics, then tries the next provider. This keeps a
corrupt corpus index or transient future live-provider failure from aborting a
directed research run before another configured provider can answer. If every
provider in the chain fails, the journaled retrieval search attempt is marked
`failed` with `provider_chain_failed` rather than `empty`, so the workloop and
resident operator can distinguish infrastructure failure from "no matching
source".

Provider inspection is also available before a run starts:

```bash
holo-v3 retrieval-providers --profile finance_fundamentals
holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  retrieval-providers --mode default --profile finance_fundamentals
```

This command is read-only. It does not retrieve, fetch, index, or read artifact
bodies. It reports provider capabilities, `network_access`, profile awareness,
and operator-facing issues such as using a generic fake provider for a directed
finance profile. It also inspects composite provider configuration; for
example, an empty fallback search chain is reported as an error before any
resident run can mistake the configuration for a usable search provider.

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
holo-v3 --corpus-log .state/kernel_v3/corpus.jsonl corpus status
holo-v3 --corpus-log .state/kernel_v3/corpus.jsonl corpus inspect-store
```

`corpus status` and `corpus inspect-store` are store-level health surfaces for
resident research operation. They report document counts, profile/provider
coverage, source-family and authority-level distribution, primary-source
coverage, audit-event counts, and small safe document samples. When an
artifact log is configured, `inspect-store` also checks that corpus document
artifact refs and blobs exist, without reading or printing raw fetched bodies;
raw content remains in `ArtifactStore`.

Profiles can also declare freshness budgets. `finance_fundamentals` currently
marks corpus documents stale after 180 days. `corpus inspect-store` reports a
`stale_research_corpus_documents` warning and recommends re-indexing through
the same profile when a resident loop would otherwise keep reusing old
financial evidence.

Corpus-backed retrieval is freshness-aware for profiled research. Ordinary
corpus inspection and corpus search can still show stale records to an
operator, but `CorpusSearchProvider` excludes stale documents when a
`research_profile` is present. Retrieval search-attempt diagnostics include the
provider's freshness summary, including stale counts and sampled document ids,
so a resident trace can explain why an indexed page was not reused as evidence.

And reused as an offline retrieval source:

```bash
holo-v3 \
  --artifact-log .state/kernel_v3/artifacts.jsonl \
  --corpus-log .state/kernel_v3/corpus.jsonl \
  retrieve "AAPL 2024 revenue" \
  --from-corpus \
  --profile finance_fundamentals
```

Repeated observations of the same URI and payload hash are treated as the same
research document, even if the artifact reference or run provenance changes.
The corpus records a safe re-observation event, refreshes the document's
`fetched_at_ms`, updates the SQLite index, and preserves the strongest known
profile/source assessment instead of duplicating the document or leaving a
freshly revalidated page marked stale. If the referenced artifact blob is
missing, corpus-backed retrieval fails closed.

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

## Agent Research Profile

The agent, chat, and resident CLI paths can pass a host-owned research profile
into `retrieval.run`:

```bash
holo-v3 agent "AAPL 2024 revenue" \
  --mode retrieval \
  --research-profile finance_fundamentals

holo-v3 chat --thread research-aapl \
  --once "research AAPL 2024 revenue" \
  --semantic-intake model \
  --research-profile finance_fundamentals

holo-v3 resident run-once \
  --worker-id research-worker \
  --research-profile finance_fundamentals
```

The profile is stored as execution metadata and merged into the retrieval goal
metadata by the host. Models may still propose structured `capability_args`,
but this flag gives operators a deterministic way to require the finance source
policy from the main agent/runtime path. It does not enable live web retrieval;
without a configured live provider, retrieval remains bounded and offline.
