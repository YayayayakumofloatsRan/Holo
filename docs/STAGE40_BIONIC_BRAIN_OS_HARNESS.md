# Stage40: Bionic Brain OS Harness

Stage40 upgrades the Stage29 bionic capsule into a bounded CLI/API agent harness. The model is treated as replaceable compute inside an operating-system-like loop: perception, working field, context compilation, deliberation, action-market gating, tool execution, verification, and consolidation intent.

This stage is not a WeChat rollout. It does not start the watcher, widen transport authority, mutate self-memory, create a second brain, or add an unbounded always-on loop.

## Implemented Surfaces
- `holo_host/bionic_brain.py` adds `BionicBrainHarness`, `ContextCompiler`, DeepSeek V4 harness profiles, Stage40 agent eval, and Stage40 acceptance payloads.
- `QueueStore` persists operational-only `context_bundles`, `bionic_brain_runs`, `bionic_brain_steps`, and `agent_eval_runs`.
- CLI commands:
  - `brain-run --goal ... --thread-key ... [--offline] [--max-steps N]`
  - `brain-trace --trace-id ...`
  - `show-context-bundle --bundle-id ...`
  - `show-brain-metrics --limit ...`
  - `run-agent-eval --suite stage40`
  - `accept-stage40`
- HTTP mirrors:
  - `POST /brain-run`
  - `GET /brain-trace?trace_id=...`
  - `GET /context-bundle?bundle_id=...`
  - `GET /brain-metrics`
  - `POST /agent-eval`
  - `POST /accept-stage40`
- `show-provider-status` now exposes `stage40_deepseek_v4` readiness metadata.

## Brain Loop Contract
Each Stage40 run records this phase order:

1. `perception`
2. `working_field`
3. `context_compiler`
4. `deliberation`
5. `action_market`
6. `tool_loop`
7. `verification`
8. `consolidation_intent`

The harness may propose tool actions, but every action must pass the action-market gate first. `read_only` and bounded operational `cache_write` actions are allowed by default. `repo_write` requires explicit user authority and `runtime_write` is blocked by default.

## Context Compiler
`ContextCompiler` creates inspectable `context_bundle` records with:

- `bundle_id`
- `model_profile`
- `token_estimate`
- `source_hashes`
- `sections`
- `cache_key`
- `excluded_private_sources`

Default private exclusions include `.holo_runtime/`, private memory JSONL, subject local files, API keys, and transport receipts. Bundles are operational artifacts only; they are not self-memory.

Budgets are:

- `flash_8k`
- `pro_128k`
- `pro_1m`

`pro_1m` is marked explicit-deep-run only and must not become the default path.

## DeepSeek V4 Profile
Stage40 defines two harness profiles:

- `deepseek_v4_flash`: fast classification, summarization, triage, and low-cost self-check.
- `deepseek_v4_pro`: planning, review, failure attribution, and acceptance.

Thinking mode is reserved for planning and review. If thinking mode plus tool calls is requested but the provider cannot preserve `reasoning_content`, the harness downgrades to a non-thinking external tool loop.

## Agent Eval
`run-agent-eval --suite stage40` emits a deterministic operational scorecard:

- `task_success`
- `tool_efficiency`
- `context_grounding`
- `verification_quality`
- `cost_per_success`
- `mechanism_leakage`
- `private_data_leakage`

Eval results are stored in `agent_eval_runs`; they never write Mind Graph self-memory.

## Stop Rules
- Stop if a Stage40 path starts WeChat or sends through transport.
- Stop if any model output can execute tools without action-market gating.
- Stop if `repo_write` or `runtime_write` is allowed without explicit operator authority.
- Stop if context bundles include private memory, subject local files, runtime DBs, transport receipts, or API keys.
- Stop if agent eval or consolidation writes self-memory or policy state.

## Rollback
Disable Stage40 CLI/API commands from operator workflows and fall back to Stage39 bionic kernel surfaces:

- `agent-run`
- `agent-trace`
- `show-bionic-metrics`
- `show-bionic-turing-scorecard`
- `accept-stage39`

Operational Stage40 tables can remain present because they do not affect runtime subject state.

## Verified
Verified on `2026-05-10`:

- `pytest -q tests/test_stage40_context_compiler.py tests/test_stage40_bionic_brain_harness.py tests/test_stage40_deepseek_v4_profile.py tests/test_stage40_agent_eval.py` passed.
- `python -m holo_host --config .holo_host.toml brain-run --goal "stage40 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2` passed.
- `python -m holo_host --config .holo_host.toml run-agent-eval --suite stage40` passed.
- `python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with the user-level `DEEPSEEK_API_KEY` loaded into the process environment.
- `python -m holo_host --config .holo_host.toml accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with the user-level `DEEPSEEK_API_KEY` loaded into the process environment.
- `pytest -q` passed with `331` tests.
- `python scripts/check_public_release_hygiene.py` passed.
- `git diff --check` reported no whitespace errors.
