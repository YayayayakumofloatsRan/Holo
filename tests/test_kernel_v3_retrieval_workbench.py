from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.contracts import FetchedDocument


def test_retrieval_operator_journals_model_workbench_decision() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench",
        query="Find ExampleCo FY2024 revenue from the annual report",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=3,
        metadata={
            "workflow_type": "filing_document_qa",
            "required_slots": ["revenue", "period", "source"],
        },
    )
    source = SearchSource(
        source_id="source-annual-report",
        provider="fake",
        uri="https://example.com/exampleco-2024-annual-report",
        title="ExampleCo 2024 Annual Report",
        snippet="Annual report with revenue.",
        metadata={"source_kind": "annual_report", "source_family": "company_ir", "authority_level": "primary"},
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "continue",
                "reason_summary": "Revenue evidence exists, but operating income remains missing.",
                "accepted_evidence_ids": ["evidence-span-doc-goal-workbench-1-1"],
                "rescued_evidence_ids": [],
                "rejected_evidence_ids": [],
                "source_roles": [
                    {
                        "source_id": "source-annual-report",
                        "role": "annual_report",
                        "confidence": 0.91,
                        "reason": "Primary annual report source.",
                    }
                ],
                "slot_assessments": [
                    {
                        "slot": "revenue",
                        "status": "filled",
                        "supporting_evidence_ids": ["evidence-span-doc-goal-workbench-1-1"],
                        "reason": "The span states FY2024 revenue.",
                    },
                    {
                        "slot": "operating_income",
                        "status": "missing",
                        "supporting_evidence_ids": [],
                        "reason": "No operating income span is present.",
                    },
                ],
                "covered_slots": ["revenue"],
                "missing_slots": ["operating_income"],
                "assumptions_needed": [],
                "next_queries": ["ExampleCo FY2024 operating income annual report"],
                "next_source_families": ["company_ir"],
                "next_document_targets": ["FY2024 annual report income statement"],
                "limitations": ["Only one revenue span was extracted."],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "ExampleCo FY2024 revenue was $10 million in the annual report."}),
        processor_fabric=fabric,
    )

    report = operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench",
        run_id="run-workbench",
    )

    workbench_records = journal.records(task_id="task-workbench", kind="retrieval_workbench_decision")
    assert len(workbench_records) == 1
    workbench = workbench_records[0].data
    assert workbench["decision"] == "continue"
    assert workbench["missing_slots"] == ["operating_income"]
    assert workbench["source_roles"][0]["role"] == "annual_report"
    assert report.diagnostics["retrieval_workbench"]["next_queries"] == ["ExampleCo FY2024 operating income annual report"]
    processor_requests = journal.records(task_id="task-workbench", kind="processor_request")
    assert any(record.data["task_type"] == "retrieval.workbench" for record in processor_requests)


def test_retrieval_workbench_host_validation_drops_invented_ids() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench-invalid",
        query="Find ExampleCo FY2024 revenue",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=3,
    )
    source = SearchSource(
        source_id="source-example",
        provider="fake",
        uri="https://example.com/report",
        title="ExampleCo Report",
        snippet="Revenue.",
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "sufficient",
                "reason_summary": "The model tried to cite invented IDs.",
                "accepted_evidence_ids": ["invented-evidence"],
                "rescued_evidence_ids": ["invented-rescue"],
                "rejected_evidence_ids": [],
                "source_roles": [{"source_id": "invented-source", "role": "annual_report", "confidence": 0.9, "reason": "bad"}],
                "slot_assessments": [],
                "covered_slots": [],
                "missing_slots": [],
                "assumptions_needed": [],
                "next_queries": [],
                "next_source_families": [],
                "next_document_targets": [],
                "limitations": [],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "ExampleCo FY2024 revenue was $10 million."}),
        processor_fabric=fabric,
    )

    operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench-invalid",
        run_id="run-workbench-invalid",
    )

    workbench = journal.records(task_id="task-workbench-invalid", kind="retrieval_workbench_decision")[0].data
    assert workbench["accepted_evidence_ids"] == []
    assert workbench["rescued_evidence_ids"] == []
    assert workbench["source_roles"] == []
    assert workbench["diagnostics"]["host_validation"]["valid"] is False
    assert workbench["diagnostics"]["host_validation"]["invalid_references"]["evidence_ids"] == [
        "invented-evidence",
        "invented-rescue",
    ]


def test_pdf_document_reader_diagnostics_are_exposed_on_spans() -> None:
    goal = SearchGoal(
        goal_id="goal-pdf-reader",
        query="capital expenditures 1577",
        max_spans_per_document=2,
    )
    document = FetchedDocument(
        document_id="doc-pdf-reader",
        goal_id=goal.goal_id,
        source_id="source-pdf-reader",
        uri="https://example.com/report.pdf",
        title="ExampleCo PDF Report",
        artifact_id="artifact-pdf-reader",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "application/pdf"},
    )
    body = "%PDF-1.4\n1 0 obj <<>> stream\n(Capital expenditures were 1577 in FY2018.) Tj\nendstream\n%%EOF"

    spans = extract_spans(goal=goal, document=document, body=body)

    assert spans
    reader = spans[0].metadata["document_reader"]
    assert reader["parser_used"] in {"pdf_text_literals", "pdf_text_pypdf", "pdf_text_pdfminer"}
    assert reader["chars_extracted"] > 0
