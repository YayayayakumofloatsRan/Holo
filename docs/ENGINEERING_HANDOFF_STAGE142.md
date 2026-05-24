# Engineering Handoff Stage142

Date: 2026-05-24

## Summary

Stage142 adds a deterministic semantic novelty gate for progressive visible bubbles. A'' now emits only when it adds useful semantic value, concrete task progress, grounded tool feedback, a memory limitation, or an explicit correction. Duplicate, low-value, contradicted, or ungrounded continuation bubbles are suppressed or trimmed before delivery and archive.

## Files Changed

- `holo_host/stage142_semantic_novelty_gate.py`
  - Adds `holo.stage142.semantic_novelty_gate.v1`.
  - Implements semantic role classification, novelty/overlap scoring, contradiction checks, grounding-block checks, and bubble trimming/suppression.

- `holo_host/stage132_progressive_conscious_stream.py`
  - Runs Stage142 inside `merge_stage132_reply_bubbles()`.
  - Preserves existing list-return behavior.
  - Adds `return_metadata=True` for callers that need the Stage142 report.

- `holo_host/processors.py`
  - Stores `stage142_semantic_novelty` in `ReplyPlan.debug`.
  - Passes the report into Stage135 topology construction.

- `holo_host/reply_api.py`
  - Propagates Stage142 metadata into reply JSON, outgoing metadata, and archive/observe metadata.
  - Runs the gate for planned progressive bubbles when a processor did not already provide Stage142 metadata.

- `holo_host/stage135_i_state_topology.py`
  - Adds an optional `semantic_novelty_gate` node and compact metrics.

- `tests/test_stage142_semantic_novelty_gate.py`
  - Covers duplicate suppression, prefix trimming, valid tool feedback, valid memory limitation, unsupported memory detail blocking, ungrounded tool claim blocking, contradiction blocking, visible-text leak prevention, Stage132 merge integration, and metadata shape.

- `tests/test_stage132_progressive_conscious_stream.py`
  - Verifies Stage142 metadata in processor debug.

- `tests/test_holo_host.py`
  - Verifies reply JSON/archive metadata propagation.

- `tests/test_stage135_i_state_topology.py`
  - Verifies the optional topology gate node.

- `docs/STAGE142_SEMANTIC_NOVELTY_GATE.md`
- `docs/ENGINEERING_HANDOFF_STAGE142.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage142.semantic_novelty_gate.v1
```

## Runtime Propagation

The Stage142 report is exposed as:

- `ReplyPlan.debug["stage142_semantic_novelty"]`
- `result["stage142_semantic_novelty"]`
- `result["stage142_semantic_novelty_status"]`
- `result["stage142_semantic_novelty_candidate_count"]`
- `result["stage142_semantic_novelty_suppressed_count"]`
- outgoing metadata
- archive/observe metadata
- optional Stage135 `semantic_novelty_gate`

## Examples

Suppressed duplicate:

```text
A'  I can do that.
A'' I can do that.
Result: A'' suppressed.
```

Trimmed prefix duplicate:

```text
A'  I checked the workspace.
A'' I checked the workspace. The tests now pass.
Result: A'' becomes "The tests now pass."
```

Allowed tool feedback:

```text
A'  I will check first.
A'' I checked the workspace and saw docs plus holo_host.
Result: A'' emitted when tool grounding is present.
```

Blocked unsupported memory detail:

```text
A'  Let me answer carefully.
A'' I remember you prefer fewer emoji.
Stage141: unsupported_memory_detail.
Result: A'' blocked.
```

Blocked unrepaired contradiction:

```text
A'  I can read that file.
A'' I cannot read that file.
Result: A'' blocked unless it explicitly says it is correcting the earlier statement.
```

## Verification

Targeted Stage142/132:

```powershell
python -m pytest tests\test_stage142_semantic_novelty_gate.py tests\test_stage132_progressive_conscious_stream.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage142-targeted
```

Observed:

```text
17 passed in 0.56s
```

Grounding regression:

```powershell
python -m pytest tests\test_memory_alignment.py tests\test_memory_grounding.py tests\test_tool_grounding.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage142-grounding-regression
```

Observed:

```text
18 passed in 0.57s
```

Reply API regression:

```powershell
python -m pytest tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage142-holo-host
```

Observed:

```text
76 passed in 17.16s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Observed:

```text
510 passed in 69.12s (0:01:09)
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

- No provider calls.
- No memory writes.
- No tool authority changes.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage132 continuation remains provider-requested.
- Stage139, Stage140, and Stage141 grounding reports remain authoritative.

## Next Suggested Stage

Stage143 should add a packet-budget and stop-reason report: why each packet was sent, skipped, continued, or stopped, with cache hints, token estimates, elapsed time, grounding results, and Stage142 novelty outcome.
