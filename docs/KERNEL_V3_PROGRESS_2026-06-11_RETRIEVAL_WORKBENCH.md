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

Remaining gap:

- Workbench semantic judgment is now visible and can drive follow-up retrieval,
  but document acquisition still needs a stronger SEC filing/HTML/XBRL reader so
  the model-guided missing slot can bind to the target 10-K cash-flow statement
  instead of drifting to secondary market pages.
- Cost is still high for live doc-retrieval; context compression and fewer
  planner retries are required after the evidence path is stable.
