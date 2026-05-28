# Stage233 Provider Timeout And Chat Goal Continuity

Kernel version remains `2.1.0`.

## Problem

The live CLI showed:

```text
上网查一下deepseek api key的用法
-> web_search status=error
-> provider_timeout

再试一次
-> answer_direct
```

There were two separate defects:

1. The DeepSeek API-key query did not map to an API-docs search goal, so
   `web_search` fell through to the legacy DuckDuckGo/Bing HTML provider path.
   That path can time out in WSL.
2. The interactive chat command did not preserve the failed web goal, so retry
   turns such as `再试一次`, `？？？`, or `我说去查一下` were treated as unrelated
   direct-answer turns.

## Fix

Stage233 does not make keyword rules choose tools. The model/fallback still
chooses `web_search`.

The fix is below the decision layer:

- `build_search_goal()` recognizes DeepSeek API-key usage as an `api_docs`
  source goal after the model has selected search.
- `SourcePolicyProvider` can return the official DeepSeek API docs home for
  API-key usage queries.
- `ChatSession` stores the last goal and failed stop reason. Retry/follow-up
  phrases inherit the previous failed goal before calling the agent.

This preserves the target architecture:

```text
model decides tool
host executes
provider policy selects source path
observation ledger proves result
chat session preserves goal continuity
```

## Live Result

WSL command:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run '上网查一下deepseek api key的用法' --trace --model fallback --max-steps 6"
```

Observed:

```text
[model_decide] selected=web_search
[observation] web_search status=ok
[model_decide] selected=open_page
[observation] open_page status=ok
[stop] final_answer_ready
```

Final source:

```text
https://api-docs.deepseek.com/
```

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage228_source_policy_provider.py::test_source_policy_provider_returns_deepseek_api_key_docs_candidate tests\test_stage233_chat_goal_continuity.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage233-green1
```

Result:

```text
4 passed
```

Neighbor:

```powershell
python -m pytest tests\test_stage228_source_policy_provider.py tests\test_stage233_chat_goal_continuity.py tests\test_stage227_web_provider_layer.py tests\test_stage232_model_self_feedback.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage233-neighbor
```

Result:

```text
24 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
93 passed
```
