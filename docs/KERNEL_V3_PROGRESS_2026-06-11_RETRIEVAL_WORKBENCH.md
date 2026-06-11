# Kernel v3 Progress 2026-06-11: Retrieval Workbench Pivot

## Direction

This pass starts moving retrieval away from threshold-centered evidence
decisions and toward a model-guided evidence workbench with host-owned
verification.

The new split is:

- model judges semantic relevance, source roles, slot coverage, missing slots,
  and next acquisition moves;
- host still validates IDs, provenance, citations, source authority,
  permissions, budgets, numeric support, and synthesis safety.

This is not a replacement for deterministic verification. It changes where the
semantic judgment lives.

## Implemented

- Added `retrieval.workbench` as a schema-first processor packet.
- Added `kernel_v3/retrieval/workbench.py` with bounded packet construction,
  prompt contract, output validation, and host rejection of invented
  source/evidence/citation IDs.
- Wired `RetrievalOperator` to journal `retrieval_workbench_decision` after
  extraction, deterministic qualification, compaction, evidence, citations, and
  rejected-evidence recording.
- Workbench judgments now affect the retrieval result, not only diagnostics:
  - if the model references an existing rejected/compacted evidence ID as
    accepted or rescued, the host can promote it into real `retrieval_evidence`
    and `retrieval_citation` records;
  - hard host rejections remain non-rescuable, including weak source authority,
    target-entity mismatch, wrong SEC companyfacts entity, and template
    placeholder evidence;
  - if deterministic coverage checks fail for semantic facet reasons while the
    workbench judges the citable evidence sufficient, the host can mark the
    retrieval sufficient with `workbench_semantic_sufficient`;
  - workbench `next_queries`, `next_source_families`, and
    `next_document_targets` are converted into `next_tool_actions` when the
    report remains insufficient.
- Added retrieval report diagnostics for:
  - `workbench_decision`
  - `rescued_count`
  - semantic missing slots
  - next queries
  - next source families
  - next document targets
  - host validation diagnostics
- Added finance benchmark trace metrics and summary fields for workbench
  participation, semantic gaps, requested rescues, actual host-approved
  rescues, and blocked rescues.
- Added a `DocumentReader` boundary inside extraction:
  - PDF parsing tries optional `pypdf`, then optional `pdfminer.six`;
  - fallback remains the previous literal/hex PDF extractor;
  - unit tests do not require optional PDF dependencies;
  - extraction diagnostics expose parser used, chars extracted, table-like
    block count, pages, and fallback failure reason where available.
- Loosened `retrieval.workbench` processor schema and moved shape handling into
  host validation:
  - live model aliases such as `evidence_sufficiency`, `filled_slots`,
    `key_source_roles`, and `next_acquisition_moves` are normalized;
  - object-style `next_queries` / `next_document_targets` are normalized instead
    of being stringified into bad search queries;
  - Python-literal-style object output can be repaired into JSON-compatible
    dicts before host validation.
- Coupled workbench decisions back into the agent loop:
  - URL document targets become `model_guided_document_target` next actions;
  - if the model planner fails after an insufficient retrieval report, the host
    can execute the latest workbench semantic next move as a bounded
    `retrieval.run` fallback;
  - workbench follow-up payloads preserve their model-selected query and are not
    rewritten by generic query-diversification supervision.

## Host Boundary

The workbench is the semantic judge, not an executor. It cannot create source,
evidence, citation, formula, or numeric IDs. The host validates references,
keeps provenance attached to rescued evidence, constructs citations itself, and
still owns authority, permission, budget, numeric verification, and synthesis
gates.

## Validation

```bash
.venv/bin/python -m compileall -q kernel_v3
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_retrieval_workbench.py \
  tests/test_kernel_v3_phase5_semantic_processors.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_phase6_agent_runtime.py -q
```

Result:

```text
compileall passed
135 passed in 1.87s
46 passed in 93.77s
```

Additional focused checks:

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_phase96_retrieval_html_extraction.py \
  tests/test_kernel_v3_phase98_sec_edgar_provider.py::test_sec_companyfacts_extracts_capital_expenditures_for_cash_flow_questions \
  tests/test_kernel_v3_finance_engine.py::test_finance_fallback_prefers_sec_companyfacts_over_secondary_market_sources \
  tests/test_kernel_v3_finance_engine.py::test_finance_fact_ledger_extracts_sec_companyfacts_spans -q
```

Result:

```text
11 passed
```

## Next

Live FinanceBench doc-retrieval probes with real model/retrieval calls show the
pivot is partially working but not solved:

- `run_financebench_doc_live1_workbench_v4`: workbench decisions reached
  benchmark metrics, but evidence remained `0`; failure localized to target PDF
  extraction and workbench next moves not being executed by the loop.
- `run_financebench_doc_live1_workbench_v6`: after workbench follow-up coupling,
  the same item produced `77` finance facts, `77` claims, citations present,
  slot frame present, transform plans present, verifier gate passed, synthesis
  gate passed, and workflow/substrate score `1.0`; it still failed numeric
  scoring because the selected supported figure came from secondary current
  StockAnalysis cash-flow data (`899M`) instead of the FY2018 10-K cash-flow
  statement gold value (`1577M`).
- `run_financebench_doc_live1_workbench_v7`: confirmed more facts can be
  acquired, but extra loop budget increased cost and did not improve numeric
  correctness.
- `run_financebench_doc_live1_binding_v7`: after target-document binding,
  SEC companyfacts full-body fetch for structured JSON, `period_fy` parsing, and
  target fact ranking, the first FinanceBench doc-retrieval item passed:
  `numeric_within_tolerance`, `retrieval_runs=1`, `facts=114`, `claims=114`,
  citation preservation `1.0`, numeric verifier / verifier gate / synthesis
  gate `passed`, unsupported numeric claim rate `0`, and answer numeric support
  `100%`.
- `run_financebench_doc_live3_binding_v1`: the first small follow-up probe was
  `1/3`. All three items reached claim ledger, slot frame, and transform plan,
  but items 2-3 were blocked by unsupported numeric synthesis / missing
  line-item support.
- `run_financebench_doc_live3_binding_v2`: the focused follow-up is now `2/3`.
  Item 2 closes after two narrow fixes: inline benchmark prompts that start the
  question with `Assume ...` no longer pollute `doc_period`, and balance-sheet
  net PP&E / net PPNE binds to SEC `PropertyPlantAndEquipmentNet`. Summary:
  pass rate / numeric accuracy `0.6667`, claim-ledger / slot-frame /
  transform-plan present rate `1.0`, citation preservation `0.6667`,
  synthesis-gate pass rate `0.6667`, and unsupported numeric claim rate
  `0.3333`. Item 3 remains the next true workflow gap: a capital-intensity
  judgment requiring PP&E / assets / capex / operating-cash-flow slots and a
  supported transform, not another fixed answer heuristic.

Remaining gap:

- Workbench semantic judgment is now visible and can drive follow-up retrieval,
  but document acquisition still needs a stronger SEC filing/HTML/XBRL reader so
  the model-guided missing slot can bind to the target 10-K cash-flow statement
  instead of drifting to secondary market pages.
- Cost is still high for live doc-retrieval; context compression and fewer
  planner retries are required after the evidence path is stable.

Issue #3 P0 implementation adds the missing target-binding boundary without
turning the benchmark into a fixed answer table:

- FinanceBench doc-retrieval payloads now derive `target_document_binding`
  fields for the company, target document link/name/type, document period,
  required statement/table, required line item, and primary-source requirement.
- Retrieval Workbench packets expose the binding, required statement, and
  required line item, so the model judges evidence with the same target document
  contract the host will later verify.
- Document extraction now adds target-window candidates when a binding is
  present. The first required case is cash-flow statement capex/PP&E purchase
  rows with the target year in the surrounding table window.
- Finance facts are annotated with target-binding scores and reasons.
  `primary_source_numeric_binding` selects facts satisfying target document /
  primary source / period / line-item / statement constraints and journals
  rejected alternatives, including secondary market pages.
- `verify_finance_answer` filters material numeric support through that resolver
  when a primary source is required, so a secondary/current `899M` value cannot
  support an answer for the FY2018 target filing row.

Current local validation:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_retrieval_workbench.py \
  tests/test_kernel_v3_retrieval_document_expansion.py \
  tests/test_kernel_v3_phase98_sec_edgar_provider.py \
  tests/test_kernel_v3_phase99_source_query_provider.py -q
```

Result:

```text
207 passed
```

Issue #3 live1 validation is now closed by
`run_financebench_doc_live1_binding_v7`, and the focused live3 follow-up
`run_financebench_doc_live3_binding_v2` improves the small probe to `2/3`.
Task Compiler v1 now adds the missing program boundary for that next step:
finance runtime journals `compiled_task_program` records with generic
`TaskSpec`, `EvidenceSpec`, and `TransformSpec` payloads. The live probe
`run_financebench_doc_live3_task_compiler_v1` still scores `2/3`, but
compiled-program coverage is `1.0`; item 3 is compiled as a capital-intensity
`compute` task with explicit missing slots for capital expenditures, operating
cash flow, net PP&E, and assets. The next FinanceBench doc-retrieval work should
therefore focus on filling those slots and binding calculator traces, not on
broad threshold expansion or fixed answer tables.

The target-slot follow-up closes this first slice. After preserving
target-bound line-item evidence through compaction and accepting SEC
companyfacts as the structured companion to the target filing for multi-slot
compute tasks, `run_financebench_doc_live3_target_slots_v4` passes `3/3`.
The previously failing capital-intensity item now has five target facts,
zero missing slots, one calculator/formula trace, numeric verifier passed,
verifier gate passed, synthesis gate passed, citation preservation `1.0`, and
unsupported numeric claim rate `0`. A broader live10 probe,
`run_financebench_doc_live10_target_slots_v1`, is `3/10`; the remaining failures
are mostly document/table extraction and source-resolution gaps for later
FinanceBench rows, not the first-slice target binding bug.

2026-06-12 follow-up:

- `run_financebench_doc_live3_model_net_v1` revalidates the first live3 slice
  with real model and network calls: pass rate / numeric accuracy `1.0`,
  citation preservation `1.0`, unsupported numeric claim rate `0`, average
  retrieval runs `1.3333`, and average tokens `116,822.7`. This is the
  reportable live-model check for the closed first slice.
- `run_financebench_doc_item4_model_net_v6` shows the next failure boundary.
  The Workbench's semantic missing slots now prevent premature finalization and
  trigger a second retrieval; source hosts include `investors.3m.com`, and the
  required-source miss is cleared. The row still fails answer scoring because
  the qualitative operating-margin driver explanation is not synthesized from
  the target MD&A evidence.
- `run_financebench_doc_item4_model_net_v7` is intentionally not counted as a
  quality pass even though the benchmark scorer marks it passed: Holo's own
  verifier gate and synthesis gate fail, citation preservation is `0`, and the
  output is a failure report. It is useful as evidence that benchmark scoring
  alone is weaker than the host-owned gate stack.
