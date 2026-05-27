# Stage187 Live Chat Crawler Integration

Stage187 connects the Stage186 crawler loop back into the live chat capability path.

Stage186 proved the bounded crawler as a standalone drill. Stage187 makes explicit web-search turns in agent channels use that crawler instead of stopping at a planned or single-shot lookup surface.

## Behavior

For `holo_cli`, `engineering`, `research`, and `project` channels, when Stage151 selects `web_search`, the reply service rebuilds capability context with eager web execution. `CapabilityBroker` then runs:

```text
Stage186 query/open/evaluate crawler
```

The crawler path is explicit. The default Stage151 capability call still returns a normal single-shot `web_search` observation; live chat integration opts into the crawler with `use_live_crawler=True`.

The result is propagated as:

```text
stage186_live_crawler_search
web_observation_ledger
tool_requests
tool_context_lines
stage153_agent_event_stream
stage135_i_state_topology
reply/archive metadata
```

## CLI Trace

The Stage153 event stream now renders Stage186 crawler events:

```text
[crawl:query]
[crawl:search]
[crawl:open]
[crawl:evaluate]
[crawl:stop]
```

This is intended for command-line auditability. It does not expose hidden chain-of-thought or raw provider reasoning.

## Boundary

Stage187 does not start WeChat, does not write memory, does not add a new provider generation path, and does not create an unbounded crawler. Network-disabled mode remains an observable boundary with rejected web observations.
