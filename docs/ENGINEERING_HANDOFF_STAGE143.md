# Engineering Handoff Stage143

Date: 2026-05-24

## Summary

Stage143 adds a deterministic packet-budget and stop-reason report over the Stage132/142 chain. Holo now exposes why the fast packet ran, why the deep packet ran or was skipped, what cache hint and budget tag were involved, what token/timing estimate was available, and whether Stage142 novelty gating affected the final stop reason.

Stage143 is observability only. It does not add provider calls, memory writes, tool execution, transport changes, WeChat starts, or a second loop.

## Files Changed

- `holo_host/stage143_packet_budget.py`
  - Adds `holo.stage143.packet_budget.v1`.
  - Builds packet reports from existing Stage132, Stage124, Stage121, Stage142, grounding, timing, usage, and debug metadata.
  - Falls back to deterministic token estimates when provider usage is unavailable.

- `holo_host/processors.py`
  - Stores `stage143_packet_budget` in `ReplyPlan.debug` for both fast-only and fast+deep paths.
  - Passes the report into Stage135 topology construction.

- `holo_host/reply_api.py`
  - Rebuilds the report after Stage139/140/141/142 finalization so final grounding and novelty outcomes are reflected.
  - Propagates the report into reply JSON, outgoing metadata, and archive/observe metadata.
  - Preserves existing processor-supplied Stage135 topology instead of overwriting it.

- `holo_host/stage135_i_state_topology.py`
  - Adds optional `packet_budget_gate` node and compact metrics.

- `tests/test_stage143_packet_budget.py`
  - Covers fast-only, fast+deep, Stage142 stop linkage, missing-usage fallback, reply/archive propagation, topology node, and visible-text leak prevention.

- `tests/test_stage132_progressive_conscious_stream.py`
  - Verifies processor debug contains Stage143 reports for deep and fast-only paths.

- `tests/test_stage135_i_state_topology.py`
  - Verifies the packet-budget gate and processor topology propagation.

- `docs/STAGE143_PACKET_BUDGET_STOP_REASON.md`
- `docs/ENGINEERING_HANDOFF_STAGE143.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage143.packet_budget.v1
```

## Runtime Propagation

Stage143 is exposed as:

- `ReplyPlan.debug["stage143_packet_budget"]`
- `result["stage143_packet_budget"]`
- `result["stage143_packet_budget_stop_reason"]`
- `result["stage143_packet_budget_packet_count"]`
- `result["stage143_packet_budget_sent_count"]`
- `result["stage143_packet_budget_skipped_count"]`
- outgoing metadata
- archive/observe metadata
- optional Stage135 `packet_budget_gate`

## Examples

Fast-only:

```text
fast packet: sent, reason=always_run_first_packet
deep packet: skipped, reason=provider_fast_packet_said_fast_answer_enough
stop_reason=provider_fast_packet_said_fast_answer_enough
```

Fast plus deep:

```text
fast packet: sent, reason=always_run_first_packet
deep packet: sent, reason=fast_packet_deep_packet_needed
stop_reason=deep_packet_completed
```

Stage142 suppression:

```text
deep packet ran, but A'' was suppressed as duplicate
stop_reason=stage142:suppressed_duplicate
```

Missing usage:

```text
provider usage absent
estimated_tokens derived from bounded context character count
```

## Verification

Targeted Stage143/132/142:

```powershell
python -m pytest tests\test_stage143_packet_budget.py tests\test_stage132_progressive_conscious_stream.py tests\test_stage142_semantic_novelty_gate.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage143-targeted
```

Observed:

```text
24 passed in 2.15s
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage143-runtime
```

Observed:

```text
87 passed in 25.40s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Observed:

```text
518 passed in 188.86s (0:03:08)
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
- No tool execution.
- No tool authority changes.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage132 continuation remains provider-requested.
- Stage142 visible-expression gating remains authoritative.
- Stage139, Stage140, and Stage141 grounding reports remain authoritative.

## Next Suggested Stage

Stage144 should calibrate packet policy using observed Stage143 data: compare packet cost, stop reasons, Stage142 suppression, tool/memory grounding outcomes, and visible usefulness without changing runtime authority.
