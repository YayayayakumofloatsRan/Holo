# Stage172 Filing Text Retrieval

Stage172 closes the gap between search/open-page evidence and Stage171 market-research pack execution. `market_research_pack` no longer requires callers to manually supply `filing_text` when authoritative page evidence or a SEC/IR source URL is available.

## Schema

```text
holo.stage172.filing_text_retrieval.v1
```

## Runtime Flow

```text
market_research_pack selected
host checks supplied filing_text
host checks Stage163 page_evidence.page_observations
host opens authoritative source URL when network is enabled
host normalizes filing text and inserts Item heading boundaries
Stage171 builds the Stage169 filing pack
Stage170 gates final financial claims
```

## Retrieval Sources

`retrieval_source` can be:

```text
provided
page_evidence
open_page
none
```

The retrieval report records:

```text
retrieval_id
query
status
retrieval_source
source_url
filing_text
filing_text_char_count
opened_count
provider
error
failure_reasons
observed_at
```

## Failure Handling

If network is disabled and no usable filing text exists, Stage172 records `rejected_network_disabled`. If a URL can be opened but the page does not contain recognizable filing section headings, Stage172 records `insufficient` with `filing_text_not_found`.

## Boundaries

- no provider model path outside processor fabric
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no approval/sandbox changes
