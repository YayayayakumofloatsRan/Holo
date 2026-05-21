# Provider Compatibility Contract

This document defines the processor provider abstraction.

The rule is:
- every model invocation must go through one provider contract
- new direct CLI or raw HTTP call sites are not allowed

## 1. Provider Interface

Every provider must implement one standard task entry:
- `run_task()`

It must return standardized:
- text/result payload
- timing
- usage payload
- model/provider metadata
- success/failure status

## 2. Supported Providers

### `DeepSeekProvider`

Role:
- default production path for live Holo speech

Use when:
- the task is text-only
- Holo is serving the phone app, WeChat, or another live conversation endpoint
- a direct DeepSeek key is available through `DEEPSEEK_API_KEY`

Transport:
- HTTP `chat/completions`
- model defaults: `deepseek-v4-pro` for main/kernel lanes, `deepseek-v4-flash` for fast lanes

### `OpenAICompatibleProvider`

Role:
- first configurable external fallback

Use when:
- a compatible HTTP backend is configured
- DeepSeek is unavailable or a different external backend should be tested

### `ResponsesProvider`

Role:
- optional OpenAI fallback

Use when:
- OpenAI Responses is explicitly configured and reachable

### `CodexCliProvider`

Role:
- optional development/operator fallback

Use when:
- task requires current Codex CLI behavior
- image inputs are present and CLI supports them
- shadow/operator flows depend on CLI semantics

Important:
- live Holo speech must not depend on `codex_cli`
- append it only through explicit lane config or `HOLO_ENABLE_CODEX_FALLBACK=1`

## 3. Fallback Order

Per lane:
1. primary provider
2. backup provider
3. compatible external fallback
4. `codex_cli` only when explicitly configured or enabled

Important:
- fallback may change provider
- fallback must not silently change task meaning
- fallback must still write usage and failure details
- fallback must not hide a broken live provider by blocking the conversation thread for minutes

## 4. Required Request Fields

`ProcessorTaskRequest` must support:
- `task_type`
- `prompt`
- `lane`
- `provider_hint`
- `reasoning_effort`
- `budget_tag`
- `image_paths`
- `workspace_mode`
- `operator_scope`
- `max_output_tokens`
- `metadata`

## 5. Required Result Fields

Every provider result must expose enough data to record:
- provider name
- model name
- reasoning effort
- duration
- usage
- fallback provider when used

## 6. Compatibility Rules

- watcher, reply, operator, and image understanding all go through the same abstraction
- providers may differ in capabilities
- unsupported requests must fail explicitly, not degrade silently
- image support can be lane/provider-specific, but unsupported image requests must surface clearly
- provider-native tool calling must go through the Stage106 adapter:
  - Holo exposes only allowlisted tool schemas
  - provider responses are parsed as proposed `tool_calls`
  - unknown tools and invalid argument payloads are rejected before execution
  - tool execution authority remains in the WSL brain, not in the provider

## 7. Configuration Surface

Use:
- `processor_fabric`
- `provider_backends`
- `processor_routing`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL` when overriding the default endpoint
- `OPENAI_COMPATIBLE_API_KEY` and `OPENAI_COMPATIBLE_BASE_URL` for non-DeepSeek compatible providers

Do not treat:
- `codex_model`
- `fast_model`
- `responses_model`

as the authoritative long-term routing surface; they are compatibility aliases.

## 8. Validation

Use these commands:
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host show-live-readiness`
- `python3 -m holo_host show-live-flow`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host accept-processor-fabric`

`show-live-readiness` is the operator-facing readiness gate for a long-running
Holo instance. It must report:
- active processor backend and speech dispatch chain
- DeepSeek primary-provider availability for live speech
- whether `codex_cli` is still in the live speech dependency chain
- vector memory readiness
- latest processor usage state, with recent processor errors retained as
  diagnostic evidence

The readiness probe may initialize the vector-memory client in the live process,
but it must not spend provider tokens or generate user-facing speech.

`show-live-flow` is the wider long-running diagnosis surface. It must keep the
single-subject topology visible across:
- subject continuity thread
- Windows transport state, when present
- reply API readiness
- processor-fabric usage ledger
- vector and stream memory
- core brain loops
- queued outbound work
- operator/self-maintenance status

Its job is not to replace `/live-readiness`. Readiness answers "can Holo speak
through the intended provider path now?" Flow answers "is the whole live
cognitive pipeline still moving?"

## 9. Forbidden Changes

- no direct raw HTTP call sites added outside provider classes
- no direct `codex exec` subprocesses added outside the runner/provider layer
- no hidden per-feature provider logic that bypasses usage accounting
- no live-reply path that makes Codex CLI the silent final fallback unless explicitly enabled
