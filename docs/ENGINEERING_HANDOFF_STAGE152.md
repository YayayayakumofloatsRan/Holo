# Engineering Handoff Stage152

## Summary

Stage152 adds a DeepSeek-native thinking-mode tool loop. Live DeepSeek reply packets can now expose `time_observe`, `web_search`, `open_page`, `find_in_page`, and `memory_recall` schemas, execute those tools through Holo host authority, append `role=tool` results, and continue until no more tool calls or host budgets stop the loop.

The CLI trace now prefers Stage152 when available and shows `purpose`, `candidate`, `tool`, `observation`, `evaluate`, `stop`, and `final` lines without exposing raw `reasoning_content`.

## Files Changed

- `holo_host/stage152_deepseek_tool_loop.py`
- `tests/test_stage152_deepseek_tool_loop.py`
- `holo_host/codex_runner.py`
- `holo_host/processors.py`
- `holo_host/reply_api.py`
- `holo_host/cli.py`
- `holo_host/stage135_i_state_topology.py`
- `docs/STAGE152_DEEPSEEK_NATIVE_TOOL_LOOP.md`
- `docs/ENGINEERING_HANDOFF_STAGE152.md`
- `docs/ROADMAP_REGISTRY.md`
- `HOLO_HANDOFF.md`

## Runtime Propagation

- `DeepSeekProvider` uses Stage152 native tools when `stage152_native_tool_loop=true`.
- `CodexCliProcessor` sets that flag for the live reply deep packet.
- Stage152 observations are merged into reply-side web/time/tool ledgers before grounding repair.
- If a successful web observation exists but the visible draft still says lookup is unverified or omits requested sources, Holo now rewrites that visible draft from the recorded observation ledger instead of telling the user no lookup happened.
- Reply JSON, outgoing metadata, and archive metadata include:
  - `stage152_deepseek_tool_loop`
  - `stage152_live_trace`
  - `stage152_tool_call_count`
  - `stage152_round_count`
  - `stage152_stop_reason`
- Stage135 topology includes a `deepseek_native_tool_loop` node when Stage152 evidence is present.

## Constraints Preserved

- No WeChat start.
- No transport widening.
- No durable memory mutation from Stage152.
- No hidden reasoning leakage in CLI trace or public metadata.
- Network-disabled web tools return `rejected_network_disabled`.
- Stage106/113 legacy tool loop remains compatible for existing tests.

## Examples

Grounded web result:

```text
[tool] web_search id=call_web status=accepted query=OpenAI Codex CLI docs
[observation] web_search status=ok results=1 sources=https://developers.openai.com/codex/cli
[evaluate] status=grounded missing=-
```

Network disabled:

```text
[tool] web_search id=call_web status=accepted query=OpenAI Codex CLI docs
[observation] web_search status=rejected_network_disabled results=0
[evaluate] status=ungrounded_web_claim missing=web_observation
```

## Verification

Targeted:

```text
python -m pytest tests\test_stage152_deepseek_tool_loop.py tests\test_stage151_tool_decision_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage152-webfix-targeted
21 passed in 3.41s
```

Full regression and hygiene should be recorded below by the completing thread:

```text
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
598 passed in 82.91s (0:01:22)

python scripts\check_public_release_hygiene.py
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.

git diff --check
passed; only Git line-ending warnings were printed
```
