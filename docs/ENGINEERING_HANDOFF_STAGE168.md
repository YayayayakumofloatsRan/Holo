# Engineering Handoff Stage168

## Summary

Stage168 adds source-authority classification and audit reporting. It lets Holo distinguish primary filings, company IR pages, official docs/API docs, code/package sources, news, and low-authority third-party summaries.

Stage168 is designed for the market-research arc: a financial/filing task should require filing or first-party company disclosure evidence, not merely any cited page.

## Files Changed

```text
holo_host/stage168_source_authority.py
tests/test_stage168_source_authority.py
holo_host/stage151_tool_decision_loop.py
holo_host/cli.py
docs/STAGE168_SOURCE_AUTHORITY.md
docs/ENGINEERING_HANDOFF_STAGE168.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage168.source_authority.v1
holo.stage168.source_authority_report.v1
holo.stage168.source_authority_audit.v1
```

## Runtime Propagation

`web_search` observations now receive a `source_authority` block after:

```text
search_evidence
page_evidence
source_synthesis
```

The chain is:

```text
web_search -> Stage162 search sufficiency -> Stage163 page evidence -> Stage164 source synthesis -> Stage168 source authority
```

## CLI

```powershell
python -m holo_host run-source-authority-audit --output artifacts\stage168\stage168_source_authority.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

## Examples

Supported:

- SEC EDGAR filing URL for Apple 2024 10-K: `financial_filing`, `primary`, `regulatory_filing`.
- Apple investor relations URL: `company_ir`, `primary`, `company_disclosure`.
- OpenAI developer docs URL: `official_docs`, `official`, `vendor_documentation`.
- DeepSeek API docs URL: `api_docs`, `official`, `vendor_api_reference`.

Insufficient:

- A random third-party blog summary for a financial-filing task is marked `insufficient` with `missing_required_source_family:financial_filing`.
- GitHub/npm sources are useful for engineering/package tasks but are not enough for financial filing authority.

## Test Commands And Results

Initial TDD red:

```powershell
python -m pytest tests\test_stage168_source_authority.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage168-red
```

Result: `10 failed` before implementation because the Stage168 module, CLI command, and Stage151 source-authority attachment were missing.

Targeted after implementation:

```powershell
python -m pytest tests\test_stage168_source_authority.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage168-targeted
```

Result: `10 passed`.

Search-stack regression:

```powershell
python -m pytest tests\test_stage168_source_authority.py tests\test_stage167_live_search_canary.py tests\test_stage166_search_quality_eval.py tests\test_stage165_answer_citation_formatter.py tests\test_stage164_search_fallback_synthesis.py tests\test_stage163_page_evidence_verifier.py tests\test_stage151_tool_decision_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage168-search-stack
```

Result: `68 passed`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage168-runtime
```

Result: `91 passed`.

CLI source-authority audit:

```powershell
python -m holo_host run-source-authority-audit --output artifacts\stage168\stage168_source_authority.html --dry-run
```

Result: passed with `audit_count=4`, `pass_rate=1.0`, `sufficient_authority_rate=0.75`, `primary_source_total=2`, and `first_party_source_total=3`.

Stage167 live-smoke compatibility:

```powershell
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary_live.html --mode live-smoke
```

Result: passed with `provider_support_score=1.0`, `freshness_score=1.0`, and `quote_quality_score=1.0`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `772 passed`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: hygiene passed; `git diff --check` passed with CRLF normalization warnings only.

## Constraints Preserved

- no provider model path outside processor fabric
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no new tool authority path

## Next Suggested Stage

Use Stage168 as the base for a market-research source pack: ticker/entity normalization, filing checklist coverage, financial statement/risk/MD&A section extraction, and multi-source consistency checks.
