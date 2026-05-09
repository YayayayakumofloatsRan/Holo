# Stage34: Debt Registry And Visual Readiness

Stage34 closes the remaining offline-verifiable technical debt by turning the weak-spot list into a machine-checkable registry and by making visual-provider readiness explicit.

This stage does not start Holo, WeChat, watcher, or any live transport. It does not mutate self-memory, add a new loop, add a new decision layer, or widen send rights.

## Implemented Surfaces
- `holo_host.debt_registry.current_debt_registry()` returns every known current weak spot with status, evidence, resolution, validation, and next gate.
- `show-debt-registry` exposes the classified debt inventory.
- `CodexRunner.visual_provider_readiness()` checks image-task routing and provider support contracts without making a live model call.
- `show-visual-provider-readiness` exposes text-provider image rejection, image-capable path visibility, and hard boundaries.
- `accept-stage34` requires Stage33 provider contracts to remain green, the debt registry to have no unclassified items, and visual providers to avoid image-capability overclaiming.

## Debt Status Model
- `resolved`: already fixed by an earlier verified stage.
- `bounded_by_stage34`: now covered by Stage34 diagnostics and acceptance.
- `bounded_structural_debt`: known structural debt that must be changed only behind dedicated tests and acceptance.
- `external_precondition`: cannot be proven while Holo remains offline; requires operator-approved live soak or real provider credentials.
- `planned`: intentionally deferred behavior work that must be re-planned before implementation.

## Visual Readiness Contract
- DeepSeek, OpenAI-compatible, and Responses text providers must reject image-path requests.
- `codex_cli` may remain the visible local image-capable processor path.
- `image_understand` routing must be visible through the processor fabric.
- No provider readiness check may perform a live model call.

## Validation
```powershell
pytest -q tests/test_stage34_debt_closure.py tests/test_stage33_provider_contracts.py tests/test_stage32_response_shaping.py
python -m holo_host --config .holo_host.example.toml show-debt-registry
python -m holo_host --config .holo_host.example.toml show-visual-provider-readiness
python -m holo_host --config .holo_host.example.toml accept-stage34
pytest -q
```

## Stop Rules
- Stop if any current weak spot is removed from docs without a registry item.
- Stop if a text-only provider claims image support.
- Stop if Stage34 requires live transport, self-memory mutation, raw provider calls outside the processor fabric, or a new loop.

## Rollback
Ignore Stage34 diagnostics and fall back to Stage33 provider-contract acceptance. Do not restart Holo or widen any runtime capability as part of rollback.
