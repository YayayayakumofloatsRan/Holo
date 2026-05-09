# Stage35: Internal Runtime Readiness

Stage35 closes the immediate operational debt left after wiring DeepSeek locally: Holo can now prove that the internal CLI/API runtime is configured, secret-safe, and WeChat-quiescent before anyone treats it as runnable.

This stage does not add subject features, widen autonomy, start WeChat, mutate self-memory, or perform a live model call during acceptance.

## Implemented Surfaces
- `holo_host.runtime_readiness.scan_config_for_secret_material(...)` rejects provider-secret-like keys embedded in local config files.
- `holo_host.runtime_readiness.deepseek_lane_readiness(...)` verifies `kernel_xhigh`, `subject_main`, and `micro_fast` are all driven by DeepSeek primary lanes.
- `holo_host.runtime_readiness.deepseek_env_readiness(...)` verifies the configured env var exists while only returning redacted key status.
- `holo_host.runtime_readiness.wechat_transport_quiescence(...)` verifies the configured runtime state has not started the WeChat helper or queued sends.
- `show-internal-runtime-readiness` and `/internal-runtime-readiness` expose the readiness report.
- `accept-stage35` and `/accept-stage35` require Stage34 plus internal runtime readiness.

## Readiness Contract
- DeepSeek stays a replaceable processor-fabric provider, not a raw hot-path call.
- API keys live in environment variables, not `.toml`, docs, runtime artifacts, or Git.
- The readiness gate must not start the live model, daemon, watcher, helper, or WeChat transport.
- Stage22 shadow delivery remains the safe default for internal probes: semantic replies may exist while transport-facing `returned_action` remains suppressible.

## Validation
```powershell
pytest -q tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml show-internal-runtime-readiness
python -m holo_host --config .holo_host.toml accept-stage35
pytest -q
```

## Stop Rules
- Stop if a local config contains an embedded provider API key.
- Stop if DeepSeek is not the primary provider for required internal lanes when running the DeepSeek-backed internal profile.
- Stop if readiness starts WeChat, queues sends, mutates self-memory, or performs a live model call.
- Stop if readiness hides provider fallback or reports an unredacted secret.

## Rollback
Fall back to Stage34 debt-registry and visual-readiness gates. Keep Holo internal-only and WeChat stopped until Stage35 is green again.
