# Engineering Handoff Stage69

Stage69 adds the bounded inner-stream consciousness clock.

## Scope

- New module: `holo_host/inner_stream.py`.
- New daemon loop: `inner_stream`, driven from `HoloDaemon.run_cycle()`.
- New config keys under `[memory]`: `inner_stream_enabled`, `inner_stream_tick_interval_seconds`, `inner_stream_ring_size`, `inner_stream_model_enabled`, and `inner_stream_model_max_output_tokens`.
- New processor task: `inner_stream_thought`, routed to `subject_main` by default with `micro_fast` fallback.
- New recurrent dynamics: `field_state`, `plasticity_trace`, and `recurrent_context` are carried across ticks and returned to the next processor prompt.
- New biomimetic surrogate layer: neuromodulators, neural-field excitation/inhibition balance, thalamic gain, hippocampal replay pressure, global-workspace ignition, and synaptic LTP/LTD traces.
- Brain status now exposes `inner_stream_state`.
- Loop runner failures are recorded as `status=error` telemetry instead of escaping the daemon cycle.
- New regression coverage: `tests/test_stage69_inner_stream.py` plus daemon/status coverage in `tests/test_holo_host.py`.

## Boundary

The inner stream is a bounded always-on model-backed kernel signal, not a second brain:

- model calls are allowed only through `inner_stream_thought`
- no self-memory writes
- no policy writes
- no transport writes
- no watcher authority
- no downstream MCP exposure
- no autonomous long-term memory promotion

The stream writes only the daemon's volatile ring buffer and compact loop telemetry. The LLM is the processor for micro-thought generation and field perturbation, but it receives no external write or action authority. Any durable memory effect must still pass through existing explicit memory gates.

## Verification

Completed on 2026-05-14:

```powershell
python -m pytest -q tests\test_stage69_inner_stream.py
python -m pytest -q tests\test_holo_host.py::DaemonFlowTests::test_daemon_cycle_runs_inner_stream_without_inbound_message tests\test_holo_host.py::DaemonFlowTests::test_inner_stream_runner_error_is_recorded_without_crashing_daemon_loop tests\test_holo_host.py::DaemonFlowTests::test_daemon_cycle_sends_reply_and_observes_memory tests\test_holo_host.py::ReplyServiceTests::test_brain_status_merges_stage3_loops_for_live_visibility
python -m pytest -q tests\test_stage69_inner_stream.py tests\test_holo_host.py::DaemonFlowTests::test_daemon_cycle_runs_inner_stream_without_inbound_message tests\test_holo_host.py::DaemonFlowTests::test_inner_stream_runner_error_is_recorded_without_crashing_daemon_loop tests\test_holo_host.py::ReplyServiceTests::test_brain_status_merges_stage3_loops_for_live_visibility
python -m pytest -q tests\test_processor_fabric.py
python -m py_compile holo_host\inner_stream.py holo_host\daemon.py holo_host\reply_api.py holo_host\config.py holo_host\codex_runner.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

The first two tests were written before implementation and failed on the missing inner-stream surface, then passed after implementation.
The final full test run passed with `476` tests. Public-release hygiene passed. `git diff --check` passed with only Git CRLF conversion warnings.

Correction note: the first Stage69 commit added the volatile clock and ring buffer. The follow-up correction made each due tick processor-backed through `inner_stream_thought`, because the consciousness stream must actually use the LLM processor rather than only local bookkeeping.

Biomimetic correction: the stream now carries a recurrent dynamic field instead of a standalone safety-wrapped telemetry row. Model output updates activation energy, prediction error, salience, affective tension, dominant attractor, neuromodulators, neural-field E/I balance, hippocampal replay pressure, and synaptic plasticity traces; the next prompt receives that state as substrate.

The biological variables are deterministic runtime surrogates, not claims of measured neural activity. They are meant to make inner-stream dynamics observable and testable: prediction error and attractor novelty potentiate dopamine-like response, salience and arousal tune acetylcholine/norepinephrine-like gain, high conflict reduces serotonin-like stability, and repeated high-energy recurrence raises inhibition through a homeostatic response.

## Operational Notes

`inner_stream_tick_interval_seconds` defaults to `1`, matching the internal heartbeat cadence. The ring buffer defaults to `64` ticks to keep the live working field bounded while still giving dashboards and visualization tools enough temporal context.

## Next Gate

Route `inner_stream_state` and `brain_loop_runs(loop_name=inner_stream)` into the Stage54/55/56 visualization stack, then render live consciousness-flow heatmaps and low-dimensional trajectories from actual runtime ticks.
