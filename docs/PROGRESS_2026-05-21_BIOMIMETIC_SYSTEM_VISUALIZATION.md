# Holo Biomimetic System Visualization Progress - 2026-05-21

## Objective

Build a paper-facing interactive workbench for Holo's observable biomimetic memory dynamics.

The target is not a decorative graph. The page must expose how the subject runtime moves through:

- episodic archive pressure
- durable semantic memory
- candidate-memory promotion pressure
- affective/homeostatic proxy vectors
- route selection and deep-recall cost
- Mind Graph topology
- vector-index and substrate health

The workbench remains read-only. It does not send messages, mutate memory, start WeChat, reset state, or make transport decisions.

## Implemented

Added:

- `holo_host/biomimetic_visualization.py`
- CLI command: `python -m holo_host visualize-biomimetic-system`
- tests: `tests/test_biomimetic_visualization.py`
- artifact:
  - `artifacts/stage100/stage100_biomimetic_system_workbench.html`
  - `artifacts/stage100/stage100_biomimetic_system_payload.json`

The visualization has three synchronized panels:

1. Semantic-affective phase space
   - projects each archived turn into a low-dimensional proxy trajectory.
   - axes are derived from memory pressure, affect proxy, latency pressure, route type, and regulation proxy.

2. Memory topology
   - shows memory stores, route nodes, health nodes, vector index, sampled Mind Graph nodes, and temporal frame nodes.
   - supports `focus`, `trace`, and `global` density modes.
   - supports layer filtering.

3. Cortical slice proxy
   - renders deterministic activation units for the current frame's proxy vector.
   - this is explicitly not a biological neuron claim.

The page also includes route pressure and candidate-promotion dry-run readouts. Candidate text and memory text are not emitted.

## Verification

Tests:

```powershell
pytest -q tests/test_biomimetic_visualization.py tests/test_memory_doctor.py tests/test_memory_promotion.py tests/test_cli_chat.py tests/test_memory_admin.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
19 passed
```

Generation smoke:

```powershell
python -m holo_host visualize-biomimetic-system
```

Result:

```json
{
  "status": "ok",
  "html_path": "D:\\Holo\\holo\\artifacts\\stage100\\stage100_biomimetic_system_workbench.html",
  "payload_path": "D:\\Holo\\holo\\artifacts\\stage100\\stage100_biomimetic_system_payload.json",
  "frame_count": 360,
  "node_count": 183,
  "edge_count": 221,
  "raw_text_included": false
}
```

Payload smoke:

```text
holo.biomimetic_visualization.v1
raw_text_included=False
frames=360
nodes=183
edges=221
observable_proxy_only=True
```

Browser-render note: Node Playwright is not installed in the Windows environment, so canvas-level browser pixel verification was not run in this pass.

## Publication Angle

The publishable framing should be:

> A redacted interactive workbench for observable affective-semantic memory dynamics in a continuous LLM-agent runtime.

The contribution is not "the model has consciousness." The contribution is an inspectable method for turning a continuous agent runtime into:

- a memory substrate health record
- a semantic-affective movement trace
- a topology of recall and consolidation pressure
- a replayable visual artifact suitable for annotation and ablation

## Next Work

1. Add browser-level verification once Playwright is available.
2. Connect live `inspect-mind` snapshots into the trajectory so new CLI conversations can append frames.
3. Add paper export: PNG panels, JSON schema, methods table, and anonymized sample manifest.
4. Add ablation overlays: memory-drop, route-forced fast path, deep-recall-disabled, and promotion-plan-disabled.
5. Add human annotation hooks for publishable evaluation.

## Boundary

- WSL remains the authoritative brain.
- The visualization is read-only.
- It reports observable proxies only.
- It does not claim real human emotion, consciousness, hidden reasoning, or biological brain state.
