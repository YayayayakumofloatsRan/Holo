# Engineering Handoff Stage209

## Summary

Stage209 adds `holo.stage209.agent_console_search_loop_smoke.v1`, an artifact-producing smoke that proves the live reply path can continue a search loop after weak evidence and render that loop truthfully in the agent console.

The deterministic fixture forces:

1. broad first query returns a weak third-party Codex overview
2. official/docs follow-up query returns the OpenAI Codex CLI documentation
3. Stage186 crawler continues until sufficient evidence
4. Stage153/Stage207 console renders the actual web/crawler action instead of misreporting `answer_direct`

## Files Changed

- Added `holo_host/agent_console_search_loop_smoke.py`
- Added `tests/test_stage209_agent_console_search_loop.py`
- Added `docs/STAGE209_AGENT_CONSOLE_SEARCH_LOOP_SMOKE.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE209.md`
- Updated `holo_host/agent_console_live_smoke.py`
- Updated `holo_host/agent_event_stream.py`
- Updated `holo_host/cli.py`
- Updated `HOLO_HANDOFF.md`
- Updated `docs/ROADMAP_REGISTRY.md`

## Public Trace Rule

Stage209 does not expose hidden chain-of-thought or DeepSeek `reasoning_content`. It exposes public, auditable state:

- model/action selection summary
- crawler queries
- search observations
- opened pages
- evidence evaluation
- stop reason
- final grounded answer

## CLI

```powershell
python -m holo_host run-agent-console-search-loop-smoke --output artifacts\stage209\stage209_agent_console_search_loop_smoke.html --dry-run
```

## Verification

```powershell
python -m pytest tests\test_stage209_agent_console_search_loop.py tests\test_stage208_agent_console_live_smoke.py tests\test_stage207_agent_console_renderer.py tests\test_stage186_live_crawler_search.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage209-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage209-runtime
python -m pytest tests\test_stage151_tool_decision_loop.py tests\test_stage163_page_evidence_verifier.py tests\test_stage165_answer_citation_formatter.py tests\test_stage206_live_crawler_reply_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage209-web-grounding
python -m holo_host run-agent-console-search-loop-smoke --output artifacts\stage209\stage209_agent_console_search_loop_smoke.html --dry-run
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results on `2026-05-28`:

- targeted Stage209/208/207/186: `16 passed in 2.75s`
- runtime reply/topology: `92 passed in 15.98s`
- web-grounding neighbor stack: `32 passed in 4.27s`
- CLI artifact smoke: passed and wrote `artifacts\stage209\stage209_agent_console_search_loop_smoke.html`, `.json`, and `.jsonl`
- full regression: `1030 passed in 138.59s`
- public hygiene: passed
- `git diff --check`: passed with CRLF normalization warnings only

## Constraints Preserved

- no hidden reasoning exposure
- no provider path outside the processor/reply fabric
- no memory writes
- no WeChat start
- no watcher or transport authority widening
- no public promotion of weak source evidence

## Next Suggested Stage

Stage210 should move from smoke verification to live CLI search-loop remediation: when a user asks what was searched, Holo should answer directly from the last web/crawler observation ledger instead of reconstructing from model memory.
