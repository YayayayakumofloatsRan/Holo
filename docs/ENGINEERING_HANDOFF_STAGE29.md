# Stage29 Engineering Handoff

## Status
Stage29 adds a unified bionic subject kernel, a CLI adapter over that kernel, and DeepSeek provider compatibility. It is not an online Holo restart stage and does not exercise live WeChat transport.

## Code Surfaces
- `holo_host/bionic_agent.py`
  - exposes `BionicKernel` and `BionicTurnRequest`
  - keeps `BionicAgent` as a compatibility wrapper
  - records or exports operational traces
- `holo_host/bionic_kernel_parts/`
  - `contracts.py` defines the Stage29 public capsule/request dataclasses and constants
  - `normalization.py` canonicalizes adapter requests and protects kernel-owned identity fields
  - `bounded_payload.py` clips sidecar, action-market, and processor metadata before trace export
  - `generation.py` keeps generation downstream of selected action and inside processor fabric
  - `metrics.py` computes bionic explainability metrics
  - `pipeline.py` assembles perception, working-field, attention, inhibition, action-market, generation, and outcome phases
- `holo_host/codex_runner.py`
  - registers `DeepSeekProvider`
  - keeps DeepSeek inside the processor-provider abstraction
- `holo_host/store.py`
  - adds `bionic_agent_traces`
  - exposes trace listing and metric aggregation
- `holo_host/cli.py`
  - adds `agent-run`, `agent-trace`, `show-bionic-metrics`, `export-bionic-trace`, and `accept-stage29`

## Acceptance Contract
`accept-stage29` checks:
- Stage28 situational field remains visible to the capsule
- DeepSeek appears in provider status
- `kernel = "bionic_subject_kernel"` is visible
- adapter provenance is visible in capsules and persisted traces
- a synthetic WeChat adapter request uses the same kernel without starting WeChat
- transports are interface-only and have no decision authority
- all seven bionic phases are present
- trace persistence works
- metrics are visible
- WeChat transport is not required

## Review Notes
- Bionic traces stay in QueueStore operational storage.
- The bionic subject kernel is the shared surface; CLI, synthetic WeChat, and future HTTP paths are adapters.
- `holo_host/bionic_agent.py` is intentionally a thin facade; new Stage29 internals should usually land under `holo_host/bionic_kernel_parts/`.
- The capsule can use deterministic fallback generation when no runner is supplied.
- The CLI path does not start watcher, daemon, or background stream work.
- Provider calls remain replaceable because DeepSeek is a `ProcessorProvider`, not a raw hot-path call.
- Action-market candidates are bounded before trace export; large nested policy or prediction payloads stay out of the capsule.
- Non-speech actions such as `silence` do not invoke generation.
- Sidecar failures are visible as `heuristic_fallback` with an inspectable error class.

## Known Minimal Implementations
- Deterministic fallback generation has been improved by Stage32 response shaping, but it remains a bounded offline fallback rather than a substitute for configured provider-backed generation.
- Bionic metrics are first-pass operational indicators; they are useful for regression and review, not a calibrated cognitive score.
- Stage34 adds visual-readiness checks and prevents image-capability overclaiming, but real visual-provider hardening still requires configured image-capable lanes and explicit live soak.
- Stage29 does not start Holo online and does not validate the live WeChat watcher path.

## Next Debt To Pay
- Calibrate `template_pressure_score`, working-field density, and inhibition quality against real CLI transcripts.
- Add real visual-provider soak before claiming deployed image-capable API compatibility.
- Split Stage29 adapter helpers out of the already-large `holo_host/cli.py` once the command surface stabilizes.

## Validation Commands
- `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_processor_fabric.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- `python scripts/check_public_release_hygiene.py`
