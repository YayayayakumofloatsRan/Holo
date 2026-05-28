# Stage212 Persistent Action Journal

Stage212 adds a bounded, CLI-readable action journal over persisted reply metadata.

## Purpose

Holo's tool loop must be inspectable after the fact. Stage210/211 answer a narrow question: "what did you just search?" Stage212 generalizes this into a journal that Holo and the operator can inspect across recent turns.

## Schema

```text
holo.stage212.action_journal.v1
```

## Sources

Stage212 reads only public/sanitized metadata already present in outbound message rows:

- `stage186_live_crawler_search`
- `crawler_ledger`
- `web_observation_ledger`
- `tool_observation_ledger`
- `stage190_self_feedback_loop`

It does not call a provider, execute tools, write memory, start WeChat, or expose hidden reasoning.

## CLI

Persisted same-thread journal:

```powershell
python -m holo_host action-journal --thread-key holo_cli:default --chat-name HoloCLI --channel holo_cli --limit 8
```

JSON:

```powershell
python -m holo_host action-journal --thread-key holo_cli:default --json
```

Inside interactive chat:

```text
/actions
```

The interactive form renders the current turn's action journal from the last reply payload. The standalone command reads persisted `QueueStore` history.

## Rendered Rows

The text renderer emits command-line friendly rows:

```text
[journal]
[action:N]
[source]
[crawl:query]
[crawl:search]
[crawl:open]
[crawl:evaluate]
[crawl:stop]
[feedback]
```

These rows are public audit summaries, not private chain-of-thought.

## Boundary

Stage212 is observational. It makes the existing search/tool loop easier to inspect, which is required before policy calibration or autonomous long-running research can be trusted.
