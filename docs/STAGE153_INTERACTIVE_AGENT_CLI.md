# Stage153 Interactive Agent CLI

Date: 2026-05-27

## Purpose

Stage153 turns the Holo command-line chat surface into an inspectable agent console. Stage151 and Stage152 already produce tool decisions, web/time observations, native DeepSeek tool-loop metadata, and grounding reports. Stage153 renders those existing ledgers as concise, auditable event lines while preserving thread continuity.

## Schemas

```text
holo.stage153.agent_event_stream.v1
holo.stage153.interactive_cli_session.v1
```

## CLI Entry

```powershell
python -m holo_host chat --thread-key holo_cli:default --chat-name HoloCLI --channel holo_cli
```

The `chat` parser now defaults to `holo_cli:default`. Passing the same `--thread-key` keeps the same Holo subject thread.

## Event Stream

Each turn renders an event stream shaped like:

```text
[goal]
[context]
[candidate]
[tool_call]
[observation]
[grounding]
[cache]
[stop]
[final]
```

The stream is auditable external state only. It may show tool names, query strings, status, source counts, grounding status, cache hit/miss token counts, and final visible speech. It does not print raw DeepSeek `reasoning_content`, hidden chain-of-thought, or internal assistant messages.

When no tool runs, the stream explicitly says:

```text
[tool_call] no tool calls
```

## Slash Commands

```text
/trace       show last turn event stream
/json        print last turn JSON metadata with hidden reasoning redacted
/tools       show tool observations
/health      show live health
/memory      show recall trace for current topic or provided query
/compact     show compact status metadata only
/clear       clear screen only
/exit        exit session
```

Existing commands such as `/mind`, `/recall`, `/topology`, `/snapshot`, `/grant`, `/trace on|off`, and `/json on|off` remain available.

## Runtime Propagation

`reply_api.py` attaches `stage153_agent_event_stream` and `stage153_interactive_cli_session` to reply JSON, outgoing metadata, archive/observe metadata, and `ReplyPlan.debug`.

Stage135 topology adds a compact `agent_event_stream` node when Stage153 metadata is present.

## Boundaries

Stage153 does not:

- start WeChat
- widen transport authority
- add provider calls
- execute tools
- write memory beyond the existing reply/archive path
- expose raw DeepSeek `reasoning_content`
- weaken Stage149-152 grounding or directive repairs
