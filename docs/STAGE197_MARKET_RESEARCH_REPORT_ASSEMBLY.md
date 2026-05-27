# Stage197 Market Research Report Assembly

Stage197 adds a source-aware report assembly boundary for the market-research stack.

Stage196 can promote an authoritative SEC/IR filing source, and Stage173 can build a deterministic report from a filing evidence pack. Stage197 connects those two surfaces: a report is not treated as finally ready unless it actually cites the promoted source.

## Schema

- `holo.stage197.market_research_report_assembly.v1`

## Inputs

Stage197 consumes only existing local metadata:

- `stage196_market_research_source_promotion`
- `stage173_market_research_report`
- `market_research_report_ledger`

It does not call provider models, fetch network pages, execute tools, write memory, start WeChat, or widen transport authority.

## Output States

- `assembled`: promoted source exists, report is `evidence_ready`, promoted source is cited, and unsupported-claim count is zero.
- `citation_mismatch`: promoted source exists, but the report citations do not include it.
- `needs_report`: promoted source exists, but no Stage173 report is available yet.
- `insufficient_evidence`: source promotion is weak or report support is insufficient.
- `blocked`: source promotion is blocked or failed at a host boundary.

Each report includes:

- `final_report_ready`
- `primary_source_url`
- `citation_quality_status`
- `citation_quality_score`
- `ordered_sources`
- `missing_requirements`
- `insufficient_evidence_report`
- `canonical_stop_reason`

## Runtime Integration

The reply API builds Stage197 after Stage195/196 and Stage173 report metadata are available. The result is propagated into:

- `ReplyPlan.debug` / reply debug metadata
- outgoing reply metadata
- archive metadata
- Stage153 event stream as `[report_assembly]`
- Stage191 public thought stream as report-assembly self-feedback
- Stage135 topology as `market_research_report_assembly`

## CLI Trace

The trace line is:

```text
[report_assembly] status=assembled ready=true citation=sufficient sources=1 stop=final_answer_ready url=https://...
```

If the promoted source is absent from citations:

```text
[report_assembly] status=citation_mismatch ready=false citation=missing_promoted_source sources=2 stop=evidence_exhausted url=https://...
```

## Boundaries

Stage197 is deterministic and read-only. It exposes auditable report assembly state, not hidden chain-of-thought or raw provider reasoning.
