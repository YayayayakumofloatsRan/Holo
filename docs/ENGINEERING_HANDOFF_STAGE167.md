# Engineering Handoff Stage167

## Summary

Stage167 adds live-search canary evaluation over the Stage151-166 evidence chain. It compares provider observations, extracts source freshness markers, selects clean supporting quotes, checks ambiguous-entity disambiguation, and writes public-safe HTML/JSON/JSONL artifacts.

Stage167 is evaluation and observability only. It does not add provider model calls, memory writes, WeChat starts, transport authority widening, hidden reasoning exposure, or a new tool authority path.

## Files Changed

```text
holo_host/stage167_live_search_canary.py
tests/test_stage167_live_search_canary.py
holo_host/cli.py
docs/STAGE167_LIVE_SEARCH_CANARY.md
docs/ENGINEERING_HANDOFF_STAGE167.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage167.live_search_canary.v1
holo.stage167.provider_comparison.v1
holo.stage167.source_freshness.v1
holo.stage167.quote_extraction.v1
```

## Runtime Surface

New CLI:

```powershell
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary.html --dry-run
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary_live.html --mode live-smoke
```

Artifacts:

```text
.html
.json
.jsonl
```

## Examples

Provider comparison:

- official provider with supported source synthesis outranks weak unrelated provider output.
- provider timeout is recorded as a failed provider while a supported provider can still pass.

Freshness:

- SEC URL `aapl-20240928.htm` yields `2024-09-28` plus `2024` markers.
- current/latest claims without date or year markers are marked missing.

Quote extraction:

- page/CSS chrome is stripped before selecting a bounded supporting quote.

Ambiguity:

- `search apple` must disambiguate company versus fruit when the fixture requires it.

## Test Commands And Results

Initial targeted TDD red:

```powershell
python -m pytest tests\test_stage167_live_search_canary.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage167-red
```

Result: `10 failed` before implementation because the module and CLI command did not exist.

Targeted after implementation:

```powershell
python -m pytest tests\test_stage167_live_search_canary.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage167-targeted
```

Result: `10 passed`.

Search-stack regression:

```powershell
python -m pytest tests\test_stage167_live_search_canary.py tests\test_stage166_search_quality_eval.py tests\test_stage165_answer_citation_formatter.py tests\test_stage164_search_fallback_synthesis.py tests\test_stage163_page_evidence_verifier.py tests\test_stage151_tool_decision_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage167-search-stack
```

Result: `58 passed`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage167-runtime
```

Result: `91 passed`.

CLI dry-run:

```powershell
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary.html --dry-run
```

Result: passed with `canary_count=4`, `pass_rate=1.0`, `provider_support_score=1.0`, and `quote_quality_score=1.0`.

CLI live-smoke:

```powershell
python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary_live.html --mode live-smoke
```

Result: passed against the current web path for `OpenAI Codex CLI official docs` with `provider_support_score=1.0`, `freshness_score=1.0`, `quote_quality_score=1.0`, and no failed fixtures.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `762 passed`.

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
- no public runtime memory artifacts

## Next Suggested Stage

Provider abstraction and source-fetch robustness for first-party docs, filings, and market-research sources. This should remain ledgers-first and should not introduce unsupported final claims.
