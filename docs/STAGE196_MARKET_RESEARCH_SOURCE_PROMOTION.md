# Stage196 Market Research Source Promotion

Stage196 promotes web/page observations into a market-research source state. The goal is to make Holo's financial research loop understand when a discovered source is actually suitable for pack/report generation, instead of treating every search result as equivalent prompt text.

## Schemas

- `holo.stage196.market_research_source_promotion.v1`

## What It Does

Stage196 consumes:

- `web_observation_ledger`
- Stage163 `page_evidence`
- Stage168 `source_authority`
- optional Stage186 live crawler output

It produces:

- selected authoritative filing URL
- source family and authority tier
- page evidence status
- whether filing text is already available
- whether the source can feed `market_research_pack`
- promoted web-observation rows

## Promotion Logic

For market research, a promoted source must satisfy financial-filing authority:

```text
financial_filing or company_ir source authority
selected URL exists
page evidence and/or source URL can feed filing text retrieval
```

Third-party summaries are not promoted. They remain weak evidence even when the snippet discusses a filing.

If no useful rows exist and network is enabled, Stage196 may run the existing Stage186 live crawler with a bounded query budget. This preserves the existing `query -> search -> open_page -> evaluate` path instead of adding a new raw fetch path.

## Runtime Integration

Stage195 records Stage196 after each market-research execution round. The latest promotion is returned under:

```text
stage196_market_research_source_promotion
```

The promotion is exposed in:

- Stage153 event stream as `[source_promote]`
- Stage191 public thought stream as an observation card
- Stage135 topology as `market_research_source_promotion`
- reply debug / reply JSON / archive metadata when Stage195 is active

## Boundaries

Stage196 does not:

- call provider models
- write memory
- start WeChat
- widen transport authority
- expose raw hidden reasoning or provider `reasoning_content`

If it uses crawling, it delegates to Stage186 and respects `runtime.network_enabled`.

## CLI Trace

The CLI trace line is:

```text
[source_promote] status=promoted authority=sufficient family=financial_filing page=supported pack=true stop=final_answer_ready url=https://...
```

This gives the operator a clear view of whether Holo found a reusable source or only a weak third-party reference.
