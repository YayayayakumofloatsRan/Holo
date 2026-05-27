# Engineering Handoff Stage169

## Summary

Stage169 adds a deterministic market-research evidence pack for filing-driven analysis. It builds on Stage168 source authority and adds entity normalization, filing section extraction, filing checklist coverage, financial metric extraction, metric consistency checks, and public-safe bundle artifacts.

This is a foundation for long-running financial/market-research work. It does not yet make the agent loop autonomously fetch and analyze filings; it creates the evidence structure that later stages can require before final financial analysis.

## Files Changed

```text
holo_host/stage169_market_research_pack.py
tests/test_stage169_market_research_pack.py
holo_host/cli.py
docs/STAGE169_MARKET_RESEARCH_PACK.md
docs/ENGINEERING_HANDOFF_STAGE169.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage169.market_entity.v1
holo.stage169.filing_sections.v1
holo.stage169.filing_checklist.v1
holo.stage169.financial_metrics.v1
holo.stage169.metric_consistency.v1
holo.stage169.market_research_pack.v1
holo.stage169.market_research_pack_bundle.v1
```

## Runtime Surface

New CLI:

```powershell
python -m holo_host run-market-research-pack --output artifacts\stage169\stage169_market_research_pack.html --dry-run
```

Artifacts:

```text
.html
.json
.jsonl
```

## Capabilities

- resolves seed market entities such as Apple/AAPL/CIK
- extracts 10-K sections: Business, Risk Factors, MD&A, Financial Statements
- checks required filing section coverage
- extracts simple financial metrics from filing prose
- detects conflicting metric values across sources
- gates pack readiness on Stage168 source authority

## Test Commands And Results

Initial TDD red:

```powershell
python -m pytest tests\test_stage169_market_research_pack.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage169-red
```

Result: `10 failed` before implementation because the Stage169 module and CLI command did not exist.

Targeted after implementation:

```powershell
python -m pytest tests\test_stage169_market_research_pack.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage169-targeted
```

Result: `10 passed`.

Research-stack regression:

```powershell
python -m pytest tests\test_stage169_market_research_pack.py tests\test_stage168_source_authority.py tests\test_stage167_live_search_canary.py tests\test_stage166_search_quality_eval.py tests\test_stage165_answer_citation_formatter.py tests\test_stage164_search_fallback_synthesis.py tests\test_stage163_page_evidence_verifier.py tests\test_stage151_tool_decision_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage169-research-stack
```

Result: `78 passed in 6.09s`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage169-runtime
```

Result: `91 passed in 9.51s`.

CLI artifact dry-run:

```powershell
python -m holo_host run-market-research-pack --output artifacts\stage169\stage169_market_research_pack.html --dry-run
```

Result: passed with `pack_count=2`; wrote `.html`, `.json`, and `.jsonl` artifacts under `artifacts\stage169`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `782 passed in 98.49s`.

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
- no new live tool authority path

## Next Suggested Stage

Stage170 should connect the market-research pack to the model-first agent loop. Market-research final answers should require source-authority-sufficient packs and cite pack evidence items before making financial claims.
