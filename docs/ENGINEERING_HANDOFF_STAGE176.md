# Engineering Handoff Stage176

## Summary

Stage176 adds an adversarial market-research domain benchmark. It runs Stage175 live-smoke evaluation across primary and bad-evidence fixtures, then applies domain gates for primary-source authority, filing text presence, section coverage, metric consistency, period alignment, unsupported claims, and agent trace validity.

The key improvement is period-mismatch detection: a report may look `evidence_ready` to the lower-level report generator while still answering the wrong fiscal period. Stage176 blocks that condition explicitly.

## Files Changed

```text
holo_host/stage176_market_research_domain_benchmark.py
holo_host/cli.py
tests/test_stage176_market_research_domain_benchmark.py
docs/STAGE176_MARKET_RESEARCH_DOMAIN_BENCHMARK.md
docs/ENGINEERING_HANDOFF_STAGE176.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage176.market_research_domain_benchmark.v1
holo.stage176.market_research_domain_result.v1
holo.stage176.market_research_domain_scorecard.v1
```

## CLI

```powershell
python -m holo_host run-market-research-domain-bench --output artifacts\stage176\stage176_market_research_domain_benchmark.html --dry-run
```

## Adversarial Cases

```text
third_party_source_pollution -> source_authority_insufficient
missing_filing_section -> filing_checklist_incomplete
metric_conflict -> metric_conflict
period_mismatch -> period_mismatch
web_only_no_filing_text -> filing_text_missing
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage176_market_research_domain_benchmark.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage176-red
```

Result: failed because `holo_host.stage176_market_research_domain_benchmark` and the `run-market-research-domain-bench` CLI command did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage176_market_research_domain_benchmark.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage176-green1
```

Result: `10 passed`.

Targeted market stack:

```powershell
python -m pytest tests\test_stage176_market_research_domain_benchmark.py tests\test_stage175_market_research_live_smoke.py tests\test_stage174_market_research_report_action.py tests\test_stage173_market_research_report.py tests\test_stage169_market_research_pack.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage176-targeted
```

Result: `44 passed in 2.97s`.

Artifact smoke:

```powershell
python -m holo_host run-market-research-domain-bench --output artifacts\stage176\stage176_market_research_domain_benchmark.html --dry-run
```

Result: wrote `.html`, `.json`, and `.jsonl` artifacts under `artifacts\stage176`. Public artifact scan found no `reasoning_content`, `DEEPSEEK_API_KEY`, or `.holo_runtime` strings.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage176-runtime
```

Result: `92 passed in 20.05s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `843 passed in 97.87s`.

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

Stage177 should start turning these benchmark failures into live operator-facing research behaviors: targeted retrieval retries, source-period clarification, and explicit evidence insufficiency reports before any analyst conclusion.
