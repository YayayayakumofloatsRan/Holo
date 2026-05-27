# Stage170 Market Research Answer Gate

Stage170 connects the Stage169 filing evidence pack to visible answer grounding. It is a deterministic host-side gate for market-research and financial-analysis replies.

## Schemas

```text
holo.stage170.market_research_need.v1
holo.stage170.market_research_claim.v1
holo.stage170.market_research_gate.v1
```

## Purpose

Stage169 can build a filing-driven evidence pack. Stage170 makes that pack matter at answer time:

- financial and market-research claims require a ready `market_research_pack`
- ready packs require source-authority sufficiency, filing checklist completeness, and no metric conflicts
- visible financial metrics must be supported by pack metrics or filing-section evidence
- supported answers can be formatted with pack evidence IDs and source URLs
- unsupported or missing evidence degrades to bounded language

## What It Gates

Stage170 checks visible answer text for:

- financial metrics such as net sales, revenue, net income, operating income, gross margin, and cash
- filing-section references such as Business, Risk Factors, MD&A, and Financial Statements
- investment judgment language such as buy, sell, hold, undervalued, overvalued, or target price

The gate is not a provider call and does not execute tools. It consumes existing Stage169 pack metadata and visible reply text.

## Runtime Integration

`reply_api.py` now evaluates `stage170_market_research_gate` after tool, memory, and FSM grounding repairs and before final bubble construction. If a market-research answer has unsupported financial claims, the visible reply is repaired before delivery and archive. If the pack is ready and claims are supported, the gate can append a compact evidence list.

Stage135 topology exposes a `stage170_market_research_gate` node and metrics:

```text
market_research_gate_node_count
market_research_gate_status
market_research_gate_claim_count
market_research_gate_unsupported_count
```

## Action Space

Stage170 also adds the `market_research_pack` affordance to the model-first tool action space. This lets the model see that market research has a dedicated evidence-pack path instead of treating financial analysis as ordinary web text.

## Boundaries

Stage170 does not add provider calls, live network execution, memory writes, WeChat starts, transport changes, domain-module implementation, hidden reasoning exposure, or approval/sandbox logic. It is a deterministic answer gate over already available evidence.
