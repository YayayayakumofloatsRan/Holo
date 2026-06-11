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

## Host Boundary

The workbench is the semantic judge, not an executor. It cannot create source,
evidence, citation, formula, or numeric IDs. The host validates references,
keeps provenance attached to rescued evidence, constructs citations itself, and
still owns authority, permission, budget, numeric verification, and synthesis
gates.

## Validation

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_retrieval_workbench.py \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_phase6_agent_runtime.py -q
```

Result:

```text
49 passed in 106.93s
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

- Run FinanceBench doc-retrieval live3 with workbench enabled.
- Check whether workbench decisions produce useful semantic missing slots and
  next source-family/document-target moves.
- Check whether model-guided rescues increase citable finance facts without
  violating host authority/provenance gates.
