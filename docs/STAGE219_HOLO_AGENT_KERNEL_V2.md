# Stage219 Holo Agent Kernel v2

Stage219 starts a new Holo agent base in a separate directory:

```text
D:\Holo\holo-agent-kernel
```

It intentionally does not live under the legacy `D:\Holo\holo` runtime. The
legacy system can later become an adapter source, but this kernel is the new
tool-first engineering and research substrate.

Important naming rule:

- The kernel has its own product version, starting at `2.1.0`.
- Stage numbers are documentation and research iteration records only.
- The package and directory names must not include stage numbers.

## Kernel Shape

The loop is:

```text
observe -> model_decide -> tool_call -> observation -> evaluate -> stop/final
```

The model proposes the next action. The host executes tools and records
observations. The final answer is grounded in those observations.

## Current Tools

- `time_observe`
- `web_search`
- `open_page`
- `web_research`
- `workspace_search`

`web_research` is a bounded continuous search/open/evaluate tool. It searches
query variants, opens candidate pages, scores support against the user goal,
and returns sources plus an action trajectory.

## Event Log

Every run writes JSONL events under:

```text
.holo_kernel/events.jsonl
```

Events are public and auditable. Private reasoning keys such as
`reasoning_content` and `chain_of_thought` are sanitized.

## CLI

```powershell
python -m holo_agent run "search official OpenAI Codex CLI docs and cite sources" --trace
python -m holo_agent chat --trace
```

## Boundaries

- No WeChat/social/persona prompt in the kernel.
- No hidden reasoning exposure.
- No arbitrary shell execution.
- No memory mutation yet.
- DeepSeek is optional through `--model`; offline fallback is explicit.

## Stage220 Direction

Stage220 should replace the offline fallback with a production DeepSeek
tool-arbitration loop and make `web_research` the default action for research,
market, literature, and current-source tasks.
