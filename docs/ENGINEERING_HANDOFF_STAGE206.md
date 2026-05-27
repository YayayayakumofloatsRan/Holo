# Engineering Handoff Stage206

## Summary

Stage206 connects the bounded Stage186 live crawler into the real reply loop. The fix closes the gap where `holo_host chat --trace` could select `web_search` but keep using a prebuilt non-network capability context, causing Holo to say it would search without actually running the host crawler.

## Files Changed

- `holo_host/reply_api.py`
  - Reruns capability summarization with `eager_network=True` and `use_live_crawler=True` when Stage151 selects `web_search` in agent channels.
  - Replaces visible future-intent text with crawler-grounded source output or attempted-failure summaries.
  - Maps Stage186 crawler status to canonical stop reasons when no stronger stop source exists.
  - Passes `stage186_live_crawler_search` into Stage153 event stream payload.
- `holo_host/agent_event_stream.py`
  - Renders Stage186 crawler rows in the FSM event-stream path.
- `holo_host/stage151_live_tool_trace.py`
  - Treats explicit attempted web-search failure reports as grounded by failed/rejected web-tool ledgers instead of repairing them into generic missing-ledger text.
- `tests/test_stage206_live_crawler_reply_loop.py`
  - Adds reply API regression tests for successful crawler grounding and failed crawler reporting.

## Runtime Propagation

The real reply path now carries:

- `stage186_live_crawler_search`
- `web_observation_ledger`
- crawler-derived `tool_observation_ledger`
- Stage153 `[crawl:*]` events
- non-unknown `canonical_stop_reason`

## Examples

Successful source request:

```text
[crawl:query] ...
[crawl:open] status=ok url=https://developers.openai.com/codex/cli
[crawl:stop] status=sufficient reason=sufficient_evidence
[final] ... https://developers.openai.com/codex/cli
```

Failed source request:

```text
[crawl:search] status=error
[crawl:stop] status=failed reason=tool_failure_report
[final] I attempted web_search but did not obtain sufficient evidence: ...
```

## Constraints Preserved

- No hidden chain-of-thought exposure.
- No provider `reasoning_content` exposure.
- No WeChat start.
- No transport authority widening.
- No new unbounded loop.
- The crawler is bounded by Stage186 query/page budgets.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage206_live_crawler_reply_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage206-targeted
```

Result: pending final verification run in this thread.

Neighbor:

```powershell
python -m pytest tests\test_stage206_live_crawler_reply_loop.py tests\test_stage187_live_crawler_chat_integration.py tests\test_stage186_live_crawler_search.py tests\test_stage151_tool_decision_loop.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage206-neighbor
```

Result: `33 passed in 3.77s`.

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage206-runtime
```

Result: `92 passed in 14.75s`.

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `1022 passed in 133.62s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
```

Result: passed.

Diff check:

```powershell
git diff --check
```

Result: passed with CRLF normalization warnings only.

## Next Suggested Stage

Stage207 should make the interactive CLI display crawler and public thought stream with clearer visual separation between user text, system trace, observations, and final answer.
