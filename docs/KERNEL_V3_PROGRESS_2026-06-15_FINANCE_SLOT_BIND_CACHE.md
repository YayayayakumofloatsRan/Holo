# Kernel v3 Progress - 2026-06-15 Finance Slot Binding and Cache Discipline

## Scope

This note records the current Kernel v3 finance/general-capability iteration after the 2026-06-15 night work. The goal remains unchanged: improve real finance problem solving first, while preserving the general agent base, cache discipline, and model-owned decision loop.

## Hard Constraint Preserved

Core semantic decisions must stay with the LLM:

- The host must not classify fiscal period scope with fixed `period/form/fp` tables.
- The host must not choose annual vs quarterly facts with deterministic ranking rules.
- The host may validate schemas, fact id existence, numeric parseability, formula dependencies, tool execution, provenance, and verifier gates.
- `finance.slot_bind` is the model-owned fact-to-slot binding stage. The host only executes the model-selected calculator plan.

## Changes Completed

1. Removed host semantic fact ranking from the strict finance path.

- `_rank_finance_facts_for_model` now preserves source extraction order.
- Final synthesis/rescue diagnostics no longer tell the model to use host-ranked or metric-intent-preferred facts.
- Judge/slot-bind packets no longer expose `finance_metric_intent` or `finance_question_period_scope`.
- Regression tests now assert that these fields are not exposed as model guidance.

2. Standardized the `finance.slot_bind` processor interface.

- `next_action` is normalized when the model returns a string, `null`, list, or dict.
- Formula request aliases such as `calculations`, `formulas`, `calculator_calls`, and `tool_calls` are normalized to `formula_requests`.
- This fixed the live failure mode where DeepSeek produced a plausible `decision=ready` slot-bind JSON but schema validation rejected `next_action`.

3. Made finance prompts more cache-friendly.

- `task.compile` now keeps stable contract/schema first and places the compact fact ledger before task-specific objective fields inside the dynamic packet.
- `finance.slot_bind` now places raw facts before task-specific question/program fields.
- This follows the provider-side prefix-cache principle: stable or reusable long context should appear before the changing question when feasible.

4. Added chained calculator support for model-planned formulas.

- The model may now set a formula variable to a prior `formula_name` or `{"formula_ref": "name"}`.
- The host resolves that variable from the already executed `FormulaTrace`, then merges the upstream `input_fact_ids` into the downstream trace.
- This addresses the live pattern where the model requested average inventory first and DIO second, but the old host rejected the final DIO formulas as `literal_not_numeric`.

5. Added model-owned `finance.slot_bind` JSON repair and adaptive structured-output budgets.

- `finance.slot_bind` now uses a compact output contract: bounded list sizes, short per-binding reasons, short `reason_summary`, and no prose outside JSON.
- If the first `finance.slot_bind` response is malformed or truncated, Kernel v3 asks the model to repair or re-emit the same slot-binding decision as valid JSON against the same raw facts and compiled program.
- The host still does not choose fiscal periods, line items, facts, or formulas. It only validates schema, fact id existence, numeric parseability, formula references, and calculator execution.
- `finance.slot_bind` now uses an adaptive `max_tokens` cap of `4096`, `6144`, or `8192` based on fact count and transform/evidence complexity.
- `task.compile` now uses an adaptive `max_tokens` cap of `4096`, `6144`, or `8192` based on fact/program complexity, reducing the observed 4096-token truncation failure mode.

## Live Smoke Evidence

Command:

```bash
DEEPSEEK_API_KEY="$(powershell.exe -NoProfile -Command '$v=[Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY","User"); if([string]::IsNullOrWhiteSpace($v)){$v=[Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY","Machine")}; [Console]::Out.Write($v)')" \
  .venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/fabv2_dev10.jsonl \
  --dev-gold data/bench/finance/fabv2_dev10.gold.jsonl \
  --limit 1 --online --live-retrieval --live-allow-all-hosts \
  --execution-profile finance-capability \
  --thread-prefix finance-slotbind-schema-live-20260615-v1 \
  --output .state/kernel_v3/bench/finance/run_finance_slotbind_schema_live_20260615_v1.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_finance_slotbind_schema_live_20260615_v1.summary.json \
  --live-cache-dir .state/kernel_v3/live_cache/finance-cache-20260615 \
  --max-agent-steps 4 --max-agent-tool-calls 3 --max-output-tokens auto
```

Result summary:

- Item: `fabv2-hd-low-dio`
- Status: `ungraded` by strict harness, but dev annotation available.
- Overall dev annotation score: `0.8039`
- Workflow score: `0.8824`
- Substrate score: `1.0`
- Numeric score: `0.3333`
- Calculator used rate: `1.0`
- Formula trace present rate: `1.0`
- Retrieval runs: `3`
- Total tokens: `462,943`

What improved:

- Previous live slot-bind failed at schema validation.
- New live run reached `finance_slot_bind status=ready`.
- Model-selected formula plans were executed by `calculator.compute`.
- The benchmark saw calculator traces and passed the `calculator_trace_required` dealbreaker.

What remains weak:

- The answer still missed HD DIO and the difference target.
- The model selected imperfect fiscal-year facts for HD.
- Before the chained-calculator patch, only intermediate average-inventory traces were accepted; final DIO formulas with formula-result dependencies were rejected.
- Full synthesis prompt reached about `598k` chars and exceeded the per-call prompt budget, forcing compact rescue.
- Numeric verifier still failed with unsupported answer numbers.

## Local Verification

After the interface/cache/chained-calculator/JSON-repair changes:

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_execution_profile.py \
  tests/test_kernel_v3_processor_usage.py \
  tests/test_kernel_v3_retrieval_workbench.py -q
```

Result:

```text
219 passed
```

The additional regression test simulates a malformed `finance.slot_bind` JSON response followed by a model repair response. It verifies that the repaired model-selected fact ids become a calculator plan and that the journal records `repair_attempted=true`.

## Current Diagnosis

The finance subsystem is now closer to the intended model-and-tools architecture:

- LLM compiles the task.
- LLM binds facts to slots.
- LLM requests calculator formulas.
- Host validates and executes the requested tool calls.
- Host records traces and verifies final numeric support.

The current bottleneck is no longer "can the model call calculator" or "can a malformed but recoverable slot-bind output be retried"; it is now:

- model period/line-item judgment quality under noisy SEC companyfacts;
- final formula trace coverage for all benchmark-scored quantities;
- synthesis context size and compact rescue reliability;
- numeric judge repair should prefer calculator traces and avoid unsupported prose numbers.

## Next Iteration

1. Run a second live smoke after chained-calculator and slot-bind JSON repair to verify final DIO traces are accepted in a real provider call.
2. Add a compact finance synthesis packet that includes formula traces, selected facts, and citations without sending the full 500k+ retrieval report.
3. Improve the model-owned period judgment prompt: require the model to reason from raw `form`, `fp`, `start`, `end`, `duration_days`, `frame`, accession, and source URI, and to explain fiscal-year basis in `reason_summary`.
4. Preserve cost discipline by keeping stable prompt prefixes and measuring DeepSeek `prompt_cache_hit_ratio` for workbench, task.compile, slot-bind, numeric judge, and synthesizer separately.
5. After the single-item live smoke is stable, run a multi-item batch and report pass rate, numeric accuracy, workflow/substrate score, calculator trace rate, and cache ratio.

## External Reference

- DeepSeek Context Caching guide: `https://api-docs.deepseek.com/guides/kv_cache`. The relevant operational point is prefix matching: later requests benefit when they fully reuse persisted prompt prefixes, so Kernel v3 should keep stable contracts and reusable long context before turn-specific question text when that does not weaken the task contract.
