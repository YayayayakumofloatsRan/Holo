# Stage29 Bionic Subject Kernel

## What Stage29 Adds
- A unified, transport-agnostic bionic subject kernel that runs one bounded turn capsule at a time.
- A CLI adapter surface that exercises the same kernel without starting WeChat.
- A processor-fabric DeepSeek provider adapter for OpenAI-compatible chat-completions style text tasks.
- Operational trace persistence for bionic capsules in `QueueStore`, not Mind Graph or self-memory.
- Inspectable bionic workflow metrics for working-field density, inhibition, grounding modalities, history-reread avoidance, action-market margin, and template pressure.

## Bounded Capsule
Each kernel turn exposes these ordered phases:
- `perception`
- `working_field`
- `attention`
- `inhibition`
- `action_market`
- `generation`
- `outcome`

The capsule is intentionally operational. It can be stored, exported, and reviewed, but it does not become autobiographical memory and does not mutate policy sediment.

The capsule records the adapter boundary explicitly:
- `kernel = "bionic_subject_kernel"`
- `adapter = "cli"`, `wechat`, or another external interface name
- `interface_contract.transport_is_interface = true`
- `interface_contract.transport_decision_authority = false`
- `interface_contract.wechat_transport_used = false` for Stage29 local probes

Action-market candidates are clipped to a bounded review payload before they enter traces. Large nested policy, calibration, or prediction objects remain in their owning diagnostic surfaces.

If the selected action is not a speech action, generation is skipped and the capsule records `action_no_generation`.

## Kernel Modules
The public import surface remains `holo_host.bionic_agent`, but Stage29 internals are split under `holo_host/bionic_kernel_parts/`:
- `contracts.py`: request, phase, capsule dataclasses and Stage29 constants
- `normalization.py`: canonical thread identity and adapter context hardening
- `bounded_payload.py`: bounded trace-safe payload clipping
- `generation.py`: downstream generation through deterministic fallback or processor fabric
- `metrics.py`: operational bionic explainability metrics
- `pipeline.py`: ordered phase assembly

This keeps CLI, synthetic WeChat, and future adapters on one shared subject kernel without turning the facade into a second monolith.

## DeepSeek Provider
DeepSeek support lives inside `holo_host.codex_runner.DeepSeekProvider`.

Configuration keys:
- `processor_backend = "deepseek"`
- `processor_fabric.deepseek_base_url`
- `processor_fabric.deepseek_api_key_env`
- `processor_fabric.deepseek_model`
- `processor_fabric.deepseek_fast_model`

Default models:
- main lanes: `deepseek-v4-pro`
- fast lane: `deepseek-v4-flash`

The provider currently supports text/json chat-completions style requests. Image support is explicitly false until a visual-capable provider contract is added and tested.

## Adapter Surfaces
- `python -m holo_host agent-run --query "..." --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python -m holo_host agent-trace --trace-id <id>`
- `python -m holo_host show-bionic-metrics`
- `python -m holo_host export-bionic-trace --trace-id <id> --output artifacts/stage29/trace.json`
- `python -m holo_host accept-stage29 --thread-key cli:TestUser --chat-name TestUser --channel cli`

`agent-run` is a CLI adapter over the bionic kernel. It records a trace by default. Use `--no-record` for inspection-only local probes.

`accept-stage29` also runs a synthetic WeChat adapter request through the same kernel. This proves the abstraction without starting the live watcher or sending a transport message.

## Safety Boundaries
- No WeChat transport command is required.
- No live watcher is started.
- No new always-on loop is added.
- No second brain or planner is introduced.
- CLI, WeChat, and future HTTP surfaces are adapters only.
- Adapters do not select actions or bypass send policy.
- Generation remains downstream of action-market selection.
- DeepSeek calls are only allowed through the processor provider fabric.
- Trace rows are operational evidence, not self-memory.

## Validation
- `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py tests/test_stage28_multimodal_homeostatic_kernel.py`
- `pytest -q`
- `python -m holo_host --config .holo_host.example.toml accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- `python scripts/check_public_release_hygiene.py`
