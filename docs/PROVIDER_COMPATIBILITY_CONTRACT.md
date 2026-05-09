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

### `CodexCliProvider`

Role:
- primary production path

Use when:
- task requires current Codex CLI behavior
- image inputs are present and CLI supports them
- shadow/operator flows depend on CLI semantics

### `ResponsesProvider`

Role:
- first fallback

Use when:
- Codex CLI is unavailable or failing
- task is compatible with OpenAI Responses semantics

### `OpenAICompatibleProvider`

Role:
- second fallback through the common chat-completions protocol

Use when:
- a compatible HTTP backend is configured
- previous providers are unavailable

Limits:
- text/json requests only
- image support is false until an image-capable provider contract is added
- do not use the first-party Responses API for this generic compatibility path

### `DeepSeekProvider`

Role:
- low-cost text provider option exposed through the same processor fabric

Use when:
- `processor_backend = "deepseek"` is configured
- a DeepSeek-compatible chat-completions endpoint and API key are available

Limits:
- text/json requests only
- image support is false until an image-capable provider contract is added

## 3. Fallback Order

Per lane:
1. primary provider
2. backup provider
3. `openai_compatible`
4. final compatibility fallback only if configured in code

Important:
- fallback may change provider
- fallback must not silently change task meaning
- fallback must still write usage and failure details

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

## 7. Configuration Surface

Use:
- `processor_fabric`
- `provider_backends`
- `processor_routing`

DeepSeek keys:
- `processor_fabric.deepseek_base_url`
- `processor_fabric.deepseek_api_key_env`
- `processor_fabric.deepseek_model`
- `processor_fabric.deepseek_fast_model`

Do not treat:
- `codex_model`
- `fast_model`
- `responses_model`

as the authoritative long-term routing surface; they are compatibility aliases.

## 8. Validation

Use these commands:
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host show-provider-contracts`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host accept-processor-fabric`
- `python3 -m holo_host accept-stage33`

## 9. Forbidden Changes

- no direct raw HTTP call sites added outside provider classes
- no direct `codex exec` subprocesses added outside the runner/provider layer
- no hidden per-feature provider logic that bypasses usage accounting
