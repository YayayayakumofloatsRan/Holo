# Engineering Handoff Stage177

## Summary

Stage177 adds a deterministic remediation controller for market-research domain failures. It consumes Stage176 results and converts failed gates into concrete next actions such as primary-source retry, complete filing-text retrieval, period clarification/refetch, and metric-conflict reporting.

The practical change is that Holo no longer only detects bad market-research evidence. It can now report why a final answer is blocked and what evidence/action should happen next.

## Files Changed

```text
holo_host/stage177_market_research_remediation.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage177_market_research_remediation.py
docs/STAGE177_MARKET_RESEARCH_REMEDIATION.md
docs/ENGINEERING_HANDOFF_STAGE177.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage177.market_research_remediation.v1
holo.stage177.market_research_remediation_result.v1
holo.stage177.market_research_remediation_action.v1
holo.stage177.market_research_remediation_ledger.v1
```

## Runtime And CLI

```powershell
python -m holo_host run-market-research-remediation --output artifacts\stage177\stage177_market_research_remediation.html --dry-run
```

The command writes HTML, JSON, and JSONL artifacts and requires no provider or network.

Stage135 topology exposes a `market_research_remediation` node and compact metrics for remediation status and action count.

## Examples

```text
source_authority_insufficient -> retry_primary_source_search
filing_text_missing -> request_filing_text_or_open_primary_url
filing_checklist_incomplete -> retrieve_complete_filing_text
metric_conflict -> produce_metric_conflict_report
period_mismatch -> clarify_or_refetch_period
```

When a case is ready, Stage177 returns `can_finalize=true` and `recommended_stop_reason=final_answer_ready`.

When a case is unsafe, Stage177 returns `can_finalize=false`, an operator message, and at least one remediation action.

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage177_market_research_remediation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage177-red2
```

Result: `10 failed` because the Stage177 module and CLI command did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage177_market_research_remediation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage177-green2
```

Result: `10 passed`.

Targeted market stack:

```powershell
python -m pytest tests\test_stage177_market_research_remediation.py tests\test_stage176_market_research_domain_benchmark.py tests\test_stage175_market_research_live_smoke.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage177-targeted
```

Result: `28 passed in 3.12s`.

Artifact smoke:

```powershell
python -m holo_host run-market-research-remediation --output artifacts\stage177\stage177_market_research_remediation.html --dry-run
```

Result: wrote `.html`, `.json`, and `.jsonl` artifacts under `artifacts\stage177`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage177-runtime
```

Result: `92 passed in 19.81s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `853 passed in 95.83s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: public hygiene passed; `git diff --check` exited 0 with CRLF normalization warnings only.

## Constraints Preserved

- no provider model path outside processor fabric
- no network fetches in tests
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure

## Next Suggested Stage

Stage178 should generalize the remediation pattern into a domain-independent evidence/action repair controller so Holo can apply the same loop to literature review, math research, physics research, and GPU experiment management.
