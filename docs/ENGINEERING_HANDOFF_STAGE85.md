# Engineering Handoff Stage85

Stage85 repairs and evaluates GNW ignition-to-report observability.

## Scope

- Added: `holo_host/ignition_report_instrumentation.py`
- Modified: `holo_host/bionic_boundary_stress.py`
- Modified: `holo_host/cli.py`
- Added tests: `tests/test_stage85_ignition_report_instrumentation.py`
- Updated tests: `tests/test_stage46_bionic_boundary_stress.py`,
  `tests/test_stage59_provider_trace.py`
- Operator doc: `docs/STAGE85_IGNITION_REPORT_INSTRUMENTATION.md`
- Artifacts: `artifacts/stage85/*`

## Boundary

Stage85 preserves the hard authority split:

- WSL/kernel path remains the only subject runtime
- Windows transport remains unused
- no live WeChat transport
- no watcher decision authority
- no runtime decision authority added
- no self-memory or policy writes
- evaluator is read-only over trace JSON
- focused provider run used shadow runtime and no provider fallback

## Mechanism

The public trace compactor now preserves:

- `processor_debug.bionic_consciousness_flow.global_workspace_ignition`
- `processor_debug.bionic_consciousness_flow.ignition_to_reply_coupling`

The Stage85 evaluator separates two cases:

- archived traces that lack structured Stage77 fields
- post-repair traces where structured fields are observable and can be scored

## Commands

Archived Stage77 diagnostic:

```powershell
python -m holo_host --config .holo_host.toml evaluate-ignition-report-instrumentation --stream-lattice-json artifacts\stage84\stage84_consciousness_stream_lattice.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage85\stage85_ignition_report_instrumentation.html
```

Focused post-repair provider cell:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage85_ignition_report_focused --runs 1 --turns 8 --max-total-tokens 20000 --provider-hint deepseek --model deepseek-v4-pro --lane subject_main --max-output-tokens 220 --output artifacts\stage85\stage85_focused_deepseek_provider_trace.html --execute
```

Focused post-repair Stage85 evaluation:

```powershell
python -m holo_host --config .holo_host.toml evaluate-ignition-report-instrumentation --stream-lattice-json artifacts\stage84\stage84_consciousness_stream_lattice.json --trace-json artifacts\stage85\stage85_focused_deepseek_provider_trace.json --output artifacts\stage85\stage85_focused_ignition_report_instrumentation.html
```

## Evidence

Archived Stage77 diagnostic:

- `decision=instrumentation_gap_blocks_gnw_upgrade`
- `total_turn_count=84`
- `structured_ignition_turn_count=0`
- `structured_coupling_turn_count=0`
- `observed_ignition_report_transfer=0.0`
- `current_trace_instrumentation_gap=true`

Focused post-repair provider cell:

- `status=stopped`
- `collected_turn_count=6`
- `real_provider_trace=true`
- `observed_total_tokens=20598`
- `stopped_reason=token_budget_exhausted`

Focused post-repair Stage85:

- `decision=bounded_ignition_report_instrumentation_supported`
- `supported_scope=structured_gnw_ignition_report_proxy`
- `total_turn_count=6`
- `structured_ignition_turn_count=6`
- `structured_coupling_turn_count=6`
- `observed_ignition_report_transfer=1.0`
- `current_trace_instrumentation_gap=false`
- `do_not_claim_real_consciousness=true`

## Verification

Verification completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage85_ignition_report_instrumentation.py -q
python -m pytest tests\test_stage46_bionic_boundary_stress.py::Stage46BionicBoundaryStressTests::test_compact_processor_debug_preserves_memory_lifecycle_and_consciousness_flow tests\test_stage59_provider_trace.py::Stage59ProviderTraceTests::test_execute_collects_stage46_compatible_turns_and_stops_at_budget -q
python -m holo_host --config .holo_host.toml evaluate-ignition-report-instrumentation --stream-lattice-json artifacts\stage84\stage84_consciousness_stream_lattice.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage85\stage85_ignition_report_instrumentation.html
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage85_ignition_report_focused --runs 1 --turns 8 --max-total-tokens 20000 --provider-hint deepseek --model deepseek-v4-pro --lane subject_main --max-output-tokens 220 --output artifacts\stage85\stage85_focused_deepseek_provider_trace.html --execute
python -m holo_host --config .holo_host.toml evaluate-ignition-report-instrumentation --stream-lattice-json artifacts\stage84\stage84_consciousness_stream_lattice.json --trace-json artifacts\stage85\stage85_focused_deepseek_provider_trace.json --output artifacts\stage85\stage85_focused_ignition_report_instrumentation.html
python -m holo_host --config .holo_host.toml evaluate-consciousness-stream-lattice --publication-json artifacts\stage83\stage83_biomimetic_publication_bundle.json --trace-json artifacts\stage85\stage85_focused_deepseek_provider_trace.json --output artifacts\stage85\stage85_focused_consciousness_stream_lattice.html
```

Result:

- red: Stage59 test failed because `global_workspace_ignition` was not exported
- green: Stage85 tests passed with `3 passed`
- trace-compaction regression passed with `2 passed`
- archived Stage77 diagnostic returned `instrumentation_gap_blocks_gnw_upgrade`
- focused post-repair Stage85 returned `bounded_ignition_report_instrumentation_supported`
- focused Stage84 rerun was intentionally not accepted as a full stream-lattice replication because marker-control narrowing was absent in the short cell

## Next Gate

Stage86 should use Stage59/60 to run replicated focused Pro/Flash cells designed
for both marker-control-compatible false-fact episodes and structured
ignition-report observability. Do not broaden observational repeats until this
replication gate is built.
