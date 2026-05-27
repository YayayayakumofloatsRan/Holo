# Stage169 Market Research Pack

Stage169 turns Holo's source-authority layer into a reusable market-research evidence pack. It is a deterministic host-side packer for filing-driven research, aimed at the long-term requirement that Holo can assist with market research, filing reading, and evidence-backed analysis.

## Schemas

```text
holo.stage169.market_entity.v1
holo.stage169.filing_sections.v1
holo.stage169.filing_checklist.v1
holo.stage169.financial_metrics.v1
holo.stage169.metric_consistency.v1
holo.stage169.market_research_pack.v1
holo.stage169.market_research_pack_bundle.v1
```

## What It Does

Stage169 builds a pack from:

- current market/filing query
- `web_observation_ledger`
- filing text extracted from a primary source
- Stage168 `source_authority`

It then reports:

- entity normalization: ticker, CIK, canonical name
- filing section extraction: Business, Risk Factors, MD&A, Financial Statements
- filing checklist coverage
- financial metrics: net sales/revenue, net income, operating income, gross margin, cash
- metric consistency checks across sources
- evidence items with source URLs and section/metric snippets

## CLI

```powershell
python -m holo_host run-market-research-pack --output artifacts\stage169\stage169_market_research_pack.html --dry-run
```

The command writes HTML, JSON, and JSONL artifacts.

## Boundary

Stage169 does not call providers, execute live tools, write memory, start WeChat, widen transport authority, or expose hidden reasoning. It consumes existing ledgers and deterministic fixture text.

## Next Work

Stage170 should make this pack usable by the agent loop: when a market-research task is detected, Holo should collect a source-authority-sufficient filing pack before producing a final analysis, and final financial claims should cite the pack's evidence items.
