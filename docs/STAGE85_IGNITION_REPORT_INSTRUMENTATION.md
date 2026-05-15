# Stage85 Ignition Report Instrumentation

## What Stage85 Adds

Stage85 targets the Stage84 limiting result directly. Stage84 measured
`ignition_report_transfer=0.0` on archived Stage77 traces, but inspection showed
that the Stage77 runtime computed `global_workspace_ignition` and
`ignition_to_reply_coupling` while Stage59/46 trace compaction exported only
`dominant_phase` and `phase_count`.

Stage85 therefore adds a trace-schema repair plus a bounded GNW observability
evaluator:

```powershell
python -m holo_host --config .holo_host.toml evaluate-ignition-report-instrumentation --stream-lattice-json artifacts\stage84\stage84_consciousness_stream_lattice.json --trace-json <provider_trace.json> --output <stage85.html>
```

Implementation:

- `holo_host/ignition_report_instrumentation.py`
- `evaluate-ignition-report-instrumentation`
- trace export repair in `holo_host/bionic_boundary_stress.py`
- regression tests in `tests/test_stage85_ignition_report_instrumentation.py`,
  `tests/test_stage46_bionic_boundary_stress.py`, and
  `tests/test_stage59_provider_trace.py`

## Evidence

### Archived Stage77 Diagnostic

Running Stage85 on the archived Stage77 Pro/Flash cells produced:

- `decision=instrumentation_gap_blocks_gnw_upgrade`
- `supported_scope=diagnostic_trace_schema_repair`
- `stage84_stream_lattice_precondition_supported=true`
- `trace_count=2`
- `total_turn_count=84`
- `structured_ignition_turn_count=0`
- `structured_coupling_turn_count=0`
- `observed_ignition_report_transfer=0.0`
- `stage84_legacy_ignition_report_transfer=0.0`
- `current_trace_instrumentation_gap=true`
- `focused_provider_cell_required=true`
- `real_provider_trace=true`

This means the old `0.0` transfer result is an archived trace observability gap,
not a valid negative biological result.

Generated artifacts:

- `artifacts/stage85/stage85_ignition_report_instrumentation.html`
- `artifacts/stage85/stage85_ignition_report_instrumentation.json`
- `artifacts/stage85/stage85_ignition_report_instrumentation_ignition_report.png`

### Focused Post-Repair Provider Cell

After the schema repair, a focused DeepSeek V4 Pro shadow-runtime cell collected
`6` real-provider turns before the `20000` token budget stopped the run at
`20598` observed tokens.

Stage85 on that focused post-repair trace produced:

- `decision=bounded_ignition_report_instrumentation_supported`
- `supported_scope=structured_gnw_ignition_report_proxy`
- `trace_count=1`
- `total_turn_count=6`
- `structured_ignition_turn_count=6`
- `structured_coupling_turn_count=6`
- `observed_ignition_report_transfer=1.0`
- `stage84_legacy_ignition_report_transfer=0.0`
- `current_trace_instrumentation_gap=false`
- `focused_provider_cell_required=false`
- `real_provider_trace=true`
- `gnw_language_bounded=true`
- `do_not_claim_real_consciousness=true`

Generated artifacts:

- `artifacts/stage85/stage85_focused_deepseek_provider_trace.html`
- `artifacts/stage85/stage85_focused_deepseek_provider_trace.json`
- `artifacts/stage85/stage85_focused_deepseek_provider_trace_provider_trace.png`
- `artifacts/stage85/stage85_focused_ignition_report_instrumentation.html`
- `artifacts/stage85/stage85_focused_ignition_report_instrumentation.json`
- `artifacts/stage85/stage85_focused_ignition_report_instrumentation_ignition_report.png`

## Interpretation

The supported Stage85 claim is bounded:

```text
Holo can now export and evaluate a structured GNW ignition-to-report proxy from
real-provider traces. The first focused post-repair DeepSeek cell shows complete
structured coverage and positive ignition-report transfer.
```

The limitation remains important:

```text
The focused post-repair cell validates instrumentation, not a full replicated
Stage84 stream-lattice result. A Stage84 rerun on that short cell alone had
`ignition_report_transfer=1.0` but was invalidated because
`marker_control_narrows_reactivation=false`; it was not designed as a full
marker-control replication cell.
```

Therefore GNW language is upgraded only from "unobservable in archived traces"
to "instrumented and positive in one focused post-repair real-provider cell."
It is not yet a replicated GNW consciousness result.

## Boundary

Stage85 keeps the Holo authority boundaries:

- evaluator is read-only over JSON evidence
- focused provider cell used shadow runtime
- no live WeChat transport
- no watcher decision authority
- no runtime decision authority added
- no self-memory writes
- no policy writes
- no provider fallback
- no unbounded loop
- no claim of real subjective consciousness

## Next Gate

Stage86 should run replicated focused cells across Pro and Flash with both
structured ignition-report fields and marker-control-compatible false-fact
episodes. Acceptance should require:

- structured ignition/coupling coverage across all new turns
- positive `ignition_report_transfer` in each cell
- Stage84 marker-control precondition remains supported
- no weakening of replay/correction compression
- bounded GNW language until replication is stable
