# Stage198 Market Research Finalization Gate

Stage198 converts the Stage197 report assembly boundary into live visible output.

Before this stage, Holo could prove whether a market-research report consumed the promoted authoritative source, but the final visible reply could still remain generic model text. Stage198 closes that gap: report-readiness now gates the final answer.

## Schema

- `holo.stage198.market_research_finalization_gate.v1`

## Inputs

Stage198 consumes:

- `stage197_market_research_report_assembly`
- the current candidate visible text

It does not call provider models, fetch the network, execute tools, write memory, start WeChat, or widen transport authority.

## Behavior

If Stage197 status is `assembled`:

- Stage198 builds a deterministic market-research final answer from the Stage173 report.
- The answer includes report status, key metrics, filing evidence, conclusion, recommendation status, and source URLs.
- `final_visible_text_ready=true`.

If Stage197 reports `citation_mismatch`:

- Stage198 replaces the candidate text with a bounded failure message.
- It says the promoted authoritative source is missing from report citations.
- It refuses to treat the report as final.

If Stage197 reports weak or insufficient evidence:

- Stage198 uses the Stage197 insufficient-evidence report.
- It keeps investment recommendation as `not_provided`.

## Runtime Integration

The reply API builds Stage198 after Stage197 and before final bubble creation. If Stage198 says `should_replace_visible_text=true`, the visible candidate is replaced before final delivery/archive.

Stage198 is propagated into:

- reply debug
- capability context
- outgoing metadata
- archive metadata
- Stage153 event stream as `[report_final]`
- Stage191 public thought stream as a finalization card
- Stage135 topology as `market_research_finalization`

## CLI Trace

Ready:

```text
[report_final] status=finalized ready=true replace=true citation=sufficient stop=final_answer_ready url=https://...
```

Citation mismatch:

```text
[report_final] status=blocked ready=false replace=true citation=missing_promoted_source stop=evidence_exhausted url=https://...
```

## Boundary

Stage198 exposes auditable finalization state, not hidden chain-of-thought. Raw provider reasoning remains private.
