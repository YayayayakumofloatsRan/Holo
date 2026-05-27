# Engineering Handoff Stage173

## Summary

Stage173 adds a deterministic market-research report generator. It consumes Stage169-172 evidence packs and produces filing-grounded analyst-style reports with citations, section/metric coverage, unsupported-claim accounting, limitations, and a weak web-only baseline comparison.

## Files Changed

```text
holo_host/stage173_market_research_report.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage173_market_research_report.py
docs/STAGE173_MARKET_RESEARCH_REPORT.md
docs/ENGINEERING_HANDOFF_STAGE173.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage173.market_research_report.v1
holo.stage173.market_research_report_bundle.v1
holo.stage173.market_research_baseline_comparison.v1
```

## Runtime And Artifact Surface

Stage173 exposes:

```text
stage173_market_research_report
market_research_report_node_count
market_research_report_status
market_research_report_section_count
market_research_report_metric_count
market_research_report_citation_count
```

CLI artifact command:

```powershell
python -m holo_host run-market-research-report --output artifacts\stage173\stage173_market_research_report.html --dry-run
```

## Examples

Ready report:

```text
status=evidence_ready; sections=4; metrics>=2; citations>=1
```

Insufficient report:

```text
status=evidence_insufficient; unsupported_claims includes source_authority_insufficient
```

Weak baseline comparison:

```text
verdict=full_stack_stronger
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage173_market_research_report.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage173-red
```

Result: failed because `holo_host.stage173_market_research_report`, CLI command, and topology node did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage173_market_research_report.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage173-green1
```

Result: `8 passed`.

Market stack regression:

```powershell
python -m pytest tests\test_stage173_market_research_report.py tests\test_stage172_filing_text_retrieval.py tests\test_stage171_market_research_action.py tests\test_stage170_market_research_gate.py tests\test_stage169_market_research_pack.py tests\test_stage168_source_authority.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage173-market-stack
```

Result: `54 passed in 2.16s`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage173-runtime
```

Result: `92 passed in 21.82s`.

CLI artifact smoke:

```powershell
python -m holo_host run-market-research-report --output artifacts\stage173\stage173_market_research_report.html --dry-run
```

Result: passed and wrote `.html`, `.json`, and `.jsonl` artifacts with `report_count=2`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `817 passed in 108.51s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: public hygiene passed; `git diff --check` exited 0 with CRLF normalization warnings only.

## Constraints Preserved

- no provider model path outside processor fabric
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no live network requirement for tests

## Next Suggested Stage

Stage174 should connect the report generator to an evidence-backed market-research workflow that can run over a real company query, carry forward source/failure status, and benchmark whether Holo can complete a useful filing-grounded research task end to end.
