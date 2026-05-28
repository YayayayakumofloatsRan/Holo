# Stage228 Source Policy Provider

Kernel version remains `2.1.0`.

## Purpose

Stage227 made provider attempts bounded and observable. Stage228 adds a
source-policy provider so official documentation tasks do not depend entirely
on generic search pages such as DuckDuckGo or Bing HTML.

This is still part of the provider layer. It does not restore keyword routing
as the agent brain. The model selects `web_search`; the host enriches the
search action with `SearchPlan` domain policy; the provider registry chooses
providers.

## Added Provider

`SourcePolicyProvider` returns known official-source candidates when the active
source policy matches:

- OpenAI Codex CLI docs:
  `https://developers.openai.com/codex/cli`
- DeepSeek tool/function calling docs:
  `https://api-docs.deepseek.com/guides/function_calling`

The provider is first in the default provider order:

```text
source_policy -> legacy_html
```

## Runtime Effect

For an official Codex CLI docs request, WSL now reaches:

```text
web_search status=ok
open_page status=error
stop=tool_failure_report
```

This means the search stage no longer hangs or returns unrelated generic
search results. The remaining blocker is page fetching/extraction, where the
target site currently returns HTTP 403 under the WSL fetch path.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage228_source_policy_provider.py -q
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage228-full2
```

Result:

```text
61 passed
```

WSL smoke:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run 'Find official OpenAI Codex CLI docs and cite sources' --trace --model fallback --max-steps 6 --log .holo_kernel/stage228-wsl-source-policy2.jsonl"
```

Result:

```text
open_page was attempted but failed: HTTP Error 403: Forbidden
```

This is a correct bounded failure. Stage229 should harden page fetching and
extraction.
