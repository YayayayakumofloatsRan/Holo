# Engineering Handoff Stage186

## Summary

Stage186 adds a bounded live crawler/search controller for Holo. It turns search intent into an auditable loop:

```text
query plan -> web_search -> open_page -> page evidence -> sufficiency evaluation -> stop
```

This stage addresses the live CLI failure where Holo could claim or plan web lookup without showing a concrete sequence of queries, opened pages, evidence scoring, and stop reason.

## Files Changed

```text
holo_host/live_crawler_search.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage186_live_crawler_search.py
docs/STAGE186_LIVE_CRAWLER_SEARCH.md
docs/ENGINEERING_HANDOFF_STAGE186.md
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## Runtime Surface

New CLI:

```powershell
python -m holo_host run-live-crawler-search --output artifacts\stage186\stage186_live_crawler_search.html --dry-run
```

Artifacts:

```text
.html
.json
.jsonl
```

## Public Trace Events

```text
[crawl:query]
[crawl:search]
[crawl:open]
[crawl:evaluate]
[crawl:stop]
[final]
```

The trace is public and auditable. It does not expose hidden chain-of-thought or raw provider reasoning.

## Verification

Targeted red:

```powershell
python -m pytest tests\test_stage186_live_crawler_search.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage186-red
```

Result:

```text
1 error: ModuleNotFoundError: No module named 'holo_host.live_crawler_search'
```

Final verification:

Targeted green:

```powershell
python -m pytest tests\test_stage186_live_crawler_search.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage186-green2
```

Result:

```text
8 passed in 1.11s
```

CLI dry-run:

```powershell
python -m holo_host run-live-crawler-search --output artifacts\stage186\stage186_live_crawler_search.html --dry-run
```

Result:

```text
status=sufficient
query_count=2
opened_page_count=2
source_urls=https://developers.openai.com/codex/cli
```

Neighbor:

```powershell
python -m pytest tests\test_stage186_live_crawler_search.py tests\test_stage184_real_use_agent_drill.py tests\test_stage151_tool_decision_loop.py tests\test_stage167_live_search_canary.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage186-neighbor
```

Result:

```text
38 passed in 36.82s
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage186-runtime
```

Result:

```text
92 passed in 20.28s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
926 passed in 142.81s (0:02:22)
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
git diff --check passed
```

## Constraints Preserved

```text
provider calls: no new provider generation path
memory writes: none
WeChat start: none
transport authority widened: no
hidden reasoning exposure: no
unbounded crawler loop: no
```

## Next Suggested Stage

Stage187 should connect Stage186 crawler evidence directly into the live chat path so `holo_cli --trace` can execute the crawler loop for explicit search tasks and render crawl events inline, not only in offline/drill commands.
