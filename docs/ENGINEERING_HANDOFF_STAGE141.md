# Engineering Handoff Stage141

Date: 2026-05-24

## Summary

Stage141 implements memory claim alignment. Holo now checks whether visible memory claims are supported by the concrete content of the selected memory source, not only whether a memory source exists.

## Files Changed

- `holo_host/memory_alignment.py`
  - Adds `holo.memory_alignment.v1`.
  - Extracts English and Chinese memory claims deterministically.
  - Builds evidence texts from Stage140 ledger and existing sidecar/debug metadata.
  - Scores source sufficiency and repairs unsupported, weak, or contradicted details.

- `holo_host/reply_api.py`
  - Runs Stage141 after Stage140.
  - Propagates alignment metadata into reply JSON, outgoing metadata, and archive/observe metadata.
  - Preserves Stage140 missing-source repairs.
  - Rebuilds Stage135 topology with alignment evidence only when a visible memory claim exists.

- `holo_host/stage135_i_state_topology.py`
  - Adds `memory_alignment_gate` and optional claim nodes.
  - Adds memory-alignment metrics.

- `tests/test_memory_alignment.py`
  - Covers missing, aligned, weak, unsupported, contradicted, and repair cases.

- `tests/test_holo_host.py`
  - Covers reply API propagation and archive metadata.

- `tests/test_stage135_i_state_topology.py`
  - Covers the alignment gate in topology.

- `docs/STAGE141_MEMORY_CLAIM_ALIGNMENT.md`
- `docs/ENGINEERING_HANDOFF_STAGE141.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.memory_alignment.v1
```

Main fields:

- `status`
- `claim_count`
- `aligned_claim_count`
- `weak_claim_count`
- `unsupported_claim_count`
- `contradicted_claim_count`
- `claims`
- `repair_required`
- `repair_reason`

## Runtime Propagation

Reply JSON, outgoing metadata, and archive/observe metadata now include:

- `memory_alignment`
- `memory_alignment_status`
- `memory_alignment_claim_count`
- `memory_alignment_unsupported_count`
- `memory_alignment_contradicted_count`

`ReplyPlan.debug` is updated during reply finalization when available. Stage135 topology receives the same report when a visible memory claim exists.

## Claim Examples

Aligned:

```text
Claim: I remember you prefer fewer emoji.
Evidence: user preference: fewer emoji.
```

Weak:

```text
Claim: I remember you told me yesterday that you prefer fewer emoji.
Evidence: user preference: fewer emoji, no time marker.
```

Unsupported:

```text
Claim: I remember you prefer fewer emoji.
Evidence: discussed git diff and tests.
```

Contradicted:

```text
Claim: I remember you prefer more emoji.
Evidence: contradicted ledger row, or preference direction conflict.
```

## Verification

Targeted Stage141/140/135:

```powershell
python -m pytest tests\test_memory_alignment.py tests\test_memory_grounding.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage141-targeted
```

Observed:

```text
24 passed in 1.00s
```

Reply API regression:

```powershell
python -m pytest tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage141-holo-host
```

Observed:

```text
75 passed in 17.07s
```

Stage139 tool grounding regression:

```powershell
python -m pytest tests\test_tool_grounding.py tests\test_tool_benchmark.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage141-tool-regression
```

Observed:

```text
5 passed in 0.32s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Observed:

```text
498 passed in 70.70s (0:01:10)
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
```

Observed:

```text
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
```

Diff check:

```powershell
git diff --check
```

Observed:

```text
passed; Git printed line-ending normalization warnings only
```

## Constraints Preserved

- No self-memory writes.
- No provider path outside processor fabric.
- No WeChat start.
- No watcher or transport authority widening.
- No weakening of Stage139 tool grounding.
- No weakening of Stage140 memory grounding.
- No direct private memory-file reads.

## Next Suggested Stage

Stage142 A' to A'' semantic novelty and contradiction gate. It should consume Stage139, Stage140, and Stage141 reports so unsupported tool or memory claims cannot reappear in a second visible bubble, and continuation only emits when it adds a real semantic role or state delta.
