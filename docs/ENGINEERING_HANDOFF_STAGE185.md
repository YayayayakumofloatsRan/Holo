# Engineering Handoff Stage185

## Summary

Stage185 fixes live CLI issues observed in manual testing:

```text
[stop] unknown
stage state not visible
Chinese 检索/search intent falling through to answer_direct
planned web lookup not shown when eager network is disabled
no command-line friendly public internal flow
```

It adds deterministic public introspection lines to Stage153 rendering and hardens Chinese web/search intent detection in Stage151 and `CapabilityBroker`.

## Files Changed

```text
holo_host/agent_event_stream.py
holo_host/stage151_tool_decision_loop.py
holo_host/capabilities.py
tests/test_stage185_cli_introspection_search.py
docs/STAGE185_CLI_INTROSPECTION_AND_SEARCH_INTENT.md
docs/ENGINEERING_HANDOFF_STAGE185.md
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## Behavior

CLI trace now includes:

```text
[state] milestone=stage184-real-use-agent-drill source=HOLO_HANDOFF.md
[think] intent: purpose=...
[think] evidence: required=...
[think] action: selected=...
[think] stop_check: grounding=...
```

The `[think]` lines are public summaries from existing ledgers and metadata. They do not contain hidden provider reasoning.

Chinese search terms added:

```text
联网 外网 上网 网页 网站 检索 搜索 搜一下 查一下 查找 爬虫 抓取 最新 新闻 官方 官网 主页 文档 论文 资料 财报 年报
```

Non-eager network mode now records planned `web_search`/`open_page`/`find_in_page` tool requests from Stage151 selected actions instead of falling back to legacy `external_lookup` only.

## Verification

Targeted red:

```powershell
python -m pytest tests\test_stage185_cli_introspection_search.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage185-red
```

Result:

```text
6 failed
```

Targeted green:

```powershell
python -m pytest tests\test_stage185_cli_introspection_search.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage185-green1
```

Result:

```text
6 passed in 0.28s
```

Neighbor:

```powershell
python -m pytest tests\test_stage185_cli_introspection_search.py tests\test_stage153_interactive_cli.py tests\test_stage151_tool_decision_loop.py tests\test_stage184_real_use_agent_drill.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage185-neighbor
```

First neighbor run exposed one stale assertion after the handoff milestone moved from Stage184 to Stage185. The corrected run was:

```powershell
python -m pytest tests\test_stage185_cli_introspection_search.py tests\test_stage153_interactive_cli.py tests\test_stage151_tool_decision_loop.py tests\test_stage184_real_use_agent_drill.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage185-neighbor2
```

Result:

```text
35 passed in 33.43s
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage185-runtime
```

Result:

```text
92 passed in 23.54s
```

Final verification:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
918 passed in 194.98s (0:03:14)
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
git diff --check passed
```

## Constraints Preserved

```text
provider calls: none added
memory writes: none added
WeChat start: none
transport authority widened: no
hidden reasoning exposure: no
live network required for tests: no
```

## Next Suggested Stage

Stage186 should focus on live crawler/search maturity: real optional network drills, query logs, page extraction quality, source freshness, retry/fallback reporting, and market-research pack quality under actual web conditions.
