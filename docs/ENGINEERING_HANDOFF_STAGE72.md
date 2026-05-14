# Engineering Handoff Stage72

Stage72 adds correction-reactivation markers to close the provider-replay gap
identified by Stage71.

## Scope

- Updated scheduler: `holo_host/bionic_memory_scheduler.py`.
- Updated lifecycle: `holo_host/bionic_memory_lifecycle.py`.
- Regression tests:
  - `tests/test_bionic_memory_scheduler.py`
  - `tests/test_bionic_memory_lifecycle.py`
  - `tests/test_bionic_consciousness_flow.py`
- Operator docs: `docs/STAGE72_CORRECTION_REACTIVATION_MARKER.md`.

## Boundary

Stage72 is prompt-scheduling and diagnostic lifecycle only:

- no self-memory writes
- no policy writes
- no transport writes
- no watcher authority
- no downstream MCP exposure
- no runtime decision authority
- no unbounded loop

## Runtime Contract

Correction cues in the current query or latest user intent create a bounded:

```text
correction_reactivation_marker=<text>
```

The marker is protected dynamic memory and can flow through:

- `hippocampal_index.dynamic_lines`
- `prompt_dynamic_lines`
- `salience_gate.sources`
- `consolidation_targets.targets`
- lifecycle `replay_plan.sources`
- consciousness-flow `memory_reactivation`

The marker does not write memory. It raises replay pressure and provider-visible
dynamic context for the current turn.

## DeepSeek Evidence

Completed with real DeepSeek provider calls:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --runs 3 --turns 10 --max-total-tokens 180000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.html
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --output artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.html
```

Provider trace:

- `status=complete`
- `collected_turn_count=30`
- `real_provider_trace=true`
- `observed_total_tokens=135043`
- `stopped_reason=completed`
- `max_latency_ms=617411.46`

Stage71 evaluator over the Stage72 trace:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.011205`
- `correction_survival_proxy_delta=0.048457`
- `flow_to_reply_coupling_delta=-0.342426`
- `prompt_cost_delta=0.033333`
- `boundary_violation_delta=0.0`

Absolute provider comparison:

- baseline `hippocampal_reactivation` improved from `0.897044` to `0.918328`.
- baseline `correction_survival_proxy` improved from `0.801491` to `0.830654`.
- full counterfactual support is still not reached because the improved baseline leaves little headroom for the Stage71 boost condition.

## Verification

Completed:

```powershell
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py
python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\bionic_memory_lifecycle.py holo_host\bionic_consciousness_flow.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py
git diff --check
```

Results:

- focused scheduler/lifecycle/flow tests passed with `14` tests.
- related scheduler/context/stage46 regression passed with `38` tests.
- compile passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage73 should separate two metrics:

- absolute provider improvement after a mechanism lands
- residual counterfactual headroom after that mechanism lands

Then run repeated or longer DeepSeek cells to resolve the current 30-turn
geometry/attractor limitation.
