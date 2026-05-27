# Engineering Handoff Stage175

## Summary

Stage175 adds a provider-free live-smoke harness for the market-research agent path. It proves that the market-research workflow can move through model-proposed native tool calls, host tool execution, report ledgers, FSM stop validation, CLI-style event traces, and Stage135 topology without treating weak third-party evidence as a successful research result.

## Files Changed

```text
holo_host/stage175_market_research_live_smoke.py
holo_host/cli.py
tests/test_stage175_market_research_live_smoke.py
docs/STAGE175_MARKET_RESEARCH_LIVE_SMOKE.md
docs/ENGINEERING_HANDOFF_STAGE175.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage175.market_research_live_smoke.v1
holo.stage175.market_research_live_smoke_result.v1
holo.stage175.codex_style_market_research_scorecard.v1
```

## Runtime Surfaces Exercised

```text
Stage152 DeepSeek native tool loop
Stage174 market_research_report host action
Stage173 filing-grounded market research report
Stage160R agent-loop FSM
Stage153 event stream
Stage135 topology
Stage159 public metadata sanitization
```

## Examples

Ready SEC-like fixture:

```text
[model_decide] selected=market_research_report
[act] market_research_report status=executed
[observe] market_research_report status=ok observations=1 sources=1 citations=1
[stop] final_answer_ready
```

Weak third-party fixture:

```text
status=failed
failure=report_not_evidence_ready
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage175_market_research_live_smoke.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage175-red
```

Result: failed because `holo_host.stage175_market_research_live_smoke` and the `run-market-research-live-smoke` CLI command did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage175_market_research_live_smoke.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage175-green2
```

Result: `8 passed`.

Targeted market stack:

```powershell
python -m pytest tests\test_stage175_market_research_live_smoke.py tests\test_stage174_market_research_report_action.py tests\test_stage173_market_research_report.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage175-targeted2
```

Result: `24 passed in 1.43s`.

Artifact smoke:

```powershell
python -m holo_host run-market-research-live-smoke --output artifacts\stage175\stage175_market_research_live_smoke.html --dry-run
```

Result: wrote `.html`, `.json`, and `.jsonl` artifacts under `artifacts\stage175`; bundle status is `failed` by design because the weak third-party fixture must fail while the SEC-like fixture passes.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage175-runtime
```

Result: `92 passed in 22.07s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `833 passed in 99.82s`.

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
- no live network requirement for tests
- no hidden reasoning exposure

## Next Suggested Stage

Stage176 should convert the live-smoke evidence into a broader market-research domain benchmark with adversarial evidence cases, source freshness drift, and report-quality comparisons against a simple web-only baseline.
