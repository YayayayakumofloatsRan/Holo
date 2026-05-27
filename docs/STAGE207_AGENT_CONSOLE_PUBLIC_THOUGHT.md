# Stage207 Agent Console Public Thought

## Purpose

Stage207 makes the live CLI easier to use as an agent console. Earlier stages produced valid event streams and public thought cards, but `chat --trace` still printed the trace as a flat block where the final answer was just another `[final]` line. That made it hard to distinguish user text, auditable system state, tool observations, self-feedback, and the final answer.

Stage207 adds a dedicated console renderer for interactive Holo turns.

## Schema

`holo.stage207.agent_console.v1`

The report records:

- whether user text is present,
- number of rendered system lines,
- whether final text is present,
- whether Stage191 public thought cards were used,
- `hidden_reasoning_exposed=false`.

## CLI Behavior

When automatic trace output is enabled, `holo_host chat` now renders a turn as:

```text
holo> <user input>
[goal] ...
[model_decide] ...
[crawl:query] ...
[crawl:open] ...
[crawl:stop] ...
[thought:...] ...
<final visible answer>
```

On a TTY, system lines use ANSI faint styling. User input and final answer are left as ordinary text. In non-TTY captures, the same line structure is emitted without color codes.

`/trace` still shows the raw Stage153 event stream. `/thoughts` still shows Stage191 public thought cards. `/console` now shows the combined Stage207 console view for the last turn.

## Boundary

Stage207 does not expose raw hidden chain-of-thought, provider `reasoning_content`, raw provider messages, hidden prompts, or scratchpads. It renders only sanitized public event and thought streams built from ledgers and stop-state metadata.

## Acceptance

Stage207 is accepted when:

- user input and final reply render as ordinary text,
- system/action/thought rows are visually separated,
- crawler and self-feedback rows remain visible,
- no hidden reasoning appears in console or JSON output,
- existing `/trace`, `/thoughts`, `/json`, and tool views continue to work.
