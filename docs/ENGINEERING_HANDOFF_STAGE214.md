# Engineering Handoff Stage214

## Summary

Stage214 adds `holo.stage214.market_research_operator_run.v1`, an end-to-end market-research operator run that turns a research task into a public action trajectory and final filing-grounded report.

It reuses existing subsystems rather than creating a parallel path:

- Stage186 live crawler search
- Stage196 source promotion
- Stage169 market research pack
- Stage173 market research report
- Stage197 report assembly
- Stage198 finalization gate
- Stage212 action journal

The dry-run fixture forces a weak first source and then an official SEC source. Passing requires a complete pipeline, promoted authority evidence, a ready evidence pack, a finalized report, and a visible action journal.

## Files Changed

- Added `holo_host/market_research_operator_run.py`
- Added `tests/test_stage214_market_research_operator_run.py`
- Added `docs/STAGE214_MARKET_RESEARCH_OPERATOR_RUN.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE214.md`
- Updated `holo_host/cli.py`
- Updated `HOLO_HANDOFF.md`
- Updated `docs/ROADMAP_REGISTRY.md`

## Runtime Surface

```powershell
python -m holo_host run-market-research-operator-run --output artifacts\stage214\stage214_market_research_operator_run.html --dry-run
```

## Public Action Trajectory

```text
[plan]
[crawl]
[promote_source]
[build_pack]
[build_report]
[assemble_report]
[finalize]
[action_journal]
```

The generated HTML also embeds Stage212 rows:

```text
[action:1] web_search ...
[crawl:query]
[crawl:search]
[crawl:open]
[crawl:evaluate]
[crawl:stop]
[feedback]
```

These are public audit summaries, not hidden chain-of-thought.

## Constraints Preserved

- no provider calls by default
- no live network required by default
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure

## Verification

Initial targeted command:

```powershell
python -m pytest tests\test_stage214_market_research_operator_run.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage214-targeted
```

Current result:

```text
2 passed in 0.30s
```

Final verification:

```powershell
python -m holo_host run-market-research-operator-run --output artifacts\stage214\stage214_market_research_operator_run.html --dry-run
python -m pytest tests\test_stage214_market_research_operator_run.py tests\test_stage213_market_research_action_journal_smoke.py tests\test_stage212_action_journal.py tests\test_stage205_market_research_trajectory_live_smoke.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage214-neighbor
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage214-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results on `2026-05-28`:

- CLI artifact smoke: exited 0 and wrote `artifacts/stage214/stage214_market_research_operator_run.{html,json,jsonl}`
- targeted Stage214: `2 passed in 0.30s`
- neighbor Stage214/213/212/205 stack: `12 passed in 1.61s`
- runtime reply/topology: `92 passed in 15.52s`
- full regression: `1043 passed in 139.06s`
- public hygiene: passed
- `git diff --check`: passed with CRLF normalization warnings only

## Next Suggested Stage

Stage215 should connect this operator-run bundle to the interactive agent loop so `chat --trace` can choose a market-research operator action, execute it, and expose the same public phase trajectory without relying on a standalone smoke command.
