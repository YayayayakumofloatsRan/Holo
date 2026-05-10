# Engineering Handoff: Stage40

Stage40 implements the bionic brain OS harness for internal CLI/API agent workflows. It turns the Stage29 bionic kernel into a bounded, inspectable engineering loop without starting WeChat or granting new autonomy.

## What Changed
- Added `holo_host/bionic_brain.py`.
- Added operational QueueStore tables for brain runs, steps, context bundles, and agent eval runs.
- Added DeepSeek V4 Flash/Pro harness profile metadata and safe thinking/tool-call downgrade logic.
- Added Stage40 CLI commands: `brain-run`, `brain-trace`, `show-context-bundle`, `show-brain-metrics`, `run-agent-eval`, and `accept-stage40`.
- Added HTTP mirrors for the same operational surfaces.
- Added tests for context compilation, brain loop gating, DeepSeek V4 profile selection, and agent eval determinism.

## Runtime Boundaries
- WeChat watcher remains off.
- Stage40 does not mutate self-memory, Mind Graph autobiographical state, policy sediment, or live transport state.
- Context bundles exclude private runtime and memory sources by default.
- Model calls stay inside the processor fabric. Offline mode is deterministic and does not call a provider.
- Tool actions must declare `mutation_class` and pass the action-market gate before execution.

## Operational Tables
- `context_bundles`: compiled long-context packages with source hashes, cache key, token estimate, sections, and excluded private sources.
- `bionic_brain_runs`: run-level goal, status, metrics, and full operational payload.
- `bionic_brain_steps`: per-step phase payloads and tool-gate visibility.
- `agent_eval_runs`: deterministic Stage40 scorecards and run payloads.

## CLI
```powershell
python -m holo_host --config .holo_host.toml brain-run --goal "inspect current repo state" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline
python -m holo_host --config .holo_host.toml brain-trace --trace-id 1
python -m holo_host --config .holo_host.toml show-context-bundle --bundle-id ctx_...
python -m holo_host --config .holo_host.toml show-brain-metrics --limit 20
python -m holo_host --config .holo_host.toml run-agent-eval --suite stage40
python -m holo_host --config .holo_host.toml accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli
```

## Validation
```powershell
pytest -q tests/test_stage40_context_compiler.py tests/test_stage40_bionic_brain_harness.py tests/test_stage40_deepseek_v4_profile.py tests/test_stage40_agent_eval.py
pytest -q
python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli
python -m holo_host --config .holo_host.toml accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli
python scripts/check_public_release_hygiene.py
git diff --check
```

Verified on `2026-05-10`: targeted Stage40 tests passed, `brain-run --offline` passed, `run-agent-eval --suite stage40` passed, `accept-stage39` passed with user-level `DEEPSEEK_API_KEY` loaded into the process environment, `accept-stage40` passed with the same environment, full `pytest -q` passed with `331` tests, public-release hygiene passed, and `git diff --check` reported no whitespace errors.

## Review Notes
- The implementation is deliberately operational-first. It creates a real harness and trace surface, but does not yet execute arbitrary shell/test actions from model proposals.
- `repo_write` remains denied by default. Future repo-writing agent work must explicitly enable that authority and keep the action-market gate visible.
- `pro_1m` context is represented as a budget class but not used by default.

## Next Work
Stage41 should focus on broad provider/API adapter compatibility and richer safe tool execution only after Stage40 validation remains green. Live WeChat transport remains a separate operator-approved plan.
