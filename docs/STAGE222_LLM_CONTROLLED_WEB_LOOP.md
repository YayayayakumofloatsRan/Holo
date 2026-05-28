# Stage222 LLM-Controlled Web Loop

Stage222 records a web-loop architecture correction for Holo Agent Kernel
`2.1.0`.

## Correction

The search backend is not the agent.

Search engines such as Bing or DuckDuckGo only provide candidate links. They
must not decide:

- what the user really needs
- which query should be tried next
- which page should be opened
- whether a page is enough evidence
- whether research should stop

Those are semantic workflow decisions. They belong to the model.

## Runtime Loop

The preferred web workflow is now:

```text
model_decide -> web_search -> observation
model_decide -> open_page -> observation
model_decide -> answer_direct | web_search | open_page | ask_clarification
```

The host records every tool call and observation. The model sees those
observations on the next decision pass.

## Host Responsibilities

The host still does deterministic work where deterministic work is appropriate:

- normalize result URLs
- filter obvious search-engine navigation pages
- enforce step budgets
- record JSONL event logs
- block unknown tools
- report failed tools honestly
- sanitize public metadata

These are framework constraints, not a replacement for semantic reasoning.

## Legacy Compatibility

`web_research` remains as a compatibility tool and deterministic fixture helper.
It is not part of the default tool registry. The default action space exposes
lower-level tools so the model can control the workflow:

- `time_observe`
- `web_search`
- `open_page`
- `workspace_search`

## Verification

Stage222 adds tests proving:

- a successful `web_search` returns to the model instead of host-stopping
- the model can choose `web_search -> open_page -> answer_direct`
- fallback no longer repeats identical failed web actions
- search engine navigation pages are filtered before model evaluation
