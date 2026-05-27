# Stage177 Market Research Remediation

Stage177 converts Stage176 market-research domain failures into deterministic operator-facing remediation plans.

The purpose is to close a key agent-loop gap: a benchmark failure should not stop at scoring. Holo must be able to say which evidence is missing, what action should run next, why a final report cannot be delivered yet, and what success condition would make the answer safe.

## Scope

Stage177 is deterministic and offline by default. It reads Stage176 domain results and emits:

- `risk_flags`
- `remediation_actions`
- `operator_message`
- `can_finalize`
- `recommended_stop_reason`
- `requires_user_input`
- `authority_boundary`

It does not call providers, fetch the network, write memory, start WeChat, or widen transport authority.

## Schemas

```text
holo.stage177.market_research_remediation.v1
holo.stage177.market_research_remediation_result.v1
holo.stage177.market_research_remediation_action.v1
holo.stage177.market_research_remediation_ledger.v1
```

## Risk To Action Mapping

```text
source_authority_insufficient
  -> retry_primary_source_search
  -> required tool: web_search
  -> target evidence: primary SEC filing URL and source authority classification

filing_text_missing
  -> request_filing_text_or_open_primary_url
  -> required tool: open_page
  -> target evidence: raw filing text and section anchors

filing_checklist_incomplete
  -> retrieve_complete_filing_text
  -> required tool: find_in_page
  -> target evidence: complete 10-K checklist coverage

metric_conflict
  -> produce_metric_conflict_report
  -> required tool: market_research_report
  -> target evidence: conflict rows, source snippets, and resolution status

period_mismatch
  -> clarify_or_refetch_period
  -> required tool: web_search
  -> target evidence: requested-period filing and period-aligned metrics
```

## CLI

```powershell
python -m holo_host run-market-research-remediation --output artifacts\stage177\stage177_market_research_remediation.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Agent-Kernel Significance

Stage177 is deliberately small, but the pattern is general. It turns failed evidence into action-ready remediation. The same cognitive move is needed for literature review, math research, physics research, and GPU experiments:

```text
observe failure -> classify risk -> select next evidence/action -> define success condition -> refuse premature finalization
```

That is the reusable cognition/behavior loop, not a market-research-only feature.
