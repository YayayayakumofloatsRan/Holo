# Stage208 Agent Console Live Smoke

## Purpose

Stage208 verifies that the CLI-visible agent console is connected to the real reply path, not only to synthetic renderer fixtures.

The smoke runs a local `HoloReplyService` turn with a deterministic runner and a deterministic Stage186 crawler broker. The model-facing draft can say a future-intent phrase such as `I will search this now.`; the host path must still execute the crawler, record ledgers, repair the final answer into source-grounded text, and render the result through the Stage207 console.

## Schema

`holo.stage208.agent_console_live_smoke.v1`

Each result uses:

`holo.stage208.agent_console_live_smoke_result.v1`

The scorecard uses:

`holo.stage208.agent_console_scorecard.v1`

## CLI

```powershell
python -m holo_host run-agent-console-live-smoke --output artifacts\stage208\stage208_agent_console_live_smoke.html --dry-run
```

The command writes:

- `.html`
- `.json`
- `.jsonl`

## What It Proves

- The reply API can trigger Stage186 crawler execution from a normal `holo_cli` search request.
- Stage153 event streams contain `[crawl:query]`, `[crawl:open]`, `[crawl:evaluate]`, and `[crawl:stop]`.
- Stage207 renders the user input and final answer as ordinary text, with public system/action/thought rows visually separated.
- Successful search output includes a source URL in the final visible answer.
- Failed search output reports the attempted failure instead of saying the search still needs to happen.
- New turns must have a non-`unknown` canonical stop reason.
- Public artifacts and JSON do not expose provider `reasoning_content`, hidden chain-of-thought, raw provider messages, or scratchpads.

## Boundary

Stage208 does not start WeChat, does not add provider calls, does not add memory writes beyond the local smoke stub, and does not widen transport authority. It is an observability and integration smoke over the existing Stage206/207 path.
