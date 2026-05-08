# Stage29 Bionic Subject Kernel Implementation Plan

This plan was the initial Stage29 plan. It is superseded in naming and adapter boundary details by `docs/superpowers/plans/2026-05-08-stage29-unified-bionic-kernel.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Holo into a testable bionic subject kernel with a CLI adapter, bounded bionic turn-capsule workflow, DeepSeek V4 provider support, and inspectable explainability metrics.

**Architecture:** Stage29 adds an adapter-neutral bionic subject-kernel layer over the existing MemoryBridge, processor fabric, action-market, and Stage28 situational surfaces. The new layer does not add a second brain, does not start WeChat, and does not bypass action-market-first deliberation; it exposes one bounded perception-action capsule per adapter turn. DeepSeek support is a processor provider capability inside `CodexRunner`, not a raw model call from the agent workflow.

**Tech Stack:** Python stdlib, existing Holo `holo_host` modules, SQLite `QueueStore`, processor fabric, pytest, existing CLI argparse.

---

## Files

- Create `holo_host/bionic_agent.py`: bionic turn-capsule assembly, inhibition metrics, trace export payloads.
- Modify `holo_host/codex_runner.py`: add `DeepSeekProvider` and capability metadata; preserve existing provider contract.
- Modify `holo_host/config.py`: add DeepSeek config keys and provider aliases.
- Modify `holo_host/store.py`: persist Stage29 bionic traces operationally.
- Modify `holo_host/cli.py`: add `agent-run`, `agent-trace`, `show-bionic-metrics`, `export-bionic-trace`, `accept-stage29`.
- Modify `holo_host/reply_api.py`: expose local acceptance helper if needed without WeChat paths.
- Create `tests/test_stage29_bionic_cli_agent.py`: CLI capsule, metrics, trace, and acceptance tests.
- Extend `tests/test_processor_fabric.py`: DeepSeek provider config and mock execution.
- Add `docs/STAGE29_BIONIC_SUBJECT_KERNEL.md`.
- Add `docs/ENGINEERING_HANDOFF_STAGE29.md`.
- Update `HOLO_HANDOFF.md`, `.agent/PLANS.md`, `.agent/STAGE23_27_PROGRAM.md`, and `docs/ROADMAP_REGISTRY.md`.

## Task 1: DeepSeek Provider Contract

**Files:**
- Modify: `holo_host/config.py`
- Modify: `holo_host/codex_runner.py`
- Test: `tests/test_processor_fabric.py`

- [x] **Step 1: Write failing config/provider tests**

Add tests that verify:
- `processor_backend = "deepseek"` becomes a valid provider preference.
- `deepseek_base_url`, `deepseek_api_key_env`, `deepseek_model`, and `deepseek_fast_model` load from `[processor_fabric]`.
- `CodexRunner.provider_status()` includes `deepseek`.
- A mocked DeepSeek-compatible client call returns standardized `ProcessorTaskResult` metadata with provider, model, reasoning effort, usage, and capabilities.

- [x] **Step 2: Run red tests**

Run: `pytest -q tests/test_processor_fabric.py`
Expected: fails because `deepseek` is not configured or registered.

- [x] **Step 3: Implement minimal provider support**

Implementation rules:
- Add config fields to `ProcessorFabricConfig`.
- Treat DeepSeek as OpenAI-compatible chat-completions style endpoint using base URL `https://api.deepseek.com` by default.
- Default models: `deepseek-v4-pro` for main/kernel, `deepseek-v4-flash` for fast.
- Preserve no-image support unless explicitly extended later.
- Include capability metadata: text, json, tool_call_protocol, thinking_mode, image_support=false.

- [x] **Step 4: Run green tests**

Run: `pytest -q tests/test_processor_fabric.py`
Expected: pass.

## Task 2: Bionic Turn Capsule

**Files:**
- Create: `holo_host/bionic_agent.py`
- Test: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing capsule tests**

Tests must verify:
- A CLI turn creates a capsule with phases: `perception`, `working_field`, `attention`, `inhibition`, `action_market`, `generation`, `outcome`.
- The capsule consumes Stage28 `situational_field` when available.
- Inhibition is explicit and returns reasons for no recall, no tool, no send, and no history reread.
- The selected action remains action-market-first; generation is downstream.

- [x] **Step 2: Run red tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: fails because `holo_host.bionic_agent` does not exist.

- [x] **Step 3: Implement minimal capsule**

Implementation rules:
- Use dataclasses with `to_dict()` methods.
- Keep all state bounded and serializable.
- Do not mutate self-memory directly.
- Use deterministic fallback when no runner/model is available.
- Compute bionic metrics: `working_field_density`, `inhibition_count`, `grounding_modalities`, `history_reread_avoided`, `action_market_top_margin`, `template_pressure_score`.

- [x] **Step 4: Run green capsule tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: pass for capsule-only tests.

## Task 3: Operational Trace Persistence

**Files:**
- Modify: `holo_host/store.py`
- Modify: `holo_host/bionic_agent.py`
- Test: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing persistence tests**

Tests must verify:
- `QueueStore.initialize()` creates `bionic_agent_traces`.
- A bionic capsule can be recorded and listed.
- Latest metrics aggregate deterministically.
- Trace rows are operational storage, not Mind Graph/self-memory.

- [x] **Step 2: Run red tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: fails on missing store methods/table.

- [x] **Step 3: Implement storage methods**

Add:
- `record_bionic_agent_trace(...)`
- `list_bionic_agent_traces(...)`
- `latest_bionic_metrics(...)`

- [x] **Step 4: Run green persistence tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: pass.

## Task 4: CLI Surfaces

**Files:**
- Modify: `holo_host/cli.py`
- Test: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing CLI tests**

Tests must call CLI functions or subprocess entrypoints for:
- `agent-run --query ... --thread-key ...`
- `agent-trace --trace-id ...`
- `show-bionic-metrics`
- `export-bionic-trace --output ...`

- [x] **Step 2: Run red tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: fails on missing commands.

- [x] **Step 3: Implement CLI commands**

Rules:
- Commands use local process only by default.
- No WeChat transport call.
- JSON output must be deterministic and include `stage = "stage29-bionic-subject-kernel"`.
- `agent-run` records a trace unless `--no-record` is passed.

- [x] **Step 4: Run green CLI tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: pass.

## Task 5: Acceptance And Docs

**Files:**
- Modify: `holo_host/cli.py`
- Modify: `holo_host/reply_api.py`
- Create: `docs/STAGE29_BIONIC_SUBJECT_KERNEL.md`
- Create: `docs/ENGINEERING_HANDOFF_STAGE29.md`
- Modify: `HOLO_HANDOFF.md`
- Modify: `.agent/PLANS.md`
- Modify: `.agent/STAGE23_27_PROGRAM.md`
- Modify: `docs/ROADMAP_REGISTRY.md`
- Test: `tests/test_stage29_bionic_cli_agent.py`

- [x] **Step 1: Write failing acceptance test**

Test must verify `accept-stage29` checks:
- Stage28 remains available.
- DeepSeek provider is visible in provider status.
- A bionic subject-kernel turn through the CLI adapter produces a full capsule.
- Trace persistence works.
- Metrics are visible.
- No WeChat transport command is required.

- [x] **Step 2: Run red acceptance test**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py`
Expected: fails on missing `accept_stage29`.

- [x] **Step 3: Implement acceptance and docs**

Rules:
- Do not claim Stage29 starts Holo online.
- Document Stage29 as bionic subject-kernel substrate and workflow hardening.
- Preserve memory-is-self, processor-replaceable, transport-eyes-hands, action-market-first.

- [x] **Step 4: Run Stage29 acceptance**

Run: `python -m holo_host --config .holo_host.example.toml accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
Expected: JSON payload with `ok: true`.

## Task 6: Full Verification And Review

**Files:**
- All Stage29 changed files.

- [x] **Step 1: Targeted tests**

Run: `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py tests/test_stage28_multimodal_homeostatic_kernel.py`
Expected: pass.

- [x] **Step 2: Full test suite**

Run: `pytest -q`
Expected: pass.

- [x] **Step 3: Hygiene checks**

Run: `python scripts/check_public_release_hygiene.py`
Expected: pass.

- [x] **Step 4: Manual review**

Review:
- no direct provider call sites outside provider classes
- no WeChat transport dependency in Stage29 tests
- no new always-on loop
- no Mind Graph self-memory mutation from bionic trace storage
- all new docs consistent with roadmap and handoff

- [ ] **Step 5: Commit**

Commit message: `feat: unify stage29 bionic kernel`
