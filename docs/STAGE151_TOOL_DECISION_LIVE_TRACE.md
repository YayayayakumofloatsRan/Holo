# Stage151 Tool Decision Loop And Live Trace

Date: 2026-05-26

## Purpose

Stage151 upgrades Holo from keyword-style `external_lookup` into a deterministic host-side tool decision loop. Each turn now builds auditable evidence before visible speech: purpose, action candidates, selected web actions, observations, grounding result, and final answer trace.

This stage is designed to make CLI behavior closer to Codex-style tool use. The user should be able to see whether Holo decided to search, what it searched or opened, what source URLs came back, whether the final answer was grounded, and why a current web claim was blocked.

## Schemas

```text
holo.stage151.tool_decision.v1
holo.stage151.live_trace.v1
holo.web_observation.v1
holo.time_observation.v1
```

The previous `holo.stage151.live_tool_trace.v1` and `holo.stage151.network_grounding.v1` remain as compatibility surfaces for older tests and metadata consumers.

## Runtime Behavior

- Every turn receives a `time_observation` from the host clock.
- `build_tool_decision_report()` scores deterministic action candidates:
  - `answer_direct`
  - `memory_recall`
  - `web_search`
  - `open_page`
  - `find_in_page`
  - `ask_clarification`
  - `defer`
  - `engineering_tool_hint`
- Current, latest, official, search, URL, and page-find turns select host web actions before provider speech.
- Network access still respects `config.runtime.network_enabled`.
- If network is disabled, Stage151 records `rejected_network_disabled` and does not fetch.
- If network is enabled, Stage151 records normalized `web_observation_ledger` rows with query, URL, status, provider, result snippets, source URLs, fetch time, error, and confidence.
- Web observations are converted into `tool_observation_ledger` rows so Stage139 grounding can still police visible tool claims.
- Stage150 receives time/web observation summaries in the structured context packet.
- Stage135 exposes a minimal `stage151_tool_decision_loop` topology node.

## Grounding

Visible speech cannot claim live web/current knowledge unless matching evidence exists:

- "I searched"
- "latest"
- "official"
- "as of today"
- "official website"
- Chinese equivalents such as "联网", "搜索", "最新", "官方", "官网"

If no successful web observation exists, Stage151 repairs the visible text into a bounded statement. It does not expose internal debug labels to users.

Generic references to local `docs` or project documentation are not treated as web claims by themselves; this prevents Stage151 from hijacking Stage139 workspace/tool grounding.

## CLI

```bash
python3 -m holo_host chat --trace --no-local-fallback
```

Inside chat:

```text
/trace on
/trace off
```

Trace lines use only auditable external decisions:

```text
[purpose] gather_web_evidence
[candidate] web_search score=0.86 need=web_observation_ledger
[tool_call] web_search query=openai codex docs
[observation] web_search status=ok results=3 source=https://developers.openai.com/codex/cli
[grounding] status=grounded missing=-
[final] ...
```

The trace does not print hidden chain-of-thought or provider-internal reasoning.

## Boundaries

Stage151 does not add provider call paths outside processor fabric. It does not add memory writes, approval/sandbox logic, durable policy mutation, transport authority, WeChat startup, or a second loop. Host web actions are capability preprocessing and are recorded as ledgers before being passed into the existing reply pipeline.
