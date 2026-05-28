# Stage229 Page Fetcher And Extraction Diagnostics

Kernel version remains `2.1.0`.

## Purpose

Stage228 proved that official-source discovery can return the right candidate
URL while `open_page` can still fail for site-specific reasons. Stage229 adds a
dedicated page fetcher and extraction layer so Holo can distinguish:

- provider/search failure
- URL fetch failure
- HTTP status failure such as 403
- successful fetch with low or high extraction quality
- successful open-page evidence ready for model synthesis

This keeps web research from collapsing into a vague "network is disconnected"
message.

## Runtime Changes

`PageFetcher` records:

- original URL and final URL
- HTTP status code
- content type
- bytes read
- elapsed time
- error type and message

`extract_page_text` records:

- title
- cleaned page text
- content type
- extraction quality

`OpenPageTool` now stores both reports in its observation ledger under:

```text
data.fetch
data.extracted_page
```

If a page fails, the final answer reports the attempted failure. For example:

```text
open_page was attempted but failed: HTTP Error 403: Forbidden
```

## Routing Fix

Explicit URL requests now route to `open_page` first in the offline fallback
path. After a successful explicit URL open, the agent finalizes from that
source instead of running an unrelated extra web search.

This is fallback behavior only. The target architecture remains model-first:
the model chooses actions, the host executes and ledgers them, and the host
repairs unsupported final claims.

## Live Smoke Results

WSL fetcher control:

```text
https://api-docs.deepseek.com/guides/function_calling -> 200, extracted
https://docs.python.org/3/library/asyncio.html -> 200, extracted
https://example.com/ -> 200, extracted
https://developers.openai.com/codex/cli -> 403 HTTPError
```

The OpenAI Codex CLI 403 is therefore site-specific under the current fetch
path, not a global WSL network outage.

Agent smoke:

```text
open https://docs.python.org/3/library/asyncio.html and summarize source
-> open_page ok
-> answer_direct
-> stop final_answer_ready
```

OpenAI Codex CLI smoke:

```text
open https://developers.openai.com/codex/cli and summarize source
-> open_page error
-> stop tool_failure_report
```

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage229_page_fetcher.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage229-targeted3
```

Result:

```text
6 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
70 passed
```
