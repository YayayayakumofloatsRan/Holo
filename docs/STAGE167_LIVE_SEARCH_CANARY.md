# Stage167 Live Search Canary

Stage167 adds a deterministic live-search canary layer on top of the Stage151-166 evidence chain. The purpose is to measure whether Holo can choose between provider observations, extract fresh source markers, and quote clean supporting evidence before a research answer is trusted.

This stage does not add a new provider model path. It evaluates and reports the existing search stack.

## Schema

```text
holo.stage167.live_search_canary.v1
holo.stage167.provider_comparison.v1
holo.stage167.source_freshness.v1
holo.stage167.quote_extraction.v1
```

## What It Checks

- provider comparison: rank supported official sources above weak or failed providers
- provider failure handling: record failed providers without hiding successful evidence
- source freshness: extract dates, years, and filing-period markers from source text and URLs
- quote extraction: select bounded, CSS-free supporting quotes from source synthesis
- ambiguity handling: flag entity answers that skip required disambiguation
- artifact safety: HTML/JSON/JSONL reports do not expose runtime memory, keys, or hidden reasoning

## CLI

```powershell
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary.html --dry-run
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary_live.html --mode live-smoke
```

The dry-run mode uses deterministic fixtures. The live-smoke mode exercises the existing host web-search evidence path and writes the same artifact bundle.

## Boundaries

Stage167 preserves the kernel boundaries:

- no provider model calls
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no new tool authority path

## Next Stage

The next useful search work is provider abstraction and source-fetch robustness: explicit provider health, more precise first-party-source selection, and broader market/filing fixtures before domain modules depend on live research output.
