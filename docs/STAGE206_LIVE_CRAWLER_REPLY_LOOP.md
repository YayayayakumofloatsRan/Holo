# Stage206 Live Crawler Reply Loop

## Purpose

Stage206 connects the Stage186 bounded live crawler to the real `HoloReplyService` chat/reply path. The previous crawler stack could produce good artifacts, but a `holo_host chat --trace` turn could still stop at a planned lookup or a provider sentence such as "I will search this now." That was not an agent loop.

Stage206 makes web/search turns in `holo_cli`, `engineering`, `research`, and `project` channels execute the host crawler when Stage151 selects `web_search`, even when an earlier non-network capability context was prebuilt.

## Runtime Behavior

- If Stage151 selects `web_search` in an agent channel, reply API reruns `CapabilityBroker.summarize_turn(..., eager_network=True, use_live_crawler=True)`.
- Stage186 crawler output is propagated into `stage186_live_crawler_search`, `web_observation_ledger`, sidecar metadata, reply JSON, archive metadata, and Stage153 event stream.
- Successful crawler runs replace future-intent text with citation-style grounded source output.
- Failed crawler runs replace future-intent text with an attempted-failure report from the crawler ledger.
- The Stage153 trace renders crawler rows as `[crawl:query]`, `[crawl:search]`, `[crawl:open]`, `[crawl:evaluate]`, and `[crawl:stop]`.
- Canonical stop reason is no longer `unknown` when the crawler determines success, tool failure, or network boundary.

## Public Reasoning Boundary

Stage206 does not expose hidden chain-of-thought or provider `reasoning_content`. It exposes the auditable external action stream: selected web action, crawler query/open/evaluate rows, observation status, stop reason, and final grounded answer.

## Acceptance

Stage206 is accepted when a real `HoloReplyService.handle_reply(...)` search turn:

- runs Stage186 crawler instead of only planning a lookup,
- returns URLs from `web_observation_ledger` in visible text when sources are requested,
- reports attempted crawler failure without future-intent wording,
- renders crawler events in the CLI event stream,
- avoids `unknown` canonical stop reason for new crawler turns.
