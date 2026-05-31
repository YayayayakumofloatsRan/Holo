# Kernel v3 Research Source Policy

This note records the kernel-v3 infrastructure slice for domain-directed
research. It does not enable live web retrieval by default. It adds a
host-owned source policy that optional live search/fetch providers must pass
through before their evidence can support a final answer.

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
- exposes a generic network cost hint (`default_network_fetch_cost` and the
  `max_fetches` payload field) through the tool manifest so `LoopControllerV3`
  can enforce network budgets before live-capable retrieval executes, without
  dispatching on the concrete `retrieval.run` tool name
- clamps oversized retrieval goals at the operator boundary before search or
  fetch execution. Current host caps are 4 queries, 20 sources, 10 fetches, and
  5 spans per document; when clamping occurs, the journal records both the
  requested budget and the effective bounded budget.

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
- corpus-backed retrieval records `corpus_documents_searched` audit events with
  query hashes, profile ids, limits, document ids, and access context; raw query
  text and page bodies are not embedded in those audit events
- corpus search results and inspection samples are clamped by host-owned store
  caps, so CLI, retrieval, and future resident loops cannot request unbounded
  corpus output through a large limit
- corpus fetches that read raw artifact blobs record `artifact_blob_read` audit
  events with artifact ids, payload hashes, byte counts, and safe access
  context only; raw page bodies are never embedded in access audit records
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
  and requests low-sensitive blob-read audit
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
Providers marked `default_enabled=False` are not called by the fallback chain.
They remain visible in provider capabilities and diagnostics, and inspection
reports an error when every concrete fallback provider is disabled. This keeps
future live search providers opt-in even if they are present in the process.

## Optional Live HTTP Fetch Surface

`HttpFetchProvider` is the first live-network retrieval provider surface. It is
not part of the default CLI or unit-test path:

- it reports `live_network=True` and `default_enabled=False`
- it returns `disabled_by_default` without calling transport when invoked while
  disabled
- it fails closed unless the host explicitly enables it and configures either an
  allowed-host list or `allow_all_hosts=True`
- it rejects non-allowed URL schemes, URLs without hosts, and URLs with
  embedded credentials
- it enforces timeout and maximum body-byte bounds before returning a body
- diagnostics contain status, byte counts, URL scheme, and host hash only; raw
  URLs and response bodies are not embedded in diagnostics
- tests use an injected transport and never perform network access

When wired into a `RetrievalOperator`, the operator reports
`network_access=True`, so the existing `PolicyGate` `network:fetch` boundary is
still the execution gate for agent/tool runs.

## Optional Live JSON HTTP Search Surface

`JsonHttpSearchProvider` is the matching live-network search surface for
HTTP/JSON search APIs. It is infrastructure only; it is not part of the default
CLI or unit-test path.

- it reports `live_network=True` and `default_enabled=False`
- it returns `disabled_by_default` without calling transport when invoked while
  disabled
- it calls no network path unless the host constructs it and the fallback chain
  considers it enabled
- it fails closed unless the endpoint host is explicitly allowed or
  `allow_all_hosts=True`
- it rejects non-allowed URL schemes, endpoints without hosts, and endpoints
  with embedded credentials
- it supports env-only API keys through a configured header; API key values and
  env var names are not copied into provider diagnostics
- it accepts a configurable JSON `results_path`, defaults to `["results"]`,
  and normalizes common result fields such as `url`, `uri`, `link`, `title`,
  `name`, `snippet`, `description`, and `summary`
- it drops results without a usable URI and bounds query/result text before
  returning `SearchSource` objects
- source metadata contains a result payload hash, not the raw JSON result body
- diagnostics contain status, counts, URL scheme, host hash, query hash, and
  plan id only; raw endpoint URLs, raw queries, API keys, and response bodies
  are not embedded in diagnostics
- tests use an injected transport and never perform network access

The provider is intentionally generic. A finance fundamentals deployment can
wrap a regulator, exchange, vendor, or local gateway endpoint behind this
surface while still letting the retrieval operator apply the same source
authority policy, corpus indexing, artifact storage, and citation rules.

Live HTTP retrieval configuration is centralized in `LiveRetrievalConfig` and
read from environment variables only:

```text
HOLO_V3_LIVE_RETRIEVAL=1
HOLO_V3_LIVE_SEARCH_ENDPOINT=https://...
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api.example.com
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=docs.example.com,static.example.com
HOLO_V3_LIVE_SEARCH_API_KEY_ENV=DEEPSEEK_API_KEY
HOLO_V3_LIVE_SEARCH_API_KEY_HEADER=Authorization
HOLO_V3_LIVE_SEARCH_API_KEY_PREFIX="Bearer "
HOLO_V3_LIVE_SEARCH_RESULTS_PATH=results
HOLO_V3_LIVE_RETRIEVAL_TIMEOUT_SECONDS=20
HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES=1000000
```

`HOLO_V3_LIVE_RETRIEVAL=1` is the enable gate. Without it, the configured
provider can still be inspected but reports `default_enabled=false`. API key
values are read only by the provider at call time, and provider inspection
reports only booleans, host hashes, counts, and bounds.

Agent execution has a second, separate gate. Even if a host injects a live
`RetrievalOperator`, `retrieval.run` is registered as a network tool and
`PolicyGate` blocks it unless host-owned execution metadata grants
`network:fetch` and a bounded network budget:

```json
{
  "retrieval": {
    "allow_network": true,
    "max_network_fetches": 1,
    "max_fetches": 1
  }
}
```

Model planner payloads can request retrieval arguments, but they cannot grant
`network:fetch`. That permission is derived only from host execution metadata.
The CLI exposes this as an explicit live agent flag:

```bash
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_SEARCH_ENDPOINT=https://... \
holo-v3 agent "AAPL 2024 revenue" \
  --mode retrieval \
  --live-retrieval \
  --live-max-network-fetches 1 \
  --research-profile finance_fundamentals
```

If the env gate or endpoint is missing, the command returns a blocked payload
before constructing a live retrieval operator or starting the agent loop.

Provider inspection is also available before a run starts:

```bash
holo-v3 retrieval-providers --profile finance_fundamentals
holo-v3 retrieval-providers --mode live-http --profile finance_fundamentals
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
