# Engineering Handoff Stage187

## Summary

Stage187 wires Stage186 live crawler search into the live chat capability path. Explicit search turns in `holo_cli` and adjacent agent channels now run a bounded crawler loop during capability context construction, then expose crawl events in the Stage153 CLI trace.

## Files Changed

```text
holo_host/capabilities.py
holo_host/reply_api.py
holo_host/agent_event_stream.py
tests/test_stage187_live_crawler_chat_integration.py
docs/STAGE187_LIVE_CHAT_CRAWLER_INTEGRATION.md
docs/ENGINEERING_HANDOFF_STAGE187.md
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## Runtime Propagation

```text
stage186_live_crawler_search
web_observation_ledger
tool_requests
tool_context_lines
stage153_agent_event_stream
stage135_i_state_topology
reply JSON
archive metadata
```

## Verification

Targeted red:

```powershell
python -m pytest tests\test_stage187_live_crawler_chat_integration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage187-red
```

Result:

```text
2 failed
KeyError: 'stage186_live_crawler_search'
```

Targeted green:

```powershell
python -m pytest tests\test_stage187_live_crawler_chat_integration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage187-green1
```

Result:

```text
2 passed in 0.84s
```

Final verification must be filled before release.

Neighbor verification:

```powershell
python -m pytest tests\test_stage187_live_crawler_chat_integration.py tests\test_stage186_live_crawler_search.py tests\test_stage185_cli_introspection_search.py tests\test_stage153_interactive_cli.py tests\test_stage151_tool_decision_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage187-neighbor
```

Result:

```text
37 passed in 5.42s
```

Runtime verification:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage187-runtime
```

Result:

```text
92 passed in 21.38s
```

Full verification:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
928 passed in 166.48s
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
Public release hygiene passed.
git diff --check completed with CRLF normalization warnings only.
```

## Compatibility Note

`CapabilityBroker.summarize_turn(..., eager_network=True)` still preserves the Stage151 single-shot `web_search` behavior by default. Stage187 enables the Stage186 bounded crawler only when the live reply path explicitly requests `use_live_crawler=True` for agent channels after Stage151 selects `web_search`.

## Constraints Preserved

```text
provider generation path widened: no
memory writes added: no
WeChat start: no
hidden reasoning exposed: no
unbounded crawler loop: no
```

## Next Suggested Stage

Stage188 should harden live web provider quality and retries under actual network conditions, including provider choice, page extraction robustness, and live source coverage metrics for financial/market-research workflows.
